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
