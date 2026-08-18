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
