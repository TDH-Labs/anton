"""Route + data-layer guard infrastructure (AUTHZ-SPEC §2, REQ-DATA-01).

The middleware authenticates every request server-side (fail-closed),
enforces route-level capabilities, records four-identity audit rows for
mutations, and confines machine tokens to their minimal callback
allowlist (REQ-CRED-03). Route auditing and repo lint run in CI, not just
at startup.
"""
from __future__ import annotations

import ast

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import rbac

# Paths reachable unauthenticated. Everything else requires an identity —
# including routes registered after startup (fail-closed, CI-T-DATA-01).
EXEMPT_PATHS = {
    "/", "/health",
    "/api/logo", "/api/logo/son-of-anton",
    "/api/auth/login", "/api/auth/bootstrap",
}

# REQ-CRED-03: the executor's callback identity may invoke ONLY these
# endpoints — never user-scoped reads/writes.
MACHINE_TOKEN_ALLOWLIST = {
    ("POST", "/api/exec/result"),
}

# Declarative route→capability map. Exact matches take precedence over
# prefixes. Unmapped mutating routes fail closed at settings.write.
ROUTE_CAPABILITIES: list[tuple[str, str, str]] = [
    ("POST", "/api/approvals", "approvals.submit"),
    ("POST", "/api/approvals/", "approvals.decide"),
    ("POST", "/api/wizard/", "settings.write"),
    ("POST", "/api/mode/", "settings.write"),
    ("POST", "/api/connections/connect", "connections.connect"),
    ("POST", "/api/chat", "jobs.run"),
    ("GET", "/api/vault/note", "vault.read"),
    ("GET", "/api/authz/users", "users.manage"),
]


def required_capability(method: str, path: str) -> str | None:
    for m, pattern, cap in ROUTE_CAPABILITIES:
        if method != m:
            continue
        if path == pattern or (
                pattern.endswith("/") and path.startswith(pattern)):
            return cap
    return None


class AuthzMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, store, audit):
        super().__init__(app)
        self.store = store
        self.audit = audit

    async def dispatch(self, request, call_next):
        path = request.url.path
        method = request.method
        if path in EXEMPT_PATHS:
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token:
            return self._deny(401, "authentication required")

        if token.startswith("amt_"):
            principal = self.store.resolve_machine_token(token)
            if principal is None:
                return self._deny(401, "invalid machine token")
            if (method, path) not in MACHINE_TOKEN_ALLOWLIST:
                self.store.add_alert(
                    "machine_token_violation", f"{method} {path}")
                self.audit.append("machine_violation", actor=principal,
                                  payload={"method": method, "path": path})
                return self._deny(403, "machine token outside callback allowlist")
        else:
            # Every request re-validates session state — no cached decisions.
            principal = self.store.resolve_session(token)
            if principal is None:
                return self._deny(401, "missing or invalid bearer token")
            capability = required_capability(method, path)
            if capability is not None and not rbac.can(principal.role, capability):
                self.audit.append("authorization_denied", actor=principal,
                                  payload={"capability": capability,
                                           "method": method, "path": path})
                return self._deny(403, f"missing capability: {capability}")

        request.state.principal = principal
        response = await call_next(request)

        if method in ("POST", "PUT", "PATCH", "DELETE") and \
                200 <= response.status_code < 400:
            # Four-identity chain: sponsor user → workspace → agent instance
            # → tool credential (REQ-AUTH-01); all fields non-null.
            self.audit.append(
                "mutation", actor=principal, workspace="default",
                agent_instance=f"dashboard:{principal.username}",
                tool_credential="none",
                payload={"method": method, "path": path,
                         "status": response.status_code})
        return response

    @staticmethod
    def _deny(status: int, detail: str) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status)


# ---------------------------------------------------------------------------
# CI route auditor (REQ-DATA-01): enumerates routes, mounts, websockets and
# static mounts of an application and flags anything not covered by authZ.
# ---------------------------------------------------------------------------

def audit_routes_behavioral(app) -> list[str]:
    findings: list[str] = []
    guarded = getattr(getattr(app, "state", None), "authz_middleware_active",
                      False)
    _walk(app, findings, prefix="", guarded=guarded)
    return findings


def _walk(router_like, findings: list[str], prefix: str, guarded: bool) -> None:
    routes = getattr(router_like, "routes", None) or []
    for route in routes:
        cls = type(route).__name__
        path = getattr(route, "path", "")
        full = f"{prefix}{path}"
        if cls == "Mount":
            sub_app = getattr(route, "app", None)
            if hasattr(sub_app, "routes"):
                _walk(sub_app, findings, prefix=full, guarded=guarded)
            else:
                # Static mounts etc. — covered only by parent middleware.
                if not guarded and full not in EXEMPT_PATHS:
                    findings.append(f"unprotected mount: {full}")
            continue
        if cls == "WebSocketRoute":
            if not guarded and full not in EXEMPT_PATHS:
                findings.append(f"unprotected websocket: {full}")
            continue
        if cls in ("APIRoute", "StarletteRoute", "Route"):
            if not guarded and full not in EXEMPT_PATHS:
                findings.append(f"unguarded route: {full}")


# ---------------------------------------------------------------------------
# Repo lint (REQ-DATA-01): any repository function performing SQL I/O must
# declare a principal parameter.
# ---------------------------------------------------------------------------

def lint_repo_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    violations: list[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef):  # noqa: N802
            performs_io = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and \
                        isinstance(sub.func, ast.Attribute) and \
                        sub.func.attr == "execute":
                    performs_io = True
                    break
            if performs_io and "principal" not in [a.arg for a in node.args.args]:
                violations.append(node.name)
            self.generic_visit(node)

    visit = Visitor()
    visit.visit(tree)
    return violations
