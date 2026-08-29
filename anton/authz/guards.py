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
    # Intuit redirects the operator's browser here mid-OAuth — the browser
    # carries no bearer; state-token validation inside the route is the gate.
    "/api/wizard/oauth/callback",
    # Anton's own built UI (dashboard.py mounts anton/web/dist). Same trust
    # class as "/" above: application code and fonts, no user data, and a
    # browser must be able to load them BEFORE it can render the sign-in or
    # owner-claim screen. Everything here still sits behind auth-gate's
    # password on the only published port.
    "/assets", "/fonts",
}

# REQ-CRED-03: the executor's callback identity may invoke ONLY these
# endpoints — never user-scoped reads/writes. Machine credentials whose
# service principal has NO entry in MACHINE_TOKEN_SCOPES below are held to
# exactly this list (the pre-scoping contract; unchanged).
MACHINE_TOKEN_ALLOWLIST = {
    ("POST", "/api/exec/result"),
}

# Scoped surfaces per service principal (matched by username): a principal
# listed here may invoke ONLY its method/path patterns — everything else is
# deny + audit, same as the static allowlist above. Patterns ending in '*'
# prefix-match; others match exactly. The Ops Center apiproxy forwards the
# browser's cookie-only requests to the dashboard (:8799), so it needs its
# OWN machine identity covering exactly the routes it registers (apiproxy/src/
# index.ts) — never user-level powers, and deliberately disjoint from the
# executor's callback surface so revoking one cannot open the other.
APIPROXY_SERVICE_NAME = "apiproxy"
MACHINE_TOKEN_SCOPES: dict[str, set[tuple[str, str]]] = {
    APIPROXY_SERVICE_NAME: {
        # dashboard.py surfaces the proxy registers
        ("GET", "/api/mode*"), ("POST", "/api/mode*"),
        ("GET", "/api/vault/note"),
        ("GET", "/api/logo"), ("GET", "/api/logo/son-of-anton"),
        ("GET", "/api/initiatives"),
        ("GET", "/api/jobs"),
        ("GET", "/api/approvals*"), ("POST", "/api/approvals*"),
        ("POST", "/api/chat"),
        # wizard: provider keys/models/OAuth/MCP setup flows
        ("GET", "/api/wizard/*"), ("POST", "/api/wizard/*"),
        # ops_api.py surfaces
        ("GET", "/api/systems*"), ("PUT", "/api/systems*"),
        # exact + one-segment children, mirroring the webserver's
        # prefix-route semantics (never /api/agentPreset et al.)
        ("GET", "/api/agent"), ("GET", "/api/agent/*"),
        ("GET", "/api/learning"),
        ("GET", "/api/incidents"),
        ("GET", "/api/automations*"), ("PUT", "/api/automations*"),
        ("POST", "/api/automations/draft"),
        ("POST", "/api/setup"),
        # Add-ons connectors (dashboard.py + connections.py): the bundled
        # catalog / MCP-registry sync read, connect clicks, and the
        # Composio/Nango bridge surfaces. Without these the proxy's scoped
        # credential 403s and Add-ons silently renders an empty grid.
        ("GET", "/api/connections*"),
        ("POST", "/api/connections/connect"),
        ("GET", "/api/integrations*"),
        ("POST", "/api/integrations/connect/start"),
        # pasting a hosted-OAuth bridge credential from the Add-ons screen
        # (settings.write trust tier, same as the wizard provider-key POSTs)
        ("POST", "/api/integrations/bridges/configure"),
        # n8n connection settings (Automations screen's "Draw it" notice +
        # the Settings n8n section).
        ("GET", "/api/n8n*"), ("POST", "/api/n8n*"),
    },
}


def _scope_allows(pattern: str, path: str) -> bool:
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    return path == pattern

# Declarative route→capability map. Exact matches take precedence over
# prefixes. "" = any authenticated identity. MUTATING methods with no
# mapping fail closed at settings.write (ED-2 default deny).
# NOTE (review O-1): unmapped READ routes are authenticated-but-until-mapped
# readable by any role including Viewer; the data layer remains canonical.
ROUTE_CAPABILITIES: list[tuple[str, str, str]] = [
    ("POST", "/api/approvals", "approvals.submit"),
    ("POST", "/api/approvals/", "approvals.decide"),
    ("POST", "/api/wizard/", "settings.write"),
    ("POST", "/api/mode/", "settings.write"),
    ("POST", "/api/setup", "settings.write"),
    ("PUT", "/api/systems/", "settings.write"),
    ("PUT", "/api/automations/", "settings.write"),
    # Ops Center automation drafting (ops_api.py) — an explicit mapping so
    # human sessions never ride the default-deny fallback on this proxied
    # mutating route.
    ("POST", "/api/automations/draft", "settings.write"),
    ("POST", "/api/connections/connect", "connections.connect"),
    # Inbox loop: ingesting a message is a mutation of the work queue/vault
    # (settings.write tier — same as every other write surface). Reads of
    # the queue are authenticated-but-unmapped, like other read routes.
    ("POST", "/api/inbox/messages", "settings.write"),
    ("POST", "/api/chat", "jobs.run"),
    # Ask Anton: streaming a prompt dispatches through the executor exactly as
    # the one-shot endpoint does, and session lifecycle is the same trust
    # tier -- a Viewer must not be able to spend model budget or delete
    # another person's conversation.
    ("POST", "/api/chat/stream", "jobs.run"),
    ("POST", "/api/chat/sessions", "jobs.run"),
    ("DELETE", "/api/chat/sessions/", "jobs.run"),
    # Operator steering (ops_api.py): pause/resume, run-now, skip-next. These
    # decide whether and when a job runs, so they carry jobs.run rather than
    # settings.write -- a Viewer must not be able to silence an automation,
    # and an Operator must be able to without holding settings rights.
    ("POST", "/api/jobs/", "jobs.run"),
    ("GET", "/api/vault/note", "vault.read"),
    ("GET", "/api/authz/users", "users.manage"),
    ("DELETE", "/api/auth/sessions/", ""),
    ("POST", "/api/auth/logout", ""),
    ("POST", "/api/exec/result", ""),
    # REQ-EGRESS-06: channel lifecycle is Approver-gated; sends are
    # submissions into the approvals spine.
    ("POST", "/api/authz/egress/channels", "egress.channels.manage"),
    ("POST", "/api/authz/egress/opt-in", "egress.channels.manage"),
    ("POST", "/api/authz/egress/send", "approvals.submit"),
    # adoption of pre-authz approval rows is a decision-side operation
    ("POST", "/api/authz/approvals/adopt", "approvals.decide"),
    ("POST", "/api/integrations/connect/start", "connections.connect"),
    ("POST", "/api/integrations/bridges/configure", "settings.write"),
    ("POST", "/api/integrations/connect/status", "connections.read"),
    ("POST", "/api/integrations/actions/execute", "jobs.run"),
    # Portal Connections lifecycle: registration/deregistration and manual
    # health checks are Approver-tier (connections.connect), matching the
    # stored-login connect flow they govern. Exact entry above covers the
    # collection route; this prefix covers /{name}/deregister + health-check.
    ("POST", "/api/authz/portals", "connections.connect"),
    ("POST", "/api/authz/portals/", "connections.connect"),
    ("POST", "/api/n8n/", "settings.write"),
]

DEFAULT_MUTATING_CAPABILITY = "settings.write"


def _lookup(method: str, path: str) -> str | None:
    """Explicit map entry only; None = unmapped."""
    for m, pattern, cap in ROUTE_CAPABILITIES:
        if method != m:
            continue
        if path == pattern or (
                pattern.endswith("/") and path.startswith(pattern)):
            return cap
    return None


def required_capability(method: str, path: str) -> str | None:
    cap = _lookup(method, path)
    if cap is not None:
        return cap
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        # Fail closed: unmapped mutating routes demand a privileged
        # capability rather than passing open (CI-T-DATA-01 / ED-2).
        return DEFAULT_MUTATING_CAPABILITY
    return None


class DenyWebSockets:
    """Raw-ASGI middleware: BaseHTTPMiddleware only sees http scopes, so a
    WebSocket route would bypass authZ entirely (review R2A-5). Phase 1
    ships zero WebSocket routes; any connection is fail-closed rejected
    with policy violation 1008. Remove this class ONLY together with an
    authenticated WS guard in guards.py."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await receive()  # consume the websocket.connect message
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


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
            scopes = MACHINE_TOKEN_SCOPES.get(principal.username)
            if scopes is None:
                allowed = (method, path) in MACHINE_TOKEN_ALLOWLIST
            else:
                allowed = any(
                    m == method and _scope_allows(p, path)
                    for m, p in scopes)
            if not allowed:
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
            if capability and not rbac.can(principal.role, capability):
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
            # Phase-1 honesty note (review F11): dashboard-originated actions
            # have exactly one workspace and no tool credential yet — these
            # values are accurate-for-now, not fabricated identity.
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
    """Structural + coverage audit. Even when the middleware is active
    (runtime fail-closed), every MUTATING route must carry an explicit
    capability mapping — anything relying on the default-deny fallback is
    flagged so the map stays deliberate, not accidental."""
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
        methods = set(getattr(route, "methods", None) or ())
        if cls == "Mount":
            sub_app = getattr(route, "app", None)
            if hasattr(sub_app, "routes"):
                _walk(sub_app, findings, prefix=full, guarded=guarded)
            else:
                # Static/file mounts carry no auth dependency of their own;
                # they are only covered by the parent middleware — always
                # surface them so the coverage claim stays explicit.
                if full not in EXEMPT_PATHS:
                    findings.append(f"mount without own auth dependency: {full}")
            continue
        if cls == "_IncludedRouter":
            # FastAPI records include_router() as a lazy wrapper; recurse
            # into the real router so authz routes are enumerated (R8-2).
            sub = getattr(route, "original_router", None) or getattr(
                route, "router", None)
            if sub is not None:
                _walk(sub, findings, prefix=prefix, guarded=guarded)
            continue
        if cls in ("WebSocketRoute", "APIWebSocketRoute"):
            # Phase-1 policy: no WebSocket routes; runtime denies the scope
            # (DenyWebSockets). Any WS route appearing here is a finding.
            findings.append(
                f"websocket route present (denied at runtime): {full}")
            continue
        if cls in ("APIRoute", "StarletteRoute", "Route"):
            if full in EXEMPT_PATHS:
                continue
            for m in methods - {"HEAD", "OPTIONS"}:
                explicit = _lookup(m, full)
                if m in ("POST", "PUT", "PATCH", \
                         "DELETE") and explicit is None:
                    findings.append(
                        f"mutating route relies on default-deny fallback: "
                        f"{m} {full}")
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
        def _check(self, node):
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

        def visit_FunctionDef(self, node):  # noqa: N802
            self._check(node)

        def visit_AsyncFunctionDef(self, node):  # noqa: N802
            self._check(node)

    visit = Visitor()
    visit.visit(tree)
    return violations
