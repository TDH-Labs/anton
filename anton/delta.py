"""Delta detection: derive candidate initiatives from state changes (vault + ledger)."""
from __future__ import annotations

import datetime as dt

from .ledger import Ledger
from .vault import emit_candidate


def scan_ledger_failures(ledger: Ledger, db_conn, since_hours: int = 24,
                         emit: bool = True) -> list[str]:
    """Failing tasks in the window -> candidate remediation initiatives (deduped)."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = {r[0] for r in db_conn.execute(
        "SELECT slug FROM initiatives WHERE status='pending'")}
    slugs = []
    for row in ledger.read():
        if row["ts"] < since or row["exit"] == 0:
            continue
        slug = f"remediate-{row['task']}"
        if slug in pending or slug in slugs:
            continue
        slugs.append(slug)
        if emit:
            emit_candidate(db_conn, slug, f"ledger:{row['task']}:exit{row['exit']}")
    return slugs


def scan_upskill_candidates(ledger: Ledger, db_conn, since_hours: int = 24,
                            min_repeats: int = 2, emit: bool = True) -> list[str]:
    """A task failing >=min_repeats times in the window is a different signal
    than scan_ledger_failures' single-failure remediation candidates: a
    repeated failure is a competence gap, not a one-off, and warrants
    upskill.py's full research-first pipeline rather than a simple re-run
    repair (canary.py's attempt_repairs handles the single-miss case).
    Emitted as upskill-<task> so the two candidate classes stay visually and
    structurally separable in the initiatives table."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=since_hours)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = {r[0] for r in db_conn.execute(
        "SELECT slug FROM initiatives WHERE status='pending'")}
    counts: dict[str, int] = {}
    for row in ledger.read():
        if row["ts"] < since or row["exit"] == 0:
            continue
        counts[row["task"]] = counts.get(row["task"], 0) + 1
    slugs = []
    for task, n in counts.items():
        if n < min_repeats:
            continue
        slug = f"upskill-{task}"
        if slug in pending:
            continue
        slugs.append(slug)
        if emit:
            emit_candidate(db_conn, slug, f"ledger:{task}:repeated_failures:{n}")
    return slugs
