"""Anton as an MCP server: the operator's second front door.

The web Ops Center is the FIRST door and stays that way. MCP is pull-only --
nothing here notifies anyone -- so it cannot carry the product's push-shaped
value: a money gate that nobody opens a client to see is a stalled
automation, not a pending decision. What MCP is genuinely good at is the
operator's own work, from a client they already have open: "what is Anton
doing", "pause the invoice chaser", "what did it do overnight", "what's
waiting on me".

Every tool here calls Anton's own HTTP surface rather than importing the
engine, for two reasons: the dashboard process already owns the database
connections and the authz middleware, and a second in-process JobEngine
would give this server a private view of state that the running scheduler
does not share.

Run it over stdio:

    anton mcp --base-url http://127.0.0.1:8799

Point a client at that command. When Anton runs with authz enabled, pass a
token with --token (or ANTON_DASHBOARD_TOKEN) -- the mutating tools below
are the same routes the web UI calls and carry the same capability checks.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:8799"


class AntonClient:
    """Thin HTTP face onto a running `anton dashboard`.

    Injectable transport so the tool layer is testable without a live server
    (the same pattern N8NExecutor and qbo_oauth use)."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, token: Optional[str] = None,
                 transport=None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._transport = transport or self._http

    def _http(self, method: str, path: str, body: Optional[dict]) -> tuple[int, str]:
        import httpx
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        r = httpx.request(method, f"{self.base_url}{path}", json=body,
                          headers=headers, timeout=30.0)
        return r.status_code, r.text

    def call(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        """Return the decoded body, or a {"error": ...} dict.

        Never raises: a tool result that says what went wrong is more useful
        to a model than a transport exception, and an unreachable Anton is an
        ordinary condition (the container may be restarting)."""
        try:
            status, text = self._transport(method, path, body)
        except Exception as e:
            return {"error": f"could not reach Anton at {self.base_url}: "
                             f"{type(e).__name__}: {e}"}
        if status == 401 or status == 403:
            return {"error": f"Anton refused the request ({status}). This install has "
                             f"authorization enabled; pass --token or set "
                             f"ANTON_DASHBOARD_TOKEN."}
        if status >= 400:
            return {"error": f"Anton returned {status}: {text[:400]}"}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}


# Tool definitions. Names are verbs from the operator's vocabulary, not route
# names: a model choosing between them should not have to know Anton's HTTP
# surface exists.
TOOLS: list[dict] = [
    {
        "name": "anton_status",
        "description": (
            "What Anton is doing right now and what it has finished today. "
            "Returns work actually in flight, work due this tick, and today's "
            "completed runs with honest ok/failed/skipped statuses."),
        "schema": {"type": "object", "properties": {}},
        "method": "GET", "path": "/api/agent/worklog",
    },
    {
        "name": "anton_list_jobs",
        "description": (
            "Every automation Anton has, with whether it is paused, running, "
            "or has a queued run. Use before steering so the job id is real."),
        "schema": {"type": "object", "properties": {}},
        "method": "GET", "path": "/api/jobs/state",
    },
    {
        "name": "anton_pending_approvals",
        "description": (
            "Decisions waiting on a person. Anton blocks anything touching "
            "money or outbound messages until one of these is approved."),
        "schema": {"type": "object", "properties": {}},
        "method": "GET", "path": "/api/approvals",
    },
    {
        "name": "anton_recent_runs",
        "description": "The run ledger: every dispatch with its exit code, model, and cost.",
        "schema": {"type": "object", "properties": {}},
        "method": "GET", "path": "/api/ledger",
    },
    {
        "name": "anton_usage",
        "description": "Token and cost totals against the configured budgets.",
        "schema": {"type": "object", "properties": {}},
        "method": "GET", "path": "/api/usage",
    },
    {
        "name": "anton_search_memory",
        "description": (
            "Read a note from Anton's second brain by slug. The vault is "
            "markdown on disk; this returns one note's content."),
        "schema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Note slug, e.g. 'index'"}},
            "required": ["slug"],
        },
        "method": "GET", "path": "/api/vault/note",
        "query": ["slug"],
    },
]

# Mutating tools are listed separately so the boundary is visible in the
# source, not just in the schema: everything below changes what Anton does.
STEER_ACTIONS = ("pause", "resume", "run-now", "skip-next")


def dispatch(client: AntonClient, name: str, arguments: dict) -> Any:
    """Route one tool call to Anton's HTTP surface.

    A plain function, deliberately: the SDK's decorators bind schemas from
    signatures, but the routing and argument validation below must be
    testable with a fake transport and no MCP session at all."""
    for spec in TOOLS:
        if spec["name"] != name:
            continue
        path = spec["path"]
        for key in spec.get("query", []):
            value = arguments.get(key)
            if value is None:
                return {"error": f"{name} requires '{key}'"}
            sep = "&" if "?" in path else "?"
            path = f"{path}{sep}{key}={value}"
        return client.call(spec["method"], path, None)

    if name == "anton_steer_job":
        job_id = arguments.get("job_id")
        action = arguments.get("action")
        if not job_id:
            return {"error": "anton_steer_job requires 'job_id'"}
        if action not in STEER_ACTIONS:
            return {"error": f"unknown action {action!r}; expected one of "
                             f"{', '.join(STEER_ACTIONS)}"}
        return client.call("POST", f"/api/jobs/{job_id}/steer", {"action": action})

    if name == "anton_decide_approval":
        aid = arguments.get("approval_id")
        decision = arguments.get("decision")
        if aid is None:
            return {"error": "anton_decide_approval requires 'approval_id'"}
        if decision not in ("once", "always", "defer"):
            return {"error": f"unknown decision {decision!r}"}
        return client.call("POST", f"/api/approvals/{aid}", {"decision": decision})

    return {"error": f"unknown tool {name!r}"}


def _register(server, client: "AntonClient") -> None:
    """Bind every tool onto an MCPServer.

    The SDK derives each tool's input schema from the function signature, so
    the parameter names and annotations below ARE the wire contract; keep
    them aligned with `dispatch`, which stays a plain function so the whole
    tool layer is testable without an MCP session.
    """
    def _json(result: Any) -> str:
        return json.dumps(result, indent=2, default=str)

    for spec in TOOLS:
        if spec.get("query"):
            continue  # parameterised tools are declared explicitly below

        def make(spec_=spec):
            def run() -> str:
                return _json(dispatch(client, spec_["name"], {}))
            return run

        server.add_tool(make(), name=spec["name"], description=spec["description"])

    def anton_search_memory(slug: str) -> str:
        """Read one note from Anton's second brain by slug."""
        return _json(dispatch(client, "anton_search_memory", {"slug": slug}))

    server.add_tool(
        anton_search_memory, name="anton_search_memory",
        description=next(t["description"] for t in TOOLS
                         if t["name"] == "anton_search_memory"))

    def anton_steer_job(job_id: str, action: str) -> str:
        """Pause, resume, run now, or skip the next window for one automation."""
        return _json(dispatch(client, "anton_steer_job",
                              {"job_id": job_id, "action": action}))

    server.add_tool(
        anton_steer_job, name="anton_steer_job",
        description=(
            "Change whether or when one automation runs. Actions: pause "
            "(stop running it until resumed), resume, run-now (dispatch once "
            "at the next tick regardless of schedule), skip-next (skip only "
            "the next scheduled window). Takes effect at Anton's next poll "
            "tick, typically within 15 seconds, and never interrupts a run "
            "already in progress. A paused job ignores run-now until resumed."))

    def anton_decide_approval(approval_id: int, decision: str) -> str:
        """Approve once, approve always, or defer one pending decision."""
        return _json(dispatch(client, "anton_decide_approval",
                              {"approval_id": approval_id, "decision": decision}))

    server.add_tool(
        anton_decide_approval, name="anton_decide_approval",
        description=(
            "Approve or defer one pending decision. 'once' approves this "
            "instance only; 'always' approves and stops asking for this kind; "
            "'defer' leaves it pending. This releases real money movement or "
            "outbound messages -- confirm with the person before calling it."))


async def serve(base_url: str = DEFAULT_BASE_URL, token: Optional[str] = None) -> None:
    """Run the MCP server over stdio until the client disconnects."""
    from mcp.server import MCPServer

    client = AntonClient(base_url, token)
    server = MCPServer(
        name="anton",
        version="0.2.0",
        instructions=(
            "Anton is a small-business automation agent. Its web Ops Center is "
            "the primary interface and the only surface that can notify a "
            "person; these tools are the operator's second door. Approvals "
            "gate real money movement and outbound messages -- never decide "
            "one without the person asking you to."),
    )
    _register(server, client)
    await server.run_stdio_async()


def main(base_url: Optional[str] = None, token: Optional[str] = None) -> int:
    """Entry point for `anton mcp`."""
    import asyncio
    resolved = base_url or os.environ.get("ANTON_BASE_URL") or DEFAULT_BASE_URL
    resolved_token = token or os.environ.get("ANTON_DASHBOARD_TOKEN") or None
    asyncio.run(serve(resolved, resolved_token))
    return 0
