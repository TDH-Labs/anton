"""Boot checks & migration runner (AUTHZ-SPEC §9, REQ-APPR-05b, REQ-PRIN-02)."""
from __future__ import annotations

import hashlib
import sqlite3

from .principals import MigrationPrincipal, PrincipalTypeError, require_nonhuman
from .schema import (missing_critical_triggers, schema_signature,
                     weakened_critical_objects)


class SchemaHashMismatch(Exception):
    """The recorded trigger/constraint set no longer matches the database —
    hand-dropped triggers block multi-user boot (REQ-APPR-05b)."""


class MigrationIntegrityError(Exception):
    """A migration weakened the invariant set (REQ-PRIN-02)."""


def boot_check(store, audit, mode: str = "multi_user") -> str:
    """Record/verify the schema-hash in the audit chain at boot. A mismatch
    blocks boot into multi-user mode; single-operator mode records the same
    hash so later escalation to multi-user is still checked."""
    sig = schema_signature(store.conn)
    baseline = store.kv_get("schema_hash")
    if mode == "first_boot":
        # R14-B1: a genuinely fresh DB is canonical by construction
        # (ensure_schema ran in open_store before this check) — so even the
        # first_boot path must assert the canonical object set before
        # recording its baseline. A wiped-history tamper that weakened a
        # trigger cannot be blessed as 'first boot'.
        missing = missing_critical_triggers(store.conn)
        weakened = weakened_critical_objects(store.conn)
        if missing or weakened:
            audit.append("schema_mismatch", payload={
                "mode": mode, "missing": missing, "weakened": weakened})
            raise SchemaHashMismatch(
                f"'first boot' refused: DB is not pristine canonical "
                f"(missing={missing} weakened={weakened})")
    if mode == "first_boot":
        store.kv_set("schema_hash", sig)
        audit.append("boot", payload={"mode": mode, "schema_hash": sig})
        return sig
    if baseline is None:
        audit.append("schema_mismatch", payload={
            "expected": None, "actual": sig, "mode": mode,
            "reason": "baseline_missing"})
        raise SchemaHashMismatch(
            "authZ schema-hash baseline is MISSING — the DB was tampered "
            "or restored improperly. Refusing to start into multi-user.")
    if baseline != sig:
        audit.append("schema_mismatch", payload={
            "expected": baseline, "actual": sig, "mode": mode})
        raise SchemaHashMismatch(
            "authZ schema-hash mismatch — triggers/constraints were "
            "altered out-of-band. Refusing to start.")
    store.kv_set("schema_hash", sig)
    audit.append("boot", payload={"mode": mode, "schema_hash": sig})
    return sig


def _TXN_CONTROL_WORDS():
    return {"BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "END"}


def _leading_keyword(text: str) -> str | None:
    """First SQL keyword after stripping whitespace and comments — a
    leading '--' comment must not smuggle transaction-control past the
    guard (R20-1)."""
    import re as _re
    s = text
    while True:
        s = s.lstrip()
        if s.startswith("--"):
            nl = s.find("\n")
            if nl == -1:
                return None
            s = s[nl + 1:]
            continue
        if s.startswith("/*"):
            end = s.find("*/")
            if end == -1:
                return None
            s = s[end + 2:]
            continue
        break
    m = _re.match(r"([A-Za-z]+)", s)
    return m.group(1).upper() if m else None


def _for_each_statement(conn, text, fn):
    """Executes fn(conn, stmt) for every complete statement in `text`.

    Splits char-by-char using sqlite3.complete_statement so semicolons
    inside trigger bodies / quoted strings do not split prematurely, and
    multiple statements on one line are applied individually. Refuses
    transaction-control statements — they would break the single-
    transaction atomicity guarantee (R19-B).
    """
    import re as _re
    buf = ""
    for ch in text:
        buf += ch
        if ch == ";" and sqlite3.complete_statement(buf):
            kw = _leading_keyword(buf)
            if kw in _TXN_CONTROL_WORDS():
                raise MigrationIntegrityError(
                    f"transaction-control statement forbidden in "
                    f"migrations: {kw}")
            fn(conn, buf)
            buf = ""
    if buf.strip():
        kw = _leading_keyword(buf)
        if kw in _TXN_CONTROL_WORDS():
            raise MigrationIntegrityError(
                f"transaction-control statement forbidden in migrations: {kw}")
        fn(conn, buf)


def run_migration(store, audit, principal, name: str, sql: str) -> str:
    """Migration runner operates exclusively under MigrationPrincipal.

    One BEGIN IMMEDIATE transaction contains: the DDL, the WORM audit row,
    and the baseline refresh — all commit or roll back atomically. The
    invariant gate (name + body) runs on a scratch clone BEFORE the live DB
    is touched, and again post-apply inside the transaction. Scope note
    (R18-OBS): the gate covers schema OBJECTS; vetting row DATA written by
    a MigrationPrincipal is out of scope."""
    require_nonhuman(principal)
    if not isinstance(principal, MigrationPrincipal):
        raise PrincipalTypeError(
            "migrations require a MigrationPrincipal")
    with store.lock:
        _validate_migration_sql(store, sql, audit=audit, name=name,
                                principal=principal)
        conn = store.conn
        # R19-A: a quiescent connection is required. If a foreign writer has
        # an open transaction we refuse WITHOUT touching it — rolling
        # back here would destroy their uncommitted work.
        if conn.in_transaction:
            _audit_refusal(audit, principal, name, sql,
                           ["foreign_transaction_present"], [])
            raise MigrationIntegrityError(
                "migration requires a quiescent connection (a foreign "
                "transaction is open on this connection)")
        store.in_migration_txn = True  # defer kv_set/audit commits
        started = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            started = True
            _for_each_statement(
                conn, sql, lambda c, stmt: c.execute(stmt))
            missing = missing_critical_triggers(conn)
            weakened = weakened_critical_objects(conn)
            if missing or weakened:
                raise MigrationIntegrityError(
                    f"migration {name!r} violated the invariant set "
                    f"post-apply: missing={missing} weakened={weakened}")
            audit.append("migration", actor=principal, payload={
                "name": name,
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest()})
            sig = schema_signature(conn)
            kv_set_deferred(conn, "schema_hash", sig)
            conn.commit()
            store.in_migration_txn = False
            return sig
        except Exception:
            if started:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            store.in_migration_txn = False
            _audit_refusal(audit, principal, name, sql,
                           ["apply_or_gate_failure_rolled_back"], [])
            raise


def kv_set_deferred(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))


def _audit_refusal(audit, principal, name: str, sql: str, missing,
                   weakened) -> None:
    try:
        audit.append("migration_refused", payload={
            "name": name,
            "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "missing": missing, "weakened": weakened})
    except Exception:
        pass


def _validate_migration_sql(store, sql: str, audit=None, name: str = "",
                            principal=None) -> None:
    """Apply the migration to a scratch in-memory clone of the live schema
    and assert the invariant gate there. This is the authoritative refusal:
    the live DB is never written when the gate would fail. Refusals are
    written to the audit chain (R5-4)."""
    import sqlite3
    scratch = sqlite3.connect(":memory:")
    try:
        try:
            for (ddl,) in store.conn.execute(
                    "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"):
                if ddl.startswith("CREATE TABLE sqlite_"):
                    continue
                scratch.execute(ddl)
            scratch.commit()
            # same statement-splitting semantics as the live apply path so
            # validation matches execution exactly (R18-B)
            _for_each_statement(
                scratch, sql, lambda c, stmt: c.execute(stmt))
            missing = missing_critical_triggers(scratch)
            weakened = weakened_critical_objects(scratch)
        finally:
            scratch.close()
        if missing or weakened:
            _audit_refusal(audit, principal, name, sql, missing, weakened)
            raise MigrationIntegrityError(
                f"migration would violate the authZ invariant set: "
                f"missing={missing} weakened={weakened}")
    finally:
        scratch.close()
