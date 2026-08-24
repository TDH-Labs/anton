"""POST /api/automations/draft — the Automations screen's "Describe it" /
"Upload a doc" drafting endpoint (ops_api.py). Contract under test:

- strict server-side shape validation of the model's JSON (fenced output,
  missing fields, wrong trigger kinds, empty/oversized steps all fail closed);
- governor philosophy: a draft never touches the automations table and never
  comes back running — activation only ever happens through the ordinary
  PUT /api/automations/:id approve path.
"""
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from anton.cli import _build
from anton.config import load_config
from anton.dashboard import create_app
from anton.executor.base import Executor, RunResult
from anton.ops_api import build_draft_prompt, parse_automation_draft
from anton.ops_schema import ensure_ops_schema
from anton.setup import run_setup

GOOD_DRAFT = {
    "name": "Morning cost digest",
    "plain": "Pulls job costs and flags overruns.",
    "trigger": {"kind": "cron", "display": "Every weekday at 7 AM", "expr": "0 7 * * 1-5"},
    "steps": [
        {"text": "Pull yesterday's job costs from the accounting file", "assignee": "agent"},
        {"text": "Email me anything over budget", "assignee": "agent"},
    ],
}


class _ScriptedExecutor(Executor):
    """Returns a canned payload as the model's raw stdout — lets these tests
    exercise exactly what parse_automation_draft does with real LLM output."""

    def __init__(self, output: str = "", exit_code: int = 0):
        self.output = output
        self.exit_code = exit_code
        self.last_prompt: str | None = None

    def run(self, task: str, *, model: str, provider: str,
            cwd=None, timeout_s=None) -> RunResult:
        self.last_prompt = task
        return RunResult(exit_code=self.exit_code, output=self.output, stderr="",
                         duration_ms=1, model=model, provider=provider)


class TestAutomationDraftEndpoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        info = run_setup(self._tmp.name, executor="fake")
        config = load_config(info["config"])
        _jobs, _ledger, self.engine = _build(config, info["data_dir"], "fake")
        self.data_dir = info["data_dir"]
        app = create_app(self.engine, self.data_dir, config)
        self.client = TestClient(app)
        self.scripted = _ScriptedExecutor()
        self.engine.executor = self.scripted

    def tearDown(self):
        self._tmp.cleanup()

    def _automations_count(self) -> int:
        conn = sqlite3.connect(f"{self.data_dir}/isolation.db", timeout=10.0)
        ensure_ops_schema(conn)
        try:
            return conn.execute("SELECT COUNT(*) FROM automations").fetchone()[0]
        finally:
            conn.close()

    def test_draft_returns_reviewable_shape_and_never_writes_or_activates(self):
        import json
        self.scripted.output = json.dumps(GOOD_DRAFT)
        r = self.client.post("/api/automations/draft",
                             json={"description": "Every weekday at 7 AM pull job costs"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # reviewable draft shape
        self.assertEqual(body["name"], GOOD_DRAFT["name"])
        self.assertEqual(len(body["steps"]), 2)
        self.assertTrue(body["needsSignoff"])
        self.assertEqual(body["state"], "awaiting_approval")
        # no-auto-activate: nothing persisted anywhere, nothing running
        self.assertEqual(self._automations_count(), 0)

    def test_draft_dispatches_through_the_configured_model_executor(self):
        import json
        self.scripted.output = json.dumps(GOOD_DRAFT)
        self.client.post("/api/automations/draft",
                         json={"description": "Weekly vendor check", "source_text": "Step one. Step two.",
                               "source_name": "vendor-runbook.md"})
        prompt = self.scripted.last_prompt or ""
        # strict JSON-only instruction + the uploaded doc content both present
        self.assertIn("JSON ONLY", prompt)
        self.assertIn("Weekly vendor check", prompt)
        self.assertIn("BEGIN vendor-runbook.md", prompt)
        self.assertIn("Step one. Step two.", prompt)

    def test_draft_rejects_malformed_model_json_with_502(self):
        import json
        bad_outputs = (
            "not json at all",
            '{"name": "", "steps": [{"text": "x"}]}',
            json.dumps({**GOOD_DRAFT, "trigger": {"kind": "whenever"}}),
            json.dumps({**GOOD_DRAFT, "steps": []}),
            json.dumps({**GOOD_DRAFT, "steps": [{"text": ""}]}),
        )
        for bad in bad_outputs:
            self.scripted.output = bad
            r = self.client.post("/api/automations/draft", json={"description": "d"})
            self.assertEqual(r.status_code, 502, f"expected 502 for {bad!r}")

    def test_draft_tolerates_markdown_fences_but_still_validates(self):
        import json
        fenced = f"```json\n{json.dumps(GOOD_DRAFT)}\n```"
        self.scripted.output = fenced
        r = self.client.post("/api/automations/draft", json={"description": "d"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["name"], GOOD_DRAFT["name"])

    def test_draft_requires_description(self):
        r = self.client.post("/api/automations/draft", json={"description": "   "})
        self.assertEqual(r.status_code, 400)


class TestParseAutomationDraft(unittest.TestCase):
    def test_normalizes_and_fills_defaults(self):
        out = '{"name": " N ", "trigger": null, "steps": [{"text": "do it"}, {"text": "sign off", "assignee": "human"}]}'
        d = parse_automation_draft(out)
        self.assertEqual(d["name"], "N")
        self.assertEqual(d["plain"], "")
        self.assertEqual(d["trigger"], {"kind": None, "display": None, "expr": None})
        self.assertEqual(d["steps"][1], {"text": "sign off", "assignee": "human"})
        # unknown assignees are coerced to agent-side default, not trusted
        self.assertEqual(parse_automation_draft(
            '{"name": "x", "steps": [{"text": "t", "assignee": "nobody"}]}')["steps"][0]["assignee"], None)

    def test_rejects_garbage(self):
        for bad in ("", "[]", "{}", "no braces here",
                    '{"name": "x"}',  # no steps
                    '{"name": "x", "steps": ["not an object"]}',
                    '{"steps": [{"text": "t"}]}'):  # no name
            with self.assertRaises(ValueError, msg=bad):
                parse_automation_draft(bad)

    def test_prompt_is_strict_json_only(self):
        p = build_draft_prompt("describe it in plain english", source_text="doc body", source_name="runbook.md")
        self.assertIn("JSON ONLY", p)
        self.assertIn("READ-ONLY DRAFTING", p)
        self.assertIn("runbook.md", p)


if __name__ == "__main__":
    unittest.main()
