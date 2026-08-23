"""Canonical data-layer enforcement (AUTHZ-SPEC §2, ED-1).

Repository functions take an acting-principal parameter and apply
ownership/ACL predicates themselves — where route guards and this layer
disagree, this layer wins. Non-human contexts (background jobs,
migrations) require the typed principals from principals.py.
"""
from __future__ import annotations

from .principals import (  # noqa: F401  (re-exports for CI tests)
    MigrationPrincipal, PrincipalTypeError, SystemPrincipal, require_nonhuman)

# Allowlisted background jobs permitted to run under SystemPrincipal
# (REQ-DATA-03). Anything else raises JobRegistryAlarm.
JOB_REGISTRY = {
    "e2e-canary",
    "digest",
    "backfill",
    "vault-scan",
    "pending-action-apply",
}


class JobRegistryAlarm(Exception):
    """A SystemPrincipal action outside the allowlisted job registry."""


def run_scheduled_job(store, audit, principal: SystemPrincipal) -> None:
    require_nonhuman(principal)  # an admin user object here is a type error
    if principal.job_id not in JOB_REGISTRY:
        raise JobRegistryAlarm(
            f"SystemPrincipal job {principal.job_id!r} not in allowlist")
    audit.append("system_action", actor=principal,
                 payload={"job": principal.job_id})


def get_connection_credential(store, principal, connection_id: str) -> dict:
    """Canonical ACL check for connector credentials. `principal` is a
    required positional parameter by design: calling this without one must
    raise TypeError at every bypass attempt (CI-T-DATA-01)."""
    from . import rbac
    role = getattr(principal, "role", None)
    if rbac.can(role, "secrets.rotate") or rbac.can(role, "settings.write"):
        return {"connection_id": connection_id, "via": "privileged"}
    row = store.conn.execute(
        "SELECT scope FROM connection_grants WHERE grantee_id=? AND "
        "connection_id=? AND active=1 ORDER BY id DESC LIMIT 1",
        (getattr(principal, "user_id", ""), connection_id)).fetchone()
    if row is None:
        raise PermissionError(
            f"principal {getattr(principal, 'user_id', '?')} has no active "
            f"grant on {connection_id}")
    return {"connection_id": connection_id, "scope": row["scope"],
            "via": "grant"}
