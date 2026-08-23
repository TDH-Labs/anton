"""isolation.db — agent-harness state. Tenant-ready: org_id on every table (Q4)."""
from __future__ import annotations

import sqlite3
import os

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default', room TEXT, started TEXT, state_ref TEXT
);
CREATE TABLE IF NOT EXISTS initiatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    slug TEXT, source TEXT, risk TEXT, score REAL, status TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    nonce TEXT UNIQUE, action TEXT, amount TEXT, recipient TEXT, status TEXT, hmac TEXT, ts TEXT,
    -- REQ-APPR-01/02: approver != initiator on the scheduler's real money/
    -- outbound gate. Additive; backfilled NULL until authz rewrites.
    initiator_human TEXT, initiator_principal TEXT,
    approver_human TEXT, approver_principal TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    scope TEXT, kind TEXT, cap REAL, used REAL DEFAULT 0, period_start TEXT
);
CREATE TABLE IF NOT EXISTS metering (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    ts TEXT, provider TEXT, model TEXT, tokens_in INTEGER, tokens_out INTEGER,
    cost_usd REAL, job_id TEXT
);
CREATE TABLE IF NOT EXISTS seen_external_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    source TEXT, item_hash TEXT, ts TEXT, UNIQUE(source, item_hash)
);
CREATE TABLE IF NOT EXISTS skill_dependencies (
    skill_slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    prerequisite_skill TEXT, target_capability TEXT, mastery_score REAL, last_validated TEXT
);
CREATE TABLE IF NOT EXISTS confidence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    prediction REAL, outcome REAL, ts TEXT
);
CREATE TABLE IF NOT EXISTS sandbox_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    slug TEXT, stage TEXT, ok INTEGER, detail TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS playbooks (
    slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    method TEXT, source_initiative TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS upskill_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    slug TEXT, subject TEXT, stage TEXT, attempt INTEGER, ok INTEGER, detail TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS skill_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    skill_slug TEXT, kind TEXT, text TEXT, source TEXT, consumed_at TEXT, ts TEXT
);

-- REQ-APPR-01/02 on the scheduler's real money/outbound gate: a decision
-- row may never be approved by the same human who initiated it. Initiated
-- rows carry initiator_human at creation (dashboard/API stamps it); the
-- deciding call stamps approver_human. Scripts and migrations cannot
-- bypass this — it lives in the database.
--
-- Fresh-name triggers (not IF NOT EXISTS) so this gate installs on every
-- DB including ones created by earlier rounds that shipped weaker triggers
-- under the trg_approvals_no_self_approve name (R5-2).

-- Pending-only INSERT: decided rows can never be created directly.
CREATE TRIGGER IF NOT EXISTS trg_approvals_pending_only_insert
BEFORE INSERT ON approvals
FOR EACH ROW
WHEN NEW.status IN ('approved', 'denied')
BEGIN
    SELECT RAISE(ABORT, 'approvals must be created pending');
END;

-- Decided transitions require a distinct human approver; initiator fields
-- are immutable; a consumed/denied approval is terminal (no re-run of the
-- scheduler money/outbound gate from a dated sign-off — R5-5). Pre-authz
-- rows (all NULL identity) must be ADOPTED via system:legacy before any
-- decision: the all-NULL direct forge is closed (R5-1).
CREATE TRIGGER IF NOT EXISTS trg_approvals_transition_guard
BEFORE UPDATE ON approvals
FOR EACH ROW
WHEN (
    -- initiator is immutable EXCEPT for the single-shot legacy adoption:
    -- a pending all-NULL row may be stamped with the system:legacy
    -- initiator in place of a NULL.
    ((NEW.initiator_human IS NOT OLD.initiator_human
      OR NEW.initiator_principal IS NOT OLD.initiator_principal)
     AND NOT (OLD.status = 'pending' AND NEW.status = 'pending'
              AND OLD.initiator_human IS NULL
              AND OLD.initiator_principal IS NULL
              AND NEW.approver_human IS NULL
              AND NEW.approver_principal IS NULL
              AND NEW.initiator_human = 'system:legacy'
              AND NEW.initiator_principal = 'system:legacy'))

    -- adoption is ONLY valid from an all-NULL pending row: any other
    -- initiator write is covered above; a second adoption write is refused
    OR (OLD.initiator_human = 'system:legacy'
        AND NEW.initiator_human != 'system:legacy')

    -- decided transitions demand approver != initiator, both present
    OR (NEW.status IN ('approved', 'denied')
        AND (OLD.initiator_human IS NULL
             OR NEW.initiator_human IS NULL
             OR NEW.approver_human IS NULL
             OR NEW.approver_human = OLD.initiator_human))

    -- terminal states are terminal: consumed/denied cannot be re-decided
    OR (OLD.status IN ('consumed', 'denied') AND NEW.status != OLD.status)
)
BEGIN
    SELECT RAISE(ABORT, 'approval transition rejected (REQ-APPR-01/02)');
END;
"""


def init_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# The legacy approvals trigger set is the scheduler's real money/outbound
# gate; a dropped or body-weakened trigger there is silently invisible to
# the authz-store boot gate (R5-2/R5-7). Assertion mirrors the authz
# name+body check against THIS module's canonical SCHEMA.
CRITICAL_ISOLATION_TRIGGERS = (
    "trg_approvals_pending_only_insert",
    "trg_approvals_transition_guard",
)


def isolation_approvals_integrity(conn: sqlite3.Connection) -> list[str]:
    canon: dict[str, str] = {}
    scratch = sqlite3.connect(":memory:")
    try:
        scratch.executescript(SCHEMA)
        for (name, sql) in scratch.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE name IS NOT NULL AND name LIKE 'trg_approvals_%'"):
            canon[name] = sql or ""
    finally:
        scratch.close()
    live = {r[0]: (r[1] or "") for r in conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE name IS NOT NULL")}
    out = []
    for name in CRITICAL_ISOLATION_TRIGGERS:
        if name not in live:
            out.append(f"{name}:missing")
        elif live[name] != canon.get(name):
            out.append(f"{name}:weakened")
    return out
