"""Live in-flight state and operator steering for scheduled jobs.

Two concerns, one module, because both are per-job scheduler state that the
dashboard process reads and the scheduler process writes:

`running_jobs` answers "what is Anton doing right now". Before this existed,
`/api/agent/worklog`'s `ongoing` list reported jobs whose cron window was
merely *due*, with a permanently null progress field -- the Ops Center's
"Right Now" strip was showing the most recent *finished* run under a
present-tense heading.

`job_state` answers "do that later / do that now / skip that one". Anton had
no reprioritization mechanism at all: no priority column, no pause, no
run-now. For a cron-driven system those three verbs are what reprioritizing
actually means, and they beat a priority integer nobody would tune.

Both live in isolation.db rather than in the engine's memory because
`anton serve` (scheduler, port 8798) and `anton dashboard` (FastAPI, 8799)
are separate OS processes -- in-memory state in one is invisible to the
other. jobs.yaml stays the operator's own file; steering never rewrites it.
"""
from __future__ import annotations

import datetime as dt
import os
import socket
import sqlite3
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS running_jobs (
    job_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    host TEXT
);
CREATE TABLE IF NOT EXISTS job_state (
    job_id TEXT PRIMARY KEY,
    paused INTEGER NOT NULL DEFAULT 0,
    run_now INTEGER NOT NULL DEFAULT 0,
    skip_next INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT
);
"""

# A run still marked in-flight after this long is treated as abandoned: the
# container was killed mid-dispatch, so the clearing `finally` never ran. The
# window is deliberately well past `general.job_timeout_seconds` (default
# 300s) so a legitimately slow job is never reported as a phantom.
STALE_RUNNING_SECONDS = 3600


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(data_dir: str) -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.join(data_dir, "isolation.db"), timeout=10.0)
    conn.executescript(SCHEMA)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create both tables on an already-open connection (ops_schema hook)."""
    conn.executescript(SCHEMA)


# ---- in-flight state -------------------------------------------------

def mark_running(data_dir: str, job_id: str, host: Optional[str] = None) -> None:
    """Record that `job_id` has entered dispatch. Replaces any prior row for
    the same job: a second dispatch means the first is no longer in flight."""
    conn = _connect(data_dir)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO running_jobs(job_id, started_at, host) VALUES(?,?,?)",
            (job_id, _now_iso(), host or socket.gethostname()))
        conn.commit()
    finally:
        conn.close()


def clear_running(data_dir: str, job_id: str) -> None:
    """Drop `job_id`'s in-flight row. Safe when no row exists."""
    conn = _connect(data_dir)
    try:
        conn.execute("DELETE FROM running_jobs WHERE job_id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()


def list_running(data_dir: str, max_age_s: int = STALE_RUNNING_SECONDS) -> list[dict]:
    """Every job currently in flight, newest first, with stale rows excluded
    rather than deleted -- a reader must never mutate the writer's table."""
    conn = _connect(data_dir)
    try:
        rows = conn.execute(
            "SELECT job_id, started_at, host FROM running_jobs ORDER BY started_at DESC").fetchall()
    finally:
        conn.close()
    out = []
    for job_id, started_at, host in rows:
        age = _age_seconds(started_at)
        if age is not None and age > max_age_s:
            continue
        out.append({"job_id": job_id, "started_at": started_at, "host": host,
                    "age_seconds": age})
    return out


def clear_stale_running(data_dir: str, max_age_s: int = STALE_RUNNING_SECONDS) -> int:
    """Delete abandoned in-flight rows; returns how many were removed. Called
    once at scheduler boot, which is the only moment a row from a previous
    process can be known dead."""
    conn = _connect(data_dir)
    try:
        rows = conn.execute("SELECT job_id, started_at FROM running_jobs").fetchall()
        stale = [job_id for job_id, started_at in rows
                 if (_age_seconds(started_at) or 0) > max_age_s]
        for job_id in stale:
            conn.execute("DELETE FROM running_jobs WHERE job_id=?", (job_id,))
        conn.commit()
        return len(stale)
    finally:
        conn.close()


def _age_seconds(started_at: str) -> Optional[int]:
    try:
        started = dt.datetime.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=dt.timezone.utc)
    except (ValueError, TypeError):
        return None
    return int((dt.datetime.now(dt.timezone.utc) - started).total_seconds())


# ---- steering --------------------------------------------------------

def get_state(data_dir: str, job_id: str) -> dict:
    """This job's steering flags, defaulted for a job never steered."""
    conn = _connect(data_dir)
    try:
        row = conn.execute(
            "SELECT paused, run_now, skip_next FROM job_state WHERE job_id=?",
            (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return {"job_id": job_id, "paused": False, "run_now": False, "skip_next": False}
    return {"job_id": job_id, "paused": bool(row[0]),
            "run_now": bool(row[1]), "skip_next": bool(row[2])}


def all_states(data_dir: str) -> dict[str, dict]:
    """Every steered job, keyed by id. Jobs never steered are absent."""
    conn = _connect(data_dir)
    try:
        rows = conn.execute(
            "SELECT job_id, paused, run_now, skip_next FROM job_state").fetchall()
    finally:
        conn.close()
    return {r[0]: {"job_id": r[0], "paused": bool(r[1]),
                   "run_now": bool(r[2]), "skip_next": bool(r[3])} for r in rows}


def _set_flag(data_dir: str, job_id: str, column: str, value: bool) -> dict:
    # `column` is never caller-supplied: every call site passes one of the
    # three literals below, so the f-string cannot carry untrusted input.
    assert column in ("paused", "run_now", "skip_next"), column
    conn = _connect(data_dir)
    try:
        conn.execute(
            "INSERT INTO job_state(job_id, paused, run_now, skip_next, updated_at) "
            "VALUES(?,0,0,0,?) ON CONFLICT(job_id) DO NOTHING",
            (job_id, _now_iso()))
        conn.execute(
            f"UPDATE job_state SET {column}=?, updated_at=? WHERE job_id=?",
            (1 if value else 0, _now_iso(), job_id))
        conn.commit()
    finally:
        conn.close()
    return get_state(data_dir, job_id)


def set_paused(data_dir: str, job_id: str, paused: bool) -> dict:
    """Pause or resume a job. A paused job is skipped by `due_jobs` until
    resumed; it never interrupts a run already in flight."""
    return _set_flag(data_dir, job_id, "paused", paused)


def request_run_now(data_dir: str, job_id: str) -> dict:
    """Ask for one dispatch at the next poll tick regardless of the cron
    window. Consumed by `due_jobs`, so it fires exactly once."""
    return _set_flag(data_dir, job_id, "run_now", True)


def request_skip_next(data_dir: str, job_id: str) -> dict:
    """Skip the next scheduled window only. Consumed when that window
    arrives, so the job resumes its normal cadence afterwards."""
    return _set_flag(data_dir, job_id, "skip_next", True)


def consume_run_now(data_dir: str, job_id: str) -> None:
    """Clear a satisfied run-now request."""
    _set_flag(data_dir, job_id, "run_now", False)


def consume_skip_next(data_dir: str, job_id: str) -> None:
    """Clear a spent skip-next request."""
    _set_flag(data_dir, job_id, "skip_next", False)
