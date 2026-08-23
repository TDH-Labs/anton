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
-- (R4-3 hardening) Decided rows reach that state only through the guarded
-- UPDATE. Refused transitions:
--   * any UPDATE mutating the immutable initiator fields;
--   * decided status with initiator present but no approver (laundering);
--   * decided status with same human as initiator;
--   * decided status with a claimed approver but NO initiator (a system
--     row stamps initiator 'system'; an unattributed row cannot be decided
--     by a human).
-- Fully-legacy rows (both initiator and approver NULL — pre-authz) are
-- allowed through, because there is no identity material to compare.
CREATE TRIGGER IF NOT EXISTS trg_approvals_no_self_approve
BEFORE INSERT ON approvals
FOR EACH ROW
WHEN NEW.status IN ('approved', 'denied')
BEGIN
    SELECT RAISE(ABORT, 'approvals must be created pending');
END;

CREATE TRIGGER IF NOT EXISTS trg_approvals_no_self_approve_upd
BEFORE UPDATE ON approvals
FOR EACH ROW
WHEN (
    NEW.initiator_human IS NOT OLD.initiator_human
    OR NEW.initiator_principal IS NOT OLD.initiator_principal
    OR (NEW.status IN ('approved', 'denied') AND (
        (OLD.initiator_human IS NOT NULL AND NEW.approver_human IS NULL)
        OR (OLD.initiator_human IS NOT NULL
            AND NEW.approver_human IS NOT NULL
            AND NEW.approver_human = OLD.initiator_human)
        OR (OLD.initiator_human IS NULL AND NEW.approver_human IS NOT NULL)
    ))
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
