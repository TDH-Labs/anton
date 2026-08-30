"""anton/mcp_server.py -- the tool layer, exercised with a fake transport so
no live dashboard is needed."""
from __future__ import annotations

import json
import unittest

from anton.mcp_server import STEER_ACTIONS, TOOLS, AntonClient, dispatch


class FakeTransport:
    """Records calls and replays canned responses keyed by (method, path)."""

    def __init__(self, responses=None, boom=None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str, object]] = []
        self.boom = boom

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if self.boom:
            raise self.boom
        return self.responses.get((method, path), (200, json.dumps({"ok": True})))


def client(responses=None, boom=None, token=None):
    t = FakeTransport(responses, boom)
    return AntonClient("http://anton.test", token=token, transport=t), t


class TestReadTools(unittest.TestCase):
    def test_every_declared_tool_dispatches_to_its_route(self):
        for spec in TOOLS:
            c, t = client()
            args = {k: "x" for k in spec.get("query", [])}
            dispatch(c, spec["name"], args)
            self.assertEqual(len(t.calls), 1, spec["name"])
            method, path, _ = t.calls[0]
            self.assertEqual(method, spec["method"], spec["name"])
            self.assertTrue(path.startswith(spec["path"]), (spec["name"], path))

    def test_status_returns_the_decoded_body(self):
        c, _ = client({("GET", "/api/agent/worklog"):
                       (200, json.dumps({"ongoing": [], "done": [{"text": "x"}]}))})
        out = dispatch(c, "anton_status", {})
        self.assertEqual(out["done"][0]["text"], "x")

    def test_a_query_tool_requires_its_parameter(self):
        c, t = client()
        out = dispatch(c, "anton_search_memory", {})
        self.assertIn("requires", out["error"])
        self.assertEqual(t.calls, [], "must not call Anton with a missing parameter")

    def test_a_query_tool_appends_its_parameter(self):
        # path, not slug: dashboard.py's GET /api/vault/note requires
        # `path` -- verified live, this was wrong until a real
        # cross-container run against a real Anton returned a 422.
        c, t = client()
        dispatch(c, "anton_search_memory", {"path": "index"})
        self.assertEqual(t.calls[0][1], "/api/vault/note?path=index")


class TestSteerTool(unittest.TestCase):
    def test_each_action_posts_to_the_steer_route(self):
        for action in STEER_ACTIONS:
            c, t = client()
            dispatch(c, "anton_steer_job", {"job_id": "daily-digest", "action": action})
            self.assertEqual(t.calls[0][0], "POST")
            self.assertEqual(t.calls[0][1], "/api/jobs/daily-digest/steer")
            self.assertEqual(t.calls[0][2], {"action": action})

    def test_unknown_action_is_refused_without_calling_anton(self):
        c, t = client()
        out = dispatch(c, "anton_steer_job", {"job_id": "x", "action": "delete"})
        self.assertIn("unknown action", out["error"])
        self.assertEqual(t.calls, [])

    def test_missing_job_id_is_refused(self):
        c, t = client()
        self.assertIn("requires", dispatch(c, "anton_steer_job", {"action": "pause"})["error"])
        self.assertEqual(t.calls, [])


class TestApprovalTool(unittest.TestCase):
    def test_decision_posts_to_the_approval_route(self):
        c, t = client()
        dispatch(c, "anton_decide_approval", {"approval_id": 7, "decision": "once"})
        self.assertEqual(t.calls[0][:2], ("POST", "/api/approvals/7"))
        self.assertEqual(t.calls[0][2], {"decision": "once"})

    def test_unknown_decision_is_refused_without_calling_anton(self):
        c, t = client()
        out = dispatch(c, "anton_decide_approval", {"approval_id": 1, "decision": "yolo"})
        self.assertIn("unknown decision", out["error"])
        self.assertEqual(t.calls, [])


class TestReportFailureTool(unittest.TestCase):
    """The n8n Error Trigger workflow's whole path to Anton: no /hooks/*
    surface is reachable from a sibling container (WebhookServer binds
    container loopback), and the public auth-gate is a cookie-session login
    page, not a bearer-token API door -- confirmed live, a bare Bearer
    header gets the login HTML back regardless of validity. This tool, over
    the MCP HTTP transport's real per-request auth, is the only door an
    external caller like n8n actually has."""

    def test_reports_through_the_inbox_route(self):
        c, t = client()
        dispatch(c, "anton_report_failure",
                {"subject": "n8n workflow failed", "body": "detail"})
        self.assertEqual(t.calls[0][:2], ("POST", "/api/inbox/messages"))
        self.assertEqual(t.calls[0][2], {"subject": "n8n workflow failed", "body": "detail"})

    def test_body_defaults_to_empty_string(self):
        c, t = client()
        dispatch(c, "anton_report_failure", {"subject": "x"})
        self.assertEqual(t.calls[0][2]["body"], "")

    def test_missing_subject_is_refused_without_calling_anton(self):
        c, t = client()
        out = dispatch(c, "anton_report_failure", {"body": "no subject"})
        self.assertIn("requires", out["error"])
        self.assertEqual(t.calls, [])


class TestFailureModes(unittest.TestCase):
    def test_an_unreachable_anton_is_a_message_not_an_exception(self):
        c, _ = client(boom=ConnectionRefusedError("no route to host"))
        out = dispatch(c, "anton_status", {})
        self.assertIn("could not reach Anton", out["error"])

    def test_401_explains_the_token(self):
        c, _ = client({("GET", "/api/ledger"): (401, "unauthorized")})
        out = dispatch(c, "anton_recent_runs", {})
        self.assertIn("ANTON_DASHBOARD_TOKEN", out["error"])

    def test_500_is_surfaced_not_swallowed(self):
        c, _ = client({("GET", "/api/ledger"): (500, "boom")})
        self.assertIn("500", dispatch(c, "anton_recent_runs", {})["error"])

    def test_non_json_body_is_returned_as_text(self):
        c, _ = client({("GET", "/api/ledger"): (200, "not json at all")})
        self.assertEqual(dispatch(c, "anton_recent_runs", {})["text"], "not json at all")

    def test_unknown_tool_name(self):
        c, _ = client()
        self.assertIn("unknown tool", dispatch(c, "anton_nope", {})["error"])


class TestToolRegistration(unittest.TestCase):
    """The SDK derives each tool's schema from its function signature, so the
    registration must actually bind every tool this module claims."""

    def _server(self):
        from mcp.server import MCPServer
        from anton.mcp_server import _register
        c, _ = client()
        s = MCPServer(name="anton-test", version="0")
        _register(s, c)
        return s

    def test_every_declared_tool_plus_all_mutating_ones_are_registered(self):
        import asyncio
        tools = asyncio.run(self._server().list_tools())
        names = {t.name for t in tools}
        self.assertEqual(
            names,
            {t["name"] for t in TOOLS} | {"anton_steer_job", "anton_decide_approval",
                                          "anton_report_failure"})

    def test_the_steering_tool_states_its_timing_honestly(self):
        import asyncio
        tools = asyncio.run(self._server().list_tools())
        steer = next(t for t in tools if t.name == "anton_steer_job")
        self.assertIn("next poll tick", steer.description)
        self.assertIn("never interrupts", steer.description)

    def test_the_approval_tool_warns_that_it_releases_real_actions(self):
        import asyncio
        tools = asyncio.run(self._server().list_tools())
        approve = next(t for t in tools if t.name == "anton_decide_approval")
        self.assertIn("confirm with the person", approve.description)

    def test_the_parameterised_tool_declares_its_argument(self):
        import asyncio
        tools = asyncio.run(self._server().list_tools())
        mem = next(t for t in tools if t.name == "anton_search_memory")
        self.assertIn("path", mem.input_schema.get("properties", {}))

    def test_propose_work_tool_is_declared_and_dispatches_to_opportunities(self):
        import asyncio
        from anton import mcp_server
        # declared in the TOOLS list (so the generic register loop binds it)
        spec = next(t for t in mcp_server.TOOLS if t["name"] == "anton_propose_work")
        self.assertEqual(spec["method"], "GET")
        self.assertEqual(spec["path"], "/api/opportunities")
        # dispatches through the HTTP surface like every read tool
        c, t = client()
        mcp_server.dispatch(c, "anton_propose_work", {})
        self.assertEqual(t.calls[0][0], "GET")
        self.assertEqual(t.calls[0][1], "/api/opportunities")
        # registered on a real server
        server = self._server()
        tools = asyncio.run(server.list_tools())
        self.assertIn("anton_propose_work", {x.name for x in tools})

    def test_http_transport_rejects_bare_requests_on_a_real_socket(self):
        """The real exploit the reviewer ran: server launched WITH a token,
        then a bare request with no Authorization header hits the HTTP
        surface; _require_bearer must reject it -- the token must gate
        REQUESTS, not just launch. This opens an actual socket.

        Deliberately calls mcp_server.serve() -- the actual `anton mcp`
        entry point -- rather than hand-assembling an MCPServer +
        _require_bearer pair. An earlier version of this test built its own
        server with no token_verifier and so never caught that serve()
        itself crashed on construction (MCPServer rejects a token_verifier
        passed without matching `auth` settings): the test proved the
        middleware works in isolation while the real command was broken.
        Only exercising the real entry point closes that gap."""
        import asyncio, threading, time, urllib.error, urllib.request
        from anton import mcp_server

        TOKEN = "test-token-123"
        PORT = 18878

        def run_server():
            asyncio.run(mcp_server.serve(
                base_url="http://127.0.0.1:1", token=TOKEN,
                transport="http", host="127.0.0.1", port=PORT))

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/mcp", timeout=0.3)
                break
            except urllib.error.HTTPError:
                break  # server answered (even with an error) -- it's up
            except Exception:
                time.sleep(0.1)
        else:
            self.fail("serve() never opened the socket -- see the real crash it must not have")

        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/mcp",
            data=b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
            headers={"Content-Type": "application/json"},
            method="POST")
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("bare request was accepted - MCP surface is unauthenticated")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (401, 403), f"expected 401/403, got {e.code}")

        good = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/mcp",
            data=b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
            headers={"Content-Type": "application/json",
                     "Accept": "application/json, text/event-stream",
                     "Authorization": f"Bearer {TOKEN}"},
            method="POST")
        try:
            resp = urllib.request.urlopen(good, timeout=3)
            self.assertNotIn(resp.status, (401, 403))
        except urllib.error.HTTPError as e:
            self.assertNotIn(e.code, (401, 403),
                             "token request rejected, expected pass-through to SDK")

    def test_stdio_transport_needs_no_token(self):
        """serve() must not require a token for stdio: the process boundary
        is the auth there, and a hand-set ANTON_DASHBOARD_TOKEN in the
        operator's shell must not make plain `anton mcp` (Claude Code,
        Codex, pi, opencode -- all stdio, all local) refuse to start.
        run_stdio_async is mocked -- it reads real process stdin, which
        pytest's own capture leaves unreadable, unrelated to what this
        test checks."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from anton import mcp_server

        with patch("mcp.server.MCPServer.run_stdio_async", new_callable=AsyncMock) as run:
            asyncio.run(mcp_server.serve(
                base_url="http://127.0.0.1:1", token=None, transport="stdio"))
            run.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
