"""Self-deploy provisioning (commercial readiness): cryptographic secrets
are generated automatically at first boot \u2014 no human, no shared repo
state. Each secret persists as a 0600 file under data/authz/ so separate
processes (dashboard, serve/scheduler) read the SAME value, and the
operator can rotate by replacing the file.

Trust boundary (documented): any process running as the same OS user can
read these files. That is the standard single-box deployment model; the
stronger multi-user boundary is enforced by the authZ spine itself.
"""
from __future__ import annotations

import os
import secrets as _pysecrets

from .secrets import write_private_file


def _read_private(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            v = f.read().strip()
        return v or None
    except FileNotFoundError:
        return None


def ensure_decision_secret(data_dir: str, config: dict) -> str:
    """Returns the decision HMAC secret for this deployment.

    Precedence: config.yaml authz.decision_secret \u2192 persisted file
    data/authz/decision.secret \u2192 freshly generated (persisted 0600).
    Self-deploy property: an operator never has to invent this value."""
    cfg = ((config.get("authz") or {}).get("decision_secret") or "").strip()
    if cfg:
        return cfg
    path = os.path.join(data_dir, "authz", "decision.secret")
    existing = _read_private(path)
    if existing:
        return existing
    value = _pysecrets.token_urlsafe(32)
    write_private_file(path, value)
    return value


def ensure_webhook_secret(data_dir: str, config: dict) -> str:
    """Same contract for the webhook trigger shared secret. Fail-closed
    consumers refuse triggers while this is unset, so provisioning happens
    here rather than being left to the operator."""
    cfg = ((config.get("general") or {}).get("webhook_secret") or "").strip()
    if cfg:
        return cfg
    path = os.path.join(data_dir, "authz", "webhook.secret")
    existing = _read_private(path)
    if existing:
        return existing
    value = _pysecrets.token_urlsafe(32)
    write_private_file(path, value)
    return value


def ensure_apiproxy_credential(store, azdir: str, audit=None) -> str | None:
    """Provision the Ops Center apiproxy's machine credential.

    The apiproxy (anton-studio's Node half) forwards cookie-only browser
    requests to the dashboard's :8799 surface; under authz those requests
    need a bearer identity of their own. This mints an ``amt_`` token bound
    to a dedicated kind="service" principal owned by the first human user,
    scoped by guards.MACHINE_TOKEN_SCOPES["apiproxy"] to exactly the routes
    the proxy registers — never user-level powers, and disjoint from the
    executor's callback token. Persists 0600 under authz/apiproxy.token so
    the Node process can read it without shell access to the DB.

    Idempotent + self-healing: an existing file whose token still resolves
    is left alone; a revoked/expired/stale token triggers a fresh mint
    (downtime-free rotation — overlapping generations are supported by the
    store). Returns None when there is no human owner yet (pristine first
    boot before /api/auth/bootstrap); callers re-invoke after bootstrap.
    """
    from .guards import APIPROXY_SERVICE_NAME

    token_path = os.path.join(azdir, "apiproxy.token")
    existing = _read_private(token_path)
    if existing and store.resolve_machine_token(existing) is not None:
        return existing
    owner = store.first_human_user()
    if owner is None:
        return None  # no human yet — deferred until Owner bootstrap
    svc = store.get_user_by_username(APIPROXY_SERVICE_NAME)
    if svc is None:
        svc = store.create_service_identity(
            APIPROXY_SERVICE_NAME, owner["id"])
    token, _jti = store.mint_machine_token(svc["id"])
    write_private_file(token_path, token)
    if audit is not None:
        try:
            audit.append("machine_provisioned", actor=svc["username"],
                         payload={"service": APIPROXY_SERVICE_NAME})
        except Exception:
            pass  # provisioning must never fail on audit-chain trouble
    # Self-deploy visibility, same pattern as the owner-claim code print.
    print(f"[authz] provisioned scoped machine credential for "
          f"{APIPROXY_SERVICE_NAME} -> {token_path}", flush=True)
    return token
