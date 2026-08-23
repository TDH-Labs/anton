"""authz.db schema: tables + invariant triggers (AUTHZ-SPEC §4/§5/§9).

The self-grant, escalation-chain, sole-admin and approver≠initiator
invariants live IN THE DATABASE as triggers — scripts and migrations
cannot bypass them (REQ-GRNT-02, REQ-APPR-01, REQ-GRNT-03). The full
trigger/constraint set is hash-recorded at boot (REQ-APPR-05b); a
hand-dropped trigger blocks multi-user boot (CI-T-APPR-05).
"""
from __future__ import annotations

import hashlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL DEFAULT 'user',
    human_id TEXT NOT NULL,
    password_hash TEXT,
    created TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS role_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL, role TEXT NOT NULL,
    actor_id TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
    label TEXT, first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions_authz (
    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL, device_id TEXT,
    created TEXT NOT NULL, expires REAL NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS machine_tokens (
    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
    service_user_id TEXT NOT NULL,
    created TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, ok INTEGER NOT NULL, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS authz_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, detail TEXT, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS connection_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    granter_id TEXT NOT NULL, grantee_id TEXT NOT NULL,
    connection_id TEXT NOT NULL, scope TEXT NOT NULL,
    oauth_scopes_json TEXT NOT NULL DEFAULT '[]',
    policy_version TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS connection_scopes (
    connection_id TEXT PRIMARY KEY,
    oauth_scopes_json TEXT NOT NULL DEFAULT '[]',
    policy_version TEXT NOT NULL DEFAULT 'v1',
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS used_scopes (
    connection_id TEXT PRIMARY KEY, scopes_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS authz_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    initiator_principal TEXT NOT NULL, initiator_human TEXT NOT NULL,
    approver_human TEXT,
    payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL,
    policy_version TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approval_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id INTEGER NOT NULL,
    approver_principal TEXT NOT NULL, approver_human TEXT NOT NULL,
    decision TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approval_executions (
    approval_id INTEGER PRIMARY KEY,
    executed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS breakglass_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    principal TEXT NOT NULL, reason TEXT,
    expires REAL NOT NULL, ts TEXT NOT NULL,
    channels_ok INTEGER NOT NULL DEFAULT 0,
    channels_failed INTEGER NOT NULL DEFAULT 0,
    recovery INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL, payload_json TEXT NOT NULL,
    ready_at REAL NOT NULL, applied INTEGER NOT NULL DEFAULT 0,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS egress_channels (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    address TEXT NOT NULL,
    recipient_name TEXT DEFAULT '',
    clearance TEXT NOT NULL DEFAULT 'INTERNAL',
    opt_in INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS egress_optins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL, actor_id TEXT NOT NULL, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS audit_chain (
    seq INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    sponsor_user TEXT NOT NULL DEFAULT '',
    workspace TEXT NOT NULL DEFAULT 'default',
    agent_instance TEXT NOT NULL DEFAULT '',
    tool_credential TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
"""

TRIGGERS = """
-- REQ-GRNT-02: no self-grants, enforced in schema, not API layer. The
-- check collapses service identities to their owning human, so U granting
-- U's own service account is still a self-grant.
CREATE TRIGGER IF NOT EXISTS trg_grant_no_self
BEFORE INSERT ON connection_grants
FOR EACH ROW
WHEN (SELECT human_id FROM users WHERE id = NEW.granter_id) =
     (SELECT human_id FROM users WHERE id = NEW.grantee_id)
BEGIN
    SELECT RAISE(ABORT, 'self-grant forbidden (human match)');
END;

CREATE TRIGGER IF NOT EXISTS trg_grant_no_cycle
BEFORE INSERT ON connection_grants
FOR EACH ROW
WHEN EXISTS (
    WITH RECURSIVE down(id) AS (
        SELECT NEW.grantee_id
        UNION
        SELECT g.grantee_id FROM connection_grants g
            JOIN down ON g.granter_id = down.id
        WHERE g.active = 1
    )
    SELECT 1 FROM down WHERE down.id = NEW.granter_id
)
BEGIN
    SELECT RAISE(ABORT, 'mutual escalation chain forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trg_grant_no_reparty
BEFORE UPDATE ON connection_grants
FOR EACH ROW
WHEN NEW.granter_id != OLD.granter_id OR NEW.grantee_id != OLD.grantee_id
BEGIN
    SELECT RAISE(ABORT, 'grant parties are immutable');
END;

-- Reactivating a REVOKED grant re-runs the escalation-chain check —
-- resurrection via direct SQL cannot bypass it.
CREATE TRIGGER IF NOT EXISTS trg_grant_no_cycle_reactivate
BEFORE UPDATE ON connection_grants
FOR EACH ROW
WHEN OLD.active = 0 AND NEW.active = 1 AND EXISTS (
    WITH RECURSIVE down(id) AS (
        SELECT NEW.grantee_id
        UNION
        SELECT g.grantee_id FROM connection_grants g
            JOIN down ON g.granter_id = down.id
        WHERE g.active = 1
    )
    SELECT 1 FROM down WHERE down.id = NEW.granter_id
)
BEGIN
    SELECT RAISE(ABORT, 'reactivation would create an escalation chain');
END;

-- REQ-GRNT-03: sole-admin self-elevation requires an active break-glass
-- elevation; otherwise the schema itself aborts the write.
CREATE TRIGGER IF NOT EXISTS trg_role_no_self_modify
BEFORE INSERT ON role_assignments
FOR EACH ROW
WHEN NEW.actor_id = NEW.user_id
    AND NOT EXISTS (
        SELECT 1 FROM breakglass_events
        WHERE principal = NEW.actor_id
          AND expires > strftime('%s', 'now'))
BEGIN
    SELECT RAISE(ABORT, 'self role modification requires break-glass elevation');
END;

-- REQ-APPR-01: approvals are append-only; decisions live in a separate
-- table; the approval row itself is immutable.
CREATE TRIGGER IF NOT EXISTS trg_approval_append_only
BEFORE UPDATE ON authz_approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_approval_no_delete
BEFORE DELETE ON authz_approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals are append-only');
END;

-- REQ-APPR-01/02: approver human may never equal initiator human (service
-- identities collapse to their owning human, closing secondary-identity
-- approval paths).
CREATE TRIGGER IF NOT EXISTS trg_approval_no_self_approve
BEFORE INSERT ON approval_decisions
FOR EACH ROW
WHEN NEW.approver_human = (
    SELECT initiator_human FROM authz_approvals WHERE id = NEW.approval_id)
BEGIN
    SELECT RAISE(ABORT, 'approver may not equal initiator (human match)');
END;

CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_once
ON approval_decisions(approval_id);

-- REQ-AUDIT-01: the audit chain is append-only at the schema level.
CREATE TRIGGER IF NOT EXISTS trg_audit_append_only
BEFORE UPDATE ON audit_chain
BEGIN
    SELECT RAISE(ABORT, 'audit chain is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON audit_chain
BEGIN
    SELECT RAISE(ABORT, 'audit chain is append-only');
END;
"""

# The trigger set whose presence is asserted after every migration and at
# every multi-user boot (REQ-PRIN-02, REQ-APPR-05b).
CRITICAL_TRIGGERS = (
    "trg_grant_no_self",
    "trg_grant_no_cycle",
    "trg_role_no_self_modify",
    "trg_approval_append_only",
    "trg_approval_no_self_approve",
    "trg_audit_append_only",
    "trg_audit_no_delete",
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(TRIGGERS)
    conn.commit()


def schema_signature(conn: sqlite3.Connection) -> str:
    """sha256 over every trigger/table definition — the boot-recorded
    schema-hash (REQ-APPR-05b)."""
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name").fetchall()
    h = hashlib.sha256()
    for rtype, name, sql in rows:
        h.update(f"{rtype}|{name}|{sql}\n".encode("utf-8"))
    return h.hexdigest()


def missing_critical_triggers(conn: sqlite3.Connection) -> list[str]:
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()}
    return [t for t in CRITICAL_TRIGGERS if t not in names]
