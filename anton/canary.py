"""Expected-vs-actual canary (R6): now - last_run > 2×cadence -> tripwire."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from typing import Any, List

from .governor import AUTO_EXECUTE, classify
from .jobs import Job
from .ledger import Ledger

FACTOR = 2

# job_id -> (ev, feasibility, risk, kind) for the governor.classify() call
# that decides whether a detected tripwire gets auto-repaired. Scoped to
# Anton's own scheduler/health jobs only (the ones the fresh-install default
# jobs.yaml defines) — not a place to wire in any one deployment's own
# external monitoring jobs; those belong in that deployment's own jobs.yaml,
# which is free to add its own entries here at runtime (see
# register_repair_recipe below) once it knows what "repair" means for them.
REPAIR_RECIPES: dict[str, tuple[float, float, str, str]] = {
    "e2e-canary": (0.9, 0.9, "low", "internal"),
    "daily-digest": (0.9, 0.9, "low", "internal"),
}


def register_repair_recipe(job_id: str, *, ev: float, feasibility: float,
                           risk: str = "low", kind: str = "internal") -> None:
    """Let a deployment map its own job_id to a repair recipe at runtime
    (e.g. from a jobs.yaml loader extension) without editing this module."""
    REPAIR_RECIPES[job_id] = (ev, feasibility, risk, kind)


def _diagnose_n8n_unreachable(engine: Any, job: Job) -> bool:
    """True when `job` dispatches through N8NExecutor and that instance is
    not answering right now.

    This runs BEFORE the REPAIR_RECIPES lookup for n8n-backed jobs, because
    re-running is the wrong repair when the target itself is down: it just
    burns another cycle failing the same way, and (worse) would silently
    mark a real n8n outage as "auto_repaired" the moment the job happened to
    succeed on an unrelated retry. A down n8n instance is diagnosis, not
    repair -- it always surfaces to a human via _record_repair_candidate,
    never auto-executes, regardless of what REPAIR_RECIPES says for this
    job_id. Bounded deliberately: this checks reachability only. An expired
    credential or a genuinely broken third-party integration is not
    something to auto-fix -- see examples/n8n/README.md's Auditor workflow
    for the complementary n8n-side half (a workflow skipping Anton's own
    gate gets deactivated, not silently patched).
    """
    if not job.executor or job.executor.get("name") != "n8n":
        return False
    from .executor.n8n_executor import N8NExecutor
    executor = engine._resolve_executor(job)
    if not isinstance(executor, N8NExecutor):
        return False
    return not executor.available()


def attempt_repairs(engine: Any, tripwires: List[dict]) -> List[dict]:
    """For each tripwire with a mapped repair recipe: score it through the
    governor and either dispatch the repair (re-running the job is the
    repair — it updates last_run, clearing the tripwire) or record a pending
    candidate for human review. Every tripwire produces an observable
    outcome here; none is silently dropped (the bug this closes: detection
    used to fire with no consumer).
    @param engine - a JobEngine (duck-typed here to avoid a scheduler.py <->
    canary.py import cycle: scheduler.py already imports this module).
    """
    outcomes: List[dict] = []
    for t in tripwires:
        job_id = t["job_id"]
        job = engine.by_id(job_id)
        if job is None:
            outcomes.append({"job_id": job_id, "action": "job_missing"})
            continue
        if _diagnose_n8n_unreachable(engine, job):
            outcomes.append({"job_id": job_id, "action": "n8n_unreachable"})
            _record_repair_candidate(engine, job_id, "n8n_unreachable")
            continue
        recipe = REPAIR_RECIPES.get(job_id)
        if recipe is None:
            outcomes.append({"job_id": job_id, "action": "no_recipe"})
            continue
        ev, feasibility, risk, kind = recipe
        ruling = classify(ev, feasibility, risk=risk, kind=kind)
        if ruling.route == AUTO_EXECUTE:
            record = engine.run_job(job)
            outcomes.append({"job_id": job_id, "action": "auto_repaired",
                             "exit_code": record.exit, "route": ruling.route})
        else:
            outcomes.append({"job_id": job_id, "action": "pending_approval", "route": ruling.route})
            _record_repair_candidate(engine, job_id, ruling.route)
    return outcomes


def _record_repair_candidate(engine: Any, job_id: str, route: str) -> None:
    """Surface a non-auto-executable repair the same way delta.py's other
    candidates are surfaced (the `initiatives` table `emit_candidate()`
    writes to) — never silent."""
    data_dir = getattr(engine, "data_dir", None)
    if not data_dir:
        return
    db_path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(db_path):
        return
    from .vault import emit_candidate
    slug = f"repair_{job_id}"
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        # run_canary() polls every poll_seconds (default 15s); without this,
        # a persistently-not-auto-executable tripwire would spam a fresh
        # pending candidate every cycle instead of leaving the existing one
        # for a human to act on.
        existing = conn.execute(
            "SELECT id FROM initiatives WHERE slug=? AND status='pending' LIMIT 1", (slug,)
        ).fetchone()
        if existing is None:
            emit_candidate(conn, slug, f"canary/tripwire:{job_id}:{route}")
    finally:
        conn.close()


def compute_tripwires(jobs: List[Job], ledger: Ledger,
                      now: dt.datetime | None = None) -> List[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    tripwires = []
    for job in jobs:
        cadence = job.expected_cadence_min
        if not cadence:
            continue
        last = ledger.last_run(job.id)
        if last is None:
            tripwires.append({"job_id": job.id, "last_seen": None,
                              "expected_min": cadence, "status": "tripwire"})
            continue
        last_dt = dt.datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        age_min = (now - last_dt).total_seconds() / 60.0
        if age_min > FACTOR * cadence:
            tripwires.append({"job_id": job.id, "last_seen": last["ts"],
                              "expected_min": cadence, "age_min": round(age_min, 1),
                              "status": "tripwire"})
    return tripwires
