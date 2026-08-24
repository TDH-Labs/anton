"""AuthZ HTTP surface: bootstrap, login, sessions, probes (§1)."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import rbac


class BootstrapReq(BaseModel):
    username: str
    password: str
    claim: str


class EgressChannelReq(BaseModel):
    channel_id: str
    kind: str
    address: str
    clearance: str = "INTERNAL"
    recipient_name: str = ""


class EgressOptInReq(BaseModel):
    channel_id: str


class EgressSendReq(BaseModel):
    channel_id: str
    tag: str
    body: str


class LegacyAdoptionReq(BaseModel):
    nonce: str


class PortalReq(BaseModel):
    name: str
    base_url: str
    login_url: str = ""
    selectors: dict = {}
    cookie_domains: list[str] = []
    guardian_interval_s: int = 3600
    operations_file: str | None = None


class LoginReq(BaseModel):
    username: str
    password: str


def build_router(store, audit, broker, azdir: str) -> APIRouter:
    router = APIRouter()

    # -- first-run Owner claim (R1-F12 / REQ-AUTH-01) ---------------------
    @router.post("/api/auth/bootstrap")
    def bootstrap(req: BootstrapReq, request: Request):
        claim_path = os.path.join(azdir, "owner-claim")
        if not os.path.exists(claim_path):
            raise HTTPException(409, "Owner already claimed or claim expired")
        with open(claim_path, encoding="utf-8") as f:
            expected = f.read().strip()
        if req.claim != expected:
            raise HTTPException(403, "invalid owner claim code")
        if len(req.password) < 8:
            raise HTTPException(400, "password too short")
        user = store.create_user(req.username, req.password)
        store.assign_role(user["id"], rbac.SINGLE_OPERATOR_ROLE
                          if store.enabled_roles == [rbac.SINGLE_OPERATOR_ROLE]
                          else "Owner", actor_id="__bootstrap__")
        os.unlink(claim_path)  # single use — never a predictable default
        codes = _ensure_recovery_codes(store)
        request.app.state.authz_recovery_codes = codes
        # A human Owner now exists: provision (or re-check) the apiproxy's
        # scoped machine credential so the Ops Center proxy has its own
        # authz identity without waiting for the next restart.
        from .provision import ensure_apiproxy_credential
        ensure_apiproxy_credential(store, azdir, audit=audit)
        audit.append("owner_bootstrap", payload={"username": req.username})
        return {"status": "claimed", "username": req.username,
                "recovery_codes": codes}

    # -- sessions ----------------------------------------------------------
    @router.post("/api/auth/login")
    def login(req: LoginReq, request: Request):
        if store.is_locked(req.username):
            raise HTTPException(429, "account locked; try again later")
        user = store.verify_login(req.username, req.password)
        if user is None:
            store.record_login_attempt(req.username, ok=False)
            # REQ-AUDIT-01 lists logins in the chain; failed logins are
            # attributed by username (no principal exists yet).
            audit.append("login_failed", actor=req.username)
            raise HTTPException(401, "invalid credentials")
        store.record_login_attempt(req.username, ok=True)
        audit.append("login", actor=store.principal_by_id(user["id"]),
                     payload={"method": "password"})
        device = store.create_device(
            user["id"],
            request.headers.get("user-agent", "unknown")[:120])
        token = store.create_session(user["id"], device)
        return {"token": token}

    @router.get("/api/auth/sessions")
    def list_sessions(request: Request):
        principal = _principal(request)
        rows = store.list_sessions(principal.user_id)
        for r in rows:
            r.pop("device_id", None)
        return {"sessions": rows}

    @router.delete("/api/auth/sessions/{sid}")
    def revoke_session(sid: str, request: Request):
        principal = _principal(request)
        owned = any(s["id"] == sid
                    for s in store.list_sessions(principal.user_id))
        if not owned:
            raise HTTPException(404, "no such session for this user")
        store.revoke_session(sid, actor_id=principal.user_id)
        return {"revoked": sid}

    @router.post("/api/auth/logout")
    def logout(request: Request):
        principal = _principal(request)
        if principal.session_id:
            store.revoke_session(principal.session_id,
                                 actor_id=principal.user_id)
        return {"status": "logged_out"}

    # -- admin ---------------------------------------------------------------
    @router.get("/api/authz/users")
    def users(request: Request):
        _principal(request)  # capability enforced by middleware map
        rows = store.conn.execute(
            "SELECT id, username, kind FROM users ORDER BY username").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["role"] = store.role_of(r["id"])
            out.append(d)
        return {"users": out}

    # -- capability probe (matrix-test target) ---------------------------------
    @router.get("/api/authz/probe/{capability}")
    def probe(capability: str, request: Request):
        principal = _principal(request)
        if capability not in rbac.CAPABILITIES:
            raise HTTPException(404, "unknown capability")
        if not rbac.can(principal.role, capability):
            raise HTTPException(403,
                                f"role {principal.role!r} lacks {capability}")
        return {"ok": True, "capability": capability, "role": principal.role}

    # -- egress channels (handoff #11 HTTP surface) -------------------------
    @router.post("/api/authz/egress/channels")
    def create_egress_channel(req: EgressChannelReq, request: Request):
        principal = _principal(request)
        from .egress import create_channel
        try:
            create_channel(store, audit, actor=principal,
                           channel_id=req.channel_id, kind=req.kind,
                           address=req.address, clearance=req.clearance,
                           recipient_name=req.recipient_name)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"status": "created", "channel_id": req.channel_id,
                "opt_in": False}

    @router.post("/api/authz/egress/opt-in")
    def opt_in_egress_channel(req: EgressOptInReq, request: Request):
        principal = _principal(request)
        from .egress import opt_in
        try:
            opt_in(store, audit, actor=principal, channel_id=req.channel_id)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        return {"status": "opted_in", "channel_id": req.channel_id}

    @router.post("/api/authz/egress/send")
    def submit_egress_send(req: EgressSendReq, request: Request):
        principal = _principal(request)
        from .egress import EgressBlocked, submit_send
        try:
            aid = submit_send(store, audit, actor=principal,
                              channel_id=req.channel_id, tag=req.tag,
                              body=req.body)
        except EgressBlocked as e:
            raise HTTPException(403, str(e))
        return {"status": "pending_approval", "approval_id": aid}

    # -- portal connections (legacy-website browser sessions) --------------
    @router.get("/api/authz/portals")
    def list_portals(request: Request, include_inactive: bool = False):
        _principal(request)
        from .portal import list_portals as _list
        return {"portals": _list(store, active_only=not include_inactive)}

    @router.post("/api/authz/portals")
    def register_portal(req: PortalReq, request: Request):
        principal = _principal(request)
        from .portal import PortalError, register_portal
        try:
            row = register_portal(
                store, audit, actor=principal,
                # same slug normalization as dashboard.py's stored-login id
                name=req.name.strip().lower().replace(" ", "-"),
                base_url=req.base_url, login_url=req.login_url,
                selectors=req.selectors,
                cookie_domains=req.cookie_domains,
                guardian_interval_s=req.guardian_interval_s,
                operations_file=req.operations_file)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except (PortalError, ValueError) as e:
            raise HTTPException(400, str(e))
        return {"status": "registered", "portal": row}

    @router.post("/api/authz/portals/{name}/deregister")
    def deregister_portal(name: str, request: Request):
        principal = _principal(request)
        from .portal import deregister_portal as _dereg
        try:
            _dereg(store, audit, actor=principal, name=name)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))
        return {"status": "deregistered", "name": name}

    @router.post("/api/authz/portals/{name}/health-check")
    def portal_health_check(name: str, request: Request):
        """Run one session-health check NOW (outside the guardian's normal
        interval). Requires connections.connect like the lifecycle routes."""
        principal = _principal(request)
        from .portal import (PortalError, check_session_health,
                             get_portal, record_health_result)
        if not rbac.can(principal.role, "connections.connect"):
            audit.append("authorization_denied", actor=principal, payload={
                "reason": "missing_capability",
                "capability": "connections.connect",
                "what": "portal.health_check"})
            raise HTTPException(403, "portal health check requires "
                                     "capability connections.connect")
        row = get_portal(store, name)
        if row is None or not row["active"]:
            raise HTTPException(404, f"no such portal {name}")
        # azdir is <data_dir>/authz; browser_vault/browser_login key off the
        # install dir (the parent of data_dir) exactly like dashboard.py.
        install_dir = os.path.dirname(os.path.dirname(azdir))
        result = check_session_health(install_dir, row)
        record_health_result(store, audit, name, result)
        return {"portal": name, **result}

    # -- legacy approval adoption (R7-5: audited, API-routed) --------------
    @router.post("/api/authz/approvals/adopt")
    def adopt_legacy(req: LegacyAdoptionReq, request: Request):
        principal = _principal(request)
        from ..db import adopt_legacy_approval
        import sqlite3
        iso_path = os.path.normpath(
            os.path.join(azdir, os.pardir, "isolation.db"))
        conn = sqlite3.connect(iso_path, timeout=10.0)
        try:
            adopt_legacy_approval(conn, req.nonce, audit=audit)
        except LookupError as e:
            raise HTTPException(404, str(e))
        finally:
            conn.close()
        return {"status": "adopted", "nonce": req.nonce,
                "by": principal.principal_id}

    # -- minimal machine-token callback (REQ-CRED-03) ---------------------------
    @router.post("/api/exec/result")
    def exec_result(request: Request):
        principal = _principal(request)
        return {"received": True, "by": principal.principal_id}

    def _principal(request: Request):
        p = getattr(request.state, "principal", None)
        if p is None:
            raise HTTPException(401, "authentication required")
        return p

    return router


def _ensure_recovery_codes(store) -> list[str]:
    from .breakglass import generate_recovery_artifact
    return generate_recovery_artifact(store)
