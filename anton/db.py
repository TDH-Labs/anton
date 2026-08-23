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

-- Pending-only INSERT: decided rows can never be created directly, the
-- approver identity can NEVER be preset at creation (a sign-off is only
-- lawful when written by the guarded decision UPDATE), hmac is reserved for
-- the decision path (the sole exception being the son-of-anton bypass
-- marker on a direct-consumed row), and raw 'consumed' INSERTs without
-- that marker are execution-marker forgery (R9-MINOR).
CREATE TRIGGER IF NOT EXISTS trg_approvals_pending_only_insert
BEFORE INSERT ON approvals
FOR EACH ROW
WHEN NEW.status IN ('approved', 'denied')
  OR NEW.approver_human IS NOT NULL
  OR NEW.approver_principal IS NOT NULL
  OR (NEW.hmac IS NOT NULL AND NEW.hmac != 'son_of_anton_bypass')
  OR (NEW.status = 'consumed' AND NEW.hmac != 'son_of_anton_bypass')
BEGIN
    SELECT RAISE(ABORT,
        'approvals must be created pending with no approver/hmac');
END;

-- Approvals are historical records: deletion (evidence destruction) is
-- never legitimate — the scheduler consumes, it never deletes (R9-1).
CREATE TRIGGER IF NOT EXISTS trg_approvals_no_delete
BEFORE DELETE ON approvals
BEGIN
    SELECT RAISE(ABORT, 'approvals are historical records; deletion refused');
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
      OR NEW.initiator_principal IS NOT OLD.initiator_principal
      OR NEW.id IS NOT OLD.id
      -- decision-significant payload fields are immutable after INSERT:
      -- an approved sign-off is for the action/amount/recipient it named
      -- (R7-2)
      OR NEW.action IS NOT OLD.action
      OR NEW.amount IS NOT OLD.amount
      OR NEW.recipient IS NOT OLD.recipient
      -- evidence/timeline fields are immutable too (R9-MINOR)
      OR NEW.nonce IS NOT OLD.nonce
      OR NEW.ts IS NOT OLD.ts
      OR NEW.org_id IS NOT OLD.org_id)
     AND NOT (OLD.status = 'pending' AND NEW.status = 'pending'
              AND OLD.initiator_human IS NULL
              AND OLD.initiator_principal IS NULL
              AND NEW.approver_human IS NULL
              AND NEW.approver_principal IS NULL
              AND NEW.initiator_human = 'system:legacy'
              AND NEW.initiator_principal = 'system:legacy'))
    -- the decision hmac may only be written by the guarded decided
    -- transition; it is immutable afterwards (R9-MINOR)
    OR (OLD.status = 'pending' AND NEW.hmac IS NOT OLD.hmac
        AND NEW.status NOT IN ('approved', 'denied'))
    OR (OLD.status != 'pending' AND NEW.hmac IS NOT OLD.hmac)

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

    -- pending CANNOT be skipped to consumed (audit/execution-marker
    -- spoofing), and an approved row cannot be walked back or denied after
    -- sign-off (approver laundering / dated-sign-off reopen) — R6-3/R7-3
    OR (NEW.status = 'consumed' AND OLD.status NOT IN ('approved', 'consumed'))
    OR (OLD.status = 'approved' AND NEW.status NOT IN ('approved', 'consumed'))
)
BEGIN
    SELECT RAISE(ABORT, 'approval transition rejected (REQ-APPR-01/02)');
END;
"""


def init_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    _upgrade_approvals_columns(conn)
    # Superseded trigger names from earlier rounds must never survive:
    # a same-name IF NOT EXISTS create would silently keep the OLD weak body
    # (R5-2/R6-1). Drop them explicitly, then install the canonical set.
    conn.execute("DROP TRIGGER IF EXISTS trg_approvals_no_self_approve")
    conn.execute("DROP TRIGGER IF EXISTS trg_approvals_no_self_approve_upd")
    # Same-name BODY evolution: the canonical triggers themselves change
    # between rounds (R7-4). An IF NOT EXISTS is not convergence — drop and
    # recreate ANY approvals trigger whose body differs from canonical,
    # so re-running init_db always restores the canonical gate.
    _converge_approvals_triggers(conn)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _converge_approvals_triggers(conn: sqlite3.Connection) -> None:
    """Drop stale-body approvals triggers under canonical names so a re-run
    of init_db restores the exact canonical gate (same-name body evolution)."""
    scratch = sqlite3.connect(":memory:")
    try:
        scratch.executescript(SCHEMA)
        canon = {r[0]: (r[1] or "") for r in scratch.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE name IS NOT NULL AND name LIKE 'trg_approvals_%'")}
    finally:
        scratch.close()
    for (name, sql) in conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='trigger' AND name IS NOT NULL AND name LIKE "
            "'trg_approvals_%'"):
        if canon.get(name) != (sql or ""):
            conn.execute(f"DROP TRIGGER IF EXISTS \"{name.replace(chr(34), chr(34)+chr(34))}\"")
    conn.commit()


def _upgrade_approvals_columns(conn: sqlite3.Connection) -> None:
    """Idempotent ADD COLUMN for the identity fields introduced in R3 so
    pre-R3 isolation.db files upgrade cleanly (R6-2)."""
    tbl = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='approvals'"
    ).fetchone()
    if tbl is None:
        return  # fresh DB: SCHEMA creates it with the columns already
    cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
    for name in ("initiator_human", "initiator_principal",
                 "approver_human", "approver_principal"):
        if name not in cols:
            conn.execute(f"ALTER TABLE approvals ADD COLUMN {name} TEXT")
    conn.commit()


# The legacy approvals trigger set is the scheduler's real money/outbound
# gate; a dropped or body-weakened trigger there is silently invisible to
# the authz-store boot gate (R5-2/R5-7). Assertion mirrors the authz
# name+body check against THIS module's canonical SCHEMA.
CRITICAL_ISOLATION_TRIGGERS = (
    "trg_approvals_pending_only_insert",
    "trg_approvals_transition_guard",
    "trg_approvals_no_delete",
)


def adopt_legacy_approval(conn: sqlite3.Connection, nonce: str, audit=None):
    """Single-shot adoption of a pre-authz all-NULL approval row. Only a
    row that is pending with all identity NULL may be stamped with the
    system:legacy initiator; after that it is immutable and decisions flow
    through the guarded path. The audit entry is written BEFORE the stamp
    commits (different DBs, so not one transaction): a crash in between
    leaves an audit row without a stamp (over-audited, safe direction),
    never a durable stamp with no record (R7-5)."""
    if audit is not None:
        try:
            audit.append("legacy_approval_adopted",
                         payload={"nonce": nonce})
        except Exception:
            pass
    cur = conn.execute(
        "UPDATE approvals SET initiator_human='system:legacy', "
        "initiator_principal='system:legacy' "
        "WHERE nonce=? AND status='pending' AND initiator_human IS NULL "
        "AND initiator_principal IS NULL AND approver_human IS NULL "
        "AND approver_principal IS NULL", (nonce,))
    conn.commit()
    if cur.rowcount == 0:
        raise LookupError(f"no pending all-NULL approval with nonce {nonce}")
    return True


def consume_verified_approval(conn: sqlite3.Connection, action: str,
                              secret: str | None = None):
    """THE verified consumer for the money/outbound/skill-promotion gates:
    trigger-integrity drift check + optional decision-hmac verification +
    one-shot consume, atomically orderable inside a caller's BEGIN
    IMMEDIATE (R9-BLOCKER: upskill consumed forgeries because R8-1 lived
    only in the scheduler). Returns (ok, reason)."""
    import hashlib as _hashlib
    import hmac as _hmac
    drift = isolation_approvals_integrity(conn)
    if drift:
        return False, "gate_triggers_drifted"
    if secret:
        # R10-4: iterate candidates newest-first and consume the FIRST one
        # whose keyed hmac verifies — a single planted NULL-hmac junk row
        # cannot park legit approvals behind unverified_hmac forever.
        rows = conn.execute(
            "SELECT id, hmac, nonce FROM approvals WHERE action=? AND "
            "status='approved' ORDER BY id DESC", (action,)).fetchall()
        verified = None
        for row in rows:
            if not row[1]:
                continue
            expected = _hmac.new(secret.encode(), str(row[0]).encode(),
                                 _hashlib.sha256).hexdigest()
            if _hmac.compare_digest(row[1], expected):
                verified = row
                break
        if verified is None:
            return False, ("no_approval" if not rows else "unverified_hmac")
        aid = verified[0]
    else:
        row = conn.execute(
            "SELECT id FROM approvals WHERE action=? AND status='approved' "
            "ORDER BY id DESC LIMIT 1", (action,)).fetchone()
        if row is None:
            return False, "no_approval"
        aid = row[0]
    cur = conn.execute(
        "UPDATE approvals SET status='consumed' WHERE id=? "
        "AND status='approved'", (aid,))
    conn.commit()
    return (cur.rowcount > 0), "nonce_consumed"


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
        "WHERE type='trigger' AND name IS NOT NULL")}
    out = []
    for name in CRITICAL_ISOLATION_TRIGGERS:
        if name not in live:
            out.append(f"{name}:missing")
        elif live[name] != canon.get(name):
            out.append(f"{name}:weakened")
    # Any approvals TRIGGER beyond the canonical set is drift — including a
    # superseded same-name body that survived IF NOT EXISTS (R6-1). Tables/views
    # merely prefixed trg_approvals_ are not trigger drift (R8-4).
    for name in live:
        if name.startswith("trg_approvals_") and \
                name not in CRITICAL_ISOLATION_TRIGGERS:
            out.append(f"{name}:unexpected")
    return out
