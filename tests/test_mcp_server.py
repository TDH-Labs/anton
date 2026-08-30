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
        c, t = client()
        dispatch(c, "anton_search_memory", {"slug": "index"})
        self.assertEqual(t.calls[0][1], "/api/vault/note?slug=index")


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

    def test_every_declared_tool_plus_both_mutating_ones_are_registered(self):
        import asyncio
        tools = asyncio.run(self._server().list_tools())
        names = {t.name for t in tools}
        self.assertEqual(
            names,
            {t["name"] for t in TOOLS} | {"anton_steer_job", "anton_decide_approval"})

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
        self.assertIn("slug", mem.input_schema.get("properties", {}))

    def test_http_transport_requires_a_token(self):
        """n8n's MCP client node and Claude Desktop URL need the HTTP/SSE
        surface (`anton mcp --transport sse|http`); that surface is a
        network door and must refuse to open without a token, so a bare
        `--transport http` cannot silently expose Anton's tools on a port."""
        import asyncio
        from anton import mcp_server
        async def _run():
            with self.assertRaises(ValueError) as ctx:
                await mcp_server.serve("http://127.0.0.1:8799", None,
                                       transport="http", port=8877)
            self.assertIn("requires a token", str(ctx.exception))
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
