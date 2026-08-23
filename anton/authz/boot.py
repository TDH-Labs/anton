"""Boot checks & migration runner (AUTHZ-SPEC §9, REQ-APPR-05b, REQ-PRIN-02)."""
from __future__ import annotations

import hashlib

from .principals import MigrationPrincipal, PrincipalTypeError, require_nonhuman
from .schema import missing_critical_triggers, schema_signature


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
    if mode != "first_boot":
        if baseline is not None and baseline != sig:
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
    every migration is hash-recorded in the audit chain; post-migration
    the critical trigger/constraint set is asserted (REQ-PRIN-02)."""
    require_nonhuman(principal)
    if not isinstance(principal, MigrationPrincipal):
        raise PrincipalTypeError(
            "migrations require a MigrationPrincipal")
    store.conn.executescript(sql)
    store.conn.commit()
    audit.append("migration", actor=principal, payload={
        "name": name, "sql_sha256": hashlib.sha256(sql.encode()).hexdigest()})
    missing = missing_critical_triggers(store.conn)
    if missing:
        raise MigrationIntegrityError(
            f"migration {name!r} dropped critical authZ triggers: {missing}")
    # Sanctioned migrations re-baseline the recorded schema hash.
    sig = schema_signature(store.conn)
    store.kv_set("schema_hash", sig)
    return sig
