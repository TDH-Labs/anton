"""Declarative capability→role table (AUTHZ-SPEC §1, REQ-AUTH-03).

One declarative table in code; no implicit hierarchy. "Approver" does not
subsume "Operator"; Admins do not subsume Approvers' decision rights by
accident — every cell is explicit.
"""
from __future__ import annotations

ROLES = ("Owner", "Admin", "Approver", "Operator", "Viewer")
SINGLE_OPERATOR_ROLE = "Owner"

CAPABILITY_SETS: dict[str, frozenset[str]] = {
    "Owner": frozenset({
        "users.manage", "roles.assign",
        "grants.create", "grants.revoke",
        "approvals.decide", "approvals.submit",
        "jobs.run", "vault.read", "vault.write",
        "connections.read", "connections.connect",
        "settings.write", "audit.read",
        "egress.channels.manage", "secrets.rotate",
    }),
    "Admin": frozenset({
        "users.manage", "roles.assign",
        "grants.create", "grants.revoke",
        "approvals.decide", "approvals.submit",
        "jobs.run", "vault.read", "vault.write",
        "connections.read", "connections.connect",
        "settings.write", "audit.read",
        "egress.channels.manage", "secrets.rotate",
    }),
    "Approver": frozenset({
        "approvals.decide", "approvals.submit",
        "vault.read", "connections.read", "audit.read",
        # REQ-EGRESS-06: egress channel creation/deletion is Approver-gated.
        "egress.channels.manage",
    }),
    "Operator": frozenset({
        "jobs.run", "approvals.submit",
        "vault.read", "vault.write", "connections.read",
    }),
    "Viewer": frozenset({
        "vault.read", "connections.read",
    }),
}

CAPABILITIES = frozenset().union(*CAPABILITY_SETS.values())
ROLE_CAPABILITIES = {r: set(c) for r, c in CAPABILITY_SETS.items()}

# Capabilities whose exercise in single-operator mode routes through the
# pending-actions delay window (REQ-APPR-05a).
SENSITIVE_CAPABILITIES = frozenset({
    "users.manage", "roles.assign",
    "grants.create", "grants.revoke", "egress.channels.manage",
})


def can(role: str | None, capability: str) -> bool:
    """Explicit table lookup only — no hierarchy, no fallthrough."""
    if role is None or capability not in CAPABILITIES:
        return False
    return capability in CAPABILITY_SETS.get(role, frozenset())


def enabled_roles(config: dict | None) -> list[str]:
    mode = ((config or {}).get("authz") or {}).get("mode", "multi_user")
    if mode == "single_operator":
        return [SINGLE_OPERATOR_ROLE]
    return list(ROLES)
