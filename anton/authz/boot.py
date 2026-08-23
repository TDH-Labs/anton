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


def run_migration(store, audit, principal, name: str, sql: str) -> str:
    """Migration runner operates exclusively under MigrationPrincipal;
    every migration is hash-recorded in the audit chain INSIDE the same
    transaction as the DDL; post-migration the critical trigger/constraint
    set is asserted by NAME and by BODY (REQ-PRIN-02, R3A-3, R16-B)."""
    require_nonhuman(principal)
    if not isinstance(principal, MigrationPrincipal):
        raise PrincipalTypeError(
            "migrations require a MigrationPrincipal")
    # VALIDATE FIRST on a scratch clone — a rejected migration never
    # touches the live DB.
    _validate_migration_sql(store, sql, audit=audit, name=name)
    with store.lock:
        store.in_migration_txn = True  # defer kv_set/audit commits
        conn = store.conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            # R16-A: executescript() silently commits; execute statements
            # individually (complete_statement handles trigger bodies).
            buf = ""
            for line in sql.splitlines(keepends=True):
                buf += line
                if sqlite3.complete_statement(buf):
                    conn.execute(buf)
                    buf = ""
            if buf.strip():
                conn.execute(buf)
            missing = missing_critical_triggers(conn)
            weakened = weakened_critical_objects(conn)
            if missing or weakened:
                raise MigrationIntegrityError(
                    f"migration {name!r} violated the invariant set "
                    f"post-apply: missing={missing} weakened={weakened}")
            # WORM record + baseline refresh commit atomically WITH the DDL.
            audit.append("migration", actor=principal, payload={
                "name": name,
                "sql_sha256": hashlib.sha256(sql.encode()).hexdigest()})
            sig = schema_signature(conn)
            kv_set_deferred(conn, "schema_hash", sig)
            conn.commit()
            store.in_migration_txn = False
            return sig
        except Exception:
            store.in_migration_txn = False
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            _audit_refusal(audit, name, sql,
                           ["rolled_back"], [])
            raise


def kv_set_deferred(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv(key, value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))


def _audit_refusal(audit, name: str, sql: str, missing, weakened) -> None:
    try:
        audit.append("migration_refused", payload={
            "name": name,
            "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
            "missing": missing, "weakened": weakened})
    except Exception:
        pass


def _validate_migration_sql(store, sql: str, audit=None, name: str = "") -> None:
    """Apply the migration to a scratch in-memory clone of the live schema
    and assert the invariant gate there. This is the authoritative refusal:
    the live DB is never written when the gate would fail. Refusals are
    written to the audit chain (R5-4)."""
    import sqlite3
    scratch = sqlite3.connect(":memory:")
    try:
        for (ddl,) in store.conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"):
            if ddl.startswith("CREATE TABLE sqlite_"):
                continue
            scratch.execute(ddl)
        scratch.commit()
        scratch.executescript(sql)
        scratch.commit()
        missing = missing_critical_triggers(scratch)
        weakened = weakened_critical_objects(scratch)
    finally:
        scratch.close()
    if missing or weakened:
        _audit_refusal(audit, name, sql, missing, weakened)
        raise MigrationIntegrityError(
            f"migration would violate the authZ invariant set: "
            f"missing={missing} weakened={weakened}")
