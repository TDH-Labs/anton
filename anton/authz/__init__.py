"""Anton multi-user authorization spine (AUTHZ-SPEC v1.1, FROZEN).

Phase 1 build: identity/sessions/RBAC, dual-layer route + data guards,
credential broker, grants, approvals, break-glass, WORM audit chain.
Enforcement doctrine (ED-1): the data layer is canonical; route guards
are fail-closed redundancy. Fail-closed everywhere (ED-2).
"""
from __future__ import annotations

import os

from .audit import AuditLog  # noqa: F401
from .broker import BrokerClient, CredentialBroker  # noqa: F401
from .boot import boot_check, run_migration  # noqa: F401
from .guards import AuthzMiddleware, audit_routes_behavioral, lint_repo_file  # noqa: F401
from .store import open_store  # noqa: F401


def wire_authz(app, data_dir: str, config: dict) -> None:
    """Attaches the authZ spine to a dashboard app when
    config['authz']['enabled'] is set."""
    from .breakglass import generate_recovery_artifact
    from .grants import has_active_grant
    from .rbac import enabled_roles
    from .router import build_router
    from .secrets import write_private_file

    azcfg = (config.get("authz") or {})
    mode = azcfg.get("mode", "multi_user")
    # R9-MAJOR: authz-enabled without a decision secret silently falls back
    # to the legacy fail-open consumer. Refuse the configuration instead.
    if not (azcfg.get("decision_secret") or "").strip():
        raise RuntimeError(
            "authz.enabled requires authz.decision_secret in config.yaml — "
            "without it approved sign-offs cannot be authenticated and the "
            "money/outbound gate would be forgeable.")
    azdir = os.path.join(data_dir, "authz")
    os.makedirs(azdir, exist_ok=True)

    store = open_store(os.path.join(data_dir, "authz.db"))
    store.enabled_roles = enabled_roles(config)
    store.decision_secret = ((azcfg.get("decision_secret") or "").strip()) or None
    # R13-B1: surface the pre-heal drift refusal BEFORE anything heals the DB.
    if store.preheal_refusal:
        audit = AuditLog(store)
        try:
            audit.append("schema_mismatch", payload={
                "reason": "preheal_drift", "detail": store.preheal_refusal})
        except Exception:
            pass  # the drift may include the audit chain itself (R14-B2)
        raise RuntimeError("refusing multi-user start: "
                           + store.preheal_refusal)
    audit = AuditLog(store)

    broker = CredentialBroker(
        db_path=os.path.join(azdir, "broker.db"),
        keys_dir=os.path.join(azdir, "keys"),
        socket_path=os.path.join(azdir, "broker.sock"),
        audit=audit,
    )
    store.broker = broker  # revocation-rotation path for OAuth connectors
    # Session revocation reach-through: capability tokens die with their
    # issuing session OR machine-token credential within one validation pass
    # (REQ-AUTH-02/REQ-CRED-04/R9).
    broker.session_validator = store.credential_alive
    # Full socket flow: lease/mint requests present a live session token;
    # the broker resolves the principal itself (REQ-CRED-02 attestation).
    broker.principal_validator = store.resolve_any_token
    # Grant re-check at mint/fetch; Owner/Admin are the privileged tier.
    def _grant_allowed(principal_id: str, connection_id: str) -> bool:
        p = store.principal_by_id(principal_id)
        if p is not None:
            if p.role in ("Owner", "Admin"):
                return True
            if p.kind == "service":
                # R9: a service identity inherits its owning human's access —
                # the self-grant trigger correctly forbids granting directly
                # to it.
                owner = store.principal_by_id(p.human_id)
                if owner is None:
                    return False
                if owner.role in ("Owner", "Admin"):
                    return True
                return has_active_grant(store, owner.user_id, connection_id)
        return has_active_grant(store, principal_id, connection_id)
    broker.grant_checker = _grant_allowed

    # R13-B2: first_boot means a genuinely pristine DB — no recorded
    # baseline AND no audit history AND no genesis stamp. The stamp is a
    # file OUTSIDE the database (authz/genesis.stamp), written once after
    # the first baseline: an attacker who wipes tables/kv rows inside the
    # DB cannot erase it, so a wiped DB can never be re-blessed as genesis
    # (R15-B kv-drop launder).
    has_history = bool(store.conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='audit_chain'").fetchone()) and store.conn.execute(
        "SELECT COUNT(*) FROM audit_chain").fetchone()[0] > 0
    stamp = os.path.join(azdir, "genesis.stamp")
    stamp_exists = os.path.exists(stamp)
    pristine = (store.kv_get("schema_hash") is None and not has_history)
    if stamp_exists and store.kv_get("schema_hash") is None and not has_history:
        # R15-B: genesis stamp exists but the DB looks pristine -> wiped DB;
        # never re-bless as first boot.
        audit.append("schema_mismatch", payload={
            "reason": "genesis_stamp_present_db_wiped"})
        raise RuntimeError(
            "refusing multi-user start: genesis stamp exists but the authz "
            "DB has no baseline/history — the database was wiped or "
            "restored improperly.")
    boot_check(store, audit, mode="first_boot" if pristine else mode)
    if pristine:
        from .secrets import write_private_file
        write_private_file(stamp, "genesis")

    # The scheduler's real money/outbound gate lives in isolation.db; its
    # approvals triggers must survive too (R5-7). Fail closed on drift.
    import sqlite3 as _sq
    from ..db import isolation_approvals_integrity as _iso_check
    iso_path = os.path.join(data_dir, "isolation.db")
    if os.path.exists(iso_path):
        _iso = _sq.connect(iso_path)
        try:
            drift = _iso_check(_iso)
        finally:
            _iso.close()
        if drift:
            audit.append("schema_mismatch", payload={
                "scope": "isolation_db_approvals", "drift": drift})
            raise RuntimeError(
                "isolation.db approvals trigger set drifted (" +
                "".join(drift) + ") — refusing multi-user start")

    # First-run Owner claim: explicit, out-of-band, single-use (R1-F12).
    claim_path = os.path.join(azdir, "owner-claim")
    if store.count_users() == 0 and not os.path.exists(claim_path):
        import secrets as pysecrets
        write_private_file(claim_path, pysecrets.token_hex(16))

    codes = None
    if store.kv_get("recovery_codes") is None:
        codes = generate_recovery_artifact(store)
    app.state.authz_recovery_codes = codes or []

    from .guards import AuthzMiddleware as _MW  # local import clarity
    from .guards import DenyWebSockets as _WS
    app.add_middleware(_WS)          # raw-ASGI: closes all ws scopes
    app.add_middleware(_MW, store=store, audit=audit)
    app.include_router(build_router(store, audit, broker, azdir))

    app.state.authz_store = store
    app.state.authz_audit = audit
    app.state.authz_broker = broker
    app.state.authz_middleware_active = True

    broker.start()

    try:
        app.add_event_handler("shutdown", _shutdown(broker, store))
    except Exception:
        pass


def _shutdown(broker, store):
    def _hook():
        try:
            broker.stop()
            store.close()
        except Exception:
            pass
    return _hook
