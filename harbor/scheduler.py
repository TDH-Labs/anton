"""Job engine: due-job computation, dispatch, verify, budget, record (M2)."""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import tempfile
import time
from typing import List, Optional

from .canary import compute_tripwires
from .executor import Executor
from .jobs import Job
from .ledger import Ledger
from .models import RunRecord
from .routes import select_route


class JobEngine:
    def __init__(self, jobs: List[Job], ledger: Ledger, executor: Executor,
                 config: dict, db=None, metering=None, data_dir: Optional[str] = None):
        self.jobs = jobs
        self.ledger = ledger
        self.executor = executor
        self.config = config
        self.db = db
        self.data_dir = data_dir or config.get("general", {}).get("data_dir")

    def _touch_heartbeat(self) -> None:
        if self.data_dir:
            import os
            os.makedirs(self.data_dir, exist_ok=True)
            with open(os.path.join(self.data_dir, "last-heartbeat"), "w", encoding="utf-8") as f:
                f.write(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def _record_metering(self, record: RunRecord) -> None:
        if self.data_dir:
            import os
            from .metering import connect, record
            try:
                conn = connect(os.path.join(self.data_dir, "isolation.db"))
                record(conn, record)
                conn.close()
            except Exception:  # noqa: BLE001 — metering must never break a run
                pass

    def _is_approved(self, job_id: str) -> bool:
        """R1: a gated job may only run with an approved nonce in the approvals table."""
        if not self.data_dir:
            return False
        import os
        import sqlite3
        p = os.path.join(self.data_dir, "isolation.db")
        if not os.path.exists(p):
            return False
        conn = sqlite3.connect(p)
        try:
            row = conn.execute(
                "SELECT status FROM approvals WHERE action=? ORDER BY id DESC LIMIT 1",
                (job_id,)).fetchone()
        finally:
            conn.close()
        return row is not None and row[0] == "approved"

    def by_id(self, job_id: str) -> Optional[Job]:
        return next((j for j in self.jobs if j.id == job_id), None)

    def due_jobs(self, now: Optional[dt.datetime] = None) -> List[Job]:
        now = now or dt.datetime.now(dt.timezone.utc)
        floor = now.replace(second=0, microsecond=0)
        minute_key = floor.strftime("%Y-%m-%dT%H:%M")
        due = []
        for job in self.jobs:
            if job.cron is None or not job.cron.matches(floor):
                continue
            last = self.ledger.last_run(job.id)
            if last is None or not str(last.get("ts", "")).startswith(minute_key):
                due.append(job)  # fire once per matching minute (idempotent)
        return due

    def _usage_today(self, provider: str) -> dict:
        """Tokens/cost for the current UTC day from the ledger (cloud rows only)."""
        tokens_in = tokens_out = 0
        cost = 0.0
        day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        for row in self.ledger.read():
            if not row.get("ts", "").startswith(day):
                continue
            tokens_in += row.get("tokens_in") or 0
            tokens_out += row.get("tokens_out") or 0
            cost += row.get("cost_usd") or 0.0
        return {"tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": cost}

    def enforce_budget(self, job: Job, meta: dict) -> Optional[str]:
        b = self.config.get("budgets", {})
        job_budget = job.budget or {}
        if meta.get("tokens_in") and b.get("tokens_max_per_job") and \
                meta["tokens_in"] > b["tokens_max_per_job"]:
            return f"job token budget breached: {meta['tokens_in']} > {b['tokens_max_per_job']}"
        today = self._usage_today("cloud")
        if b.get("daily_tokens_max") and (today["tokens_in"] + today["tokens_out"]) > b["daily_tokens_max"]:
            return f"daily token budget breached: {today['tokens_in'] + today['tokens_out']}"
        if b.get("daily_cost_usd_max") and today["cost_usd"] > b["daily_cost_usd_max"]:
            return f"daily cost budget breached: ${today['cost_usd']:.4f}"
        return None

    def run_job(self, job: Job, now: Optional[dt.datetime] = None) -> RunRecord:
        now = now or dt.datetime.now(dt.timezone.utc)
        route = select_route(
            local_model=self.config["routes"]["local_model"],
            cloud_model=self.config["routes"]["cloud_model"],
            prefer="local" if job.model_route == "local-default" else "cloud",
        )

        self._touch_heartbeat()

        # R1/R7: hard-gate jobs (money/outbound) require an approved nonce before any run.
        if job.gate and (job.gate.get("money") or job.gate.get("outbound")):
            if not self._is_approved(job.id):
                record = RunRecord.new(task=job.id, exit_code=5, flags="gate-blocked",
                                       output="", model=route.model, provider=route.provider,
                                       duration_ms=0,
                                       ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
                self.ledger.append(record)
                self._record_metering(record)
                return record

        started = time.monotonic()
        result = self.executor.run(job.recipe, model=route.model, provider=route.provider)

        breach = self.enforce_budget(job, {"tokens_in": result.tokens_in,
                                           "tokens_out": result.tokens_out,
                                           "cost_usd": result.cost_usd})
        if breach:
            record = RunRecord.new(task=job.id, exit_code=3, flags="budget-breach",
                                   output=result.output, model=result.model,
                                   provider=result.provider, duration_ms=result.duration_ms,
                                   ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
            self.ledger.append(record)
            return record

        exit_code = result.exit_code
        flags = f"cron;route:{route.provider}"
        if job.dry_run:
            exit_code = 0
            flags += ";dry-run"

        if job.verify and exit_code == 0:
            ok, msg = self._run_verify(job.verify, result.output)
            if not ok:
                exit_code = 4
                flags += f";verify-fail:{msg}"

        record = RunRecord.new(task=job.id, exit_code=exit_code, flags=flags,
                               output=result.output, model=result.model,
                               provider=result.provider, fallback_used=result.fallback_used,
                               tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                               cost_usd=result.cost_usd, duration_ms=result.duration_ms,
                               ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.ledger.append(record)
        self._record_metering(record)
        return record

    def _run_verify(self, verify_cmd: str, output: str) -> tuple[bool, str]:
        fd, path = tempfile.mkstemp(suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(output)
            cmd = verify_cmd.replace("<output>", path)
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                  timeout=30)
            if proc.returncode == 0:
                return True, ""
            return False, (proc.stderr or proc.stdout or "rc=%d" % proc.returncode)[:200]
        except subprocess.TimeoutExpired:
            return False, "verify timed out"
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def run_canary(self) -> List[dict]:
        tripwires = compute_tripwires(self.jobs, self.ledger)
        if tripwires:
            for t in tripwires:
                self.ledger.append(RunRecord.new(task="fleet-canary", exit_code=1,
                                                 flags=f"tripwire:{t['job_id']}"))
        return tripwires
