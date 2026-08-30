import os
import sqlite3
import tempfile
import unittest

from anton import opportunity
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.executor.base import RunResult
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine
from anton.vault import provision_vault

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
"""


def _write_opportunity_note(opp_dir, subject, source, worth, n=1):
    os.makedirs(opp_dir, exist_ok=True)
    path = os.path.join(opp_dir, f"2026-01-01-{subject}-{n}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "---\n"
            "type: opportunity\n"
            f"subject: {subject}\n"
            f"source: {source}\n"
            f"worth: {worth}\n"
            "---\n\n"
            "## What was observed\nsomething\n\n"
            "## Why this is worth pursuing\nreasons\n\n"
            "## What competence would need to be built\nskill\n"
        )
    return path


class WritingScanExecutor(FakeExecutor):
    """Deterministic double: writes conforming opportunity notes on every
    call, regardless of prompt content. Subclasses FakeExecutor (not the
    bare Executor base) so scan_for_opportunities' provider-prerequisite
    gate exempts it the same way it exempts FakeExecutor itself -- there is
    no real provider behind it by construction, same as the scheduler's own
    job-dispatch gate already treats FakeExecutor."""

    def __init__(self, opp_dir: str, findings):
        self.opp_dir = opp_dir
        self.findings = findings  # list of (subject, source, worth)
        self.calls = 0

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        self.calls += 1
        for i, (subject, source, worth) in enumerate(self.findings, start=1):
            _write_opportunity_note(self.opp_dir, subject, source, worth, n=i)
        return RunResult(exit_code=0, output="ok", stderr="", duration_ms=1,
                         model=model, provider=provider)


class OpportunityTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = self.dir.name
        init_db(os.path.join(self.data_dir, "isolation.db"))
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        provision_vault(os.path.join(self.data_dir, "vault"))
        self.ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(),
                                load_config(), data_dir=self.data_dir)

    def tearDown(self):
        self.dir.cleanup()


class TestListConnectedSources(OpportunityTestBase):
    def test_vault_always_present_even_with_no_db(self):
        sources = opportunity.list_connected_sources(self.data_dir)
        names = [s["name"] for s in sources]
        self.assertIn("vault", names)

    def test_includes_active_mcp_servers_not_inactive(self):
        db_path = os.path.join(self.data_dir, "isolation.db")
        conn = sqlite3.connect(db_path)
        conn.execute(opportunity._MCP_SERVERS_SCHEMA)
        conn.execute(
            "INSERT INTO mcp_servers(id, name, what, status) VALUES (?,?,?,?)",
            ("qbo", "quickbooks", "accounting data", "active"))
        conn.execute(
            "INSERT INTO mcp_servers(id, name, what, status) VALUES (?,?,?,?)",
            ("old", "retired-tool", "unused", "inactive"))
        conn.commit()
        conn.close()
        sources = opportunity.list_connected_sources(self.data_dir)
        names = [s["name"] for s in sources]
        self.assertIn("quickbooks", names)
        self.assertNotIn("retired-tool", names)

    def test_config_declared_extra_sources_are_listed(self):
        # The operator's own information sources -- sessions with other
        # agents, prompts, bounded disk roots -- are expressible via config
        # and surface in the scan source list with their path.
        cfg = {"general": {"opportunity_extra_sources": [
            {"name": "agent-sessions",
             "what": "transcripts of sessions with other agents",
             "path": "/tmp/sessions"},
            {"name": "notes-dir", "what": "bounded disk root"},
        ]}}
        sources = opportunity.list_connected_sources(self.data_dir, cfg)
        by_name = {s["name"]: s for s in sources}
        self.assertIn("agent-sessions", by_name)
        self.assertEqual(by_name["agent-sessions"]["path"], "/tmp/sessions")
        self.assertIn("notes-dir", by_name)

    def test_malformed_extra_sources_are_skipped(self):
        cfg = {"general": {"opportunity_extra_sources": [
            {"name": "", "what": "nameless"},
            "not-a-dict",
        ]}}
        sources = opportunity.list_connected_sources(self.data_dir, cfg)
        self.assertEqual([s["name"] for s in sources], ["vault"])


class TestVerifyOpportunities(OpportunityTestBase):
    def test_no_dir_returns_empty(self):
        vault_dir = os.path.join(self.data_dir, "vault")
        self.assertEqual(opportunity.verify_opportunities(vault_dir), [])

    def test_parses_conforming_notes(self):
        vault_dir = os.path.join(self.data_dir, "vault")
        opp_dir = os.path.join(vault_dir, "notes", "opportunities")
        _write_opportunity_note(opp_dir, "widget-resale", "email", "high")
        found = opportunity.verify_opportunities(vault_dir)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].subject, "widget-resale")
        self.assertEqual(found[0].worth, "high")

    def test_malformed_or_wrong_type_not_counted(self):
        vault_dir = os.path.join(self.data_dir, "vault")
        opp_dir = os.path.join(vault_dir, "notes", "opportunities")
        os.makedirs(opp_dir, exist_ok=True)
        with open(os.path.join(opp_dir, "junk.md"), "w", encoding="utf-8") as f:
            f.write("not frontmatter")
        with open(os.path.join(opp_dir, "wrong-type.md"), "w", encoding="utf-8") as f:
            f.write("---\ntype: research\nsubject: x\nworth: high\n---\n")
        with open(os.path.join(opp_dir, "bad-worth.md"), "w", encoding="utf-8") as f:
            f.write("---\ntype: opportunity\nsubject: x\nworth: extreme\n---\n")
        self.assertEqual(opportunity.verify_opportunities(vault_dir), [])


class TestScanForOpportunities(OpportunityTestBase):
    def test_fake_executor_finds_nothing_not_a_crash(self):
        found = opportunity.scan_for_opportunities(self.engine)
        self.assertEqual(found, [])

    def test_qualifying_finding_emits_initiative_candidate(self):
        vault_dir = os.path.join(self.data_dir, "vault")
        opp_dir = os.path.join(vault_dir, "notes", "opportunities")
        self.engine.executor = WritingScanExecutor(
            opp_dir, [("widget-resale", "email", "high")])
        found = opportunity.scan_for_opportunities(self.engine)
        self.assertEqual(len(found), 1)
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        rows = conn.execute(
            "SELECT slug, status FROM initiatives WHERE slug LIKE 'opportunity-%'").fetchall()
        conn.close()
        self.assertEqual(rows, [("opportunity-widget-resale", "pending")])

    def test_below_min_worth_is_not_emitted(self):
        vault_dir = os.path.join(self.data_dir, "vault")
        opp_dir = os.path.join(vault_dir, "notes", "opportunities")
        self.engine.executor = WritingScanExecutor(
            opp_dir, [("minor-thing", "email", "low")])
        found = opportunity.scan_for_opportunities(self.engine, min_worth="high")
        self.assertEqual(found, [])

    def test_dispatch_is_ledger_and_budget_accounted(self):
        vault_dir = os.path.join(self.data_dir, "vault")
        opp_dir = os.path.join(vault_dir, "notes", "opportunities")
        self.engine.executor = WritingScanExecutor(opp_dir, [])
        opportunity.scan_for_opportunities(self.engine)
        rows = self.ledger.read()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task"], "opportunity:scan")


class TestScanProviderPrerequisiteGate(OpportunityTestBase):
    """A fresh install with no AI provider configured used to hit real
    dispatch here unconditionally and record 'opportunity:scan (exit 1)'
    within seconds of first boot -- one poll tick after the container
    starts, since _opportunity_scan_due() is true the moment
    last-opportunity-scan has never been written. This is the same
    fabricated-failure-as-work pattern run_job()'s _provider_block was
    built to eliminate (see TestProviderPrerequisiteGate in
    test_scheduler.py); scan_for_opportunities must apply the identical
    gate instead of running a second, ungated path to the same executor."""

    def setUp(self):
        super().setUp()
        from anton.executor.base import Executor

        class StubRealExecutor(Executor):
            def available(self):
                return True
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                raise AssertionError("executor.run must never be reached when blocked")
        self.engine.executor = StubRealExecutor()
        self._old_key = os.environ.pop("OPENROUTER_API_KEY", None)

    def tearDown(self):
        if self._old_key is not None:
            os.environ["OPENROUTER_API_KEY"] = self._old_key
        super().tearDown()

    def test_missing_cloud_key_skips_instead_of_dispatching(self):
        found = opportunity.scan_for_opportunities(self.engine)
        self.assertEqual(found, [])
        rows = self.ledger.read()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task"], "opportunity:scan")
        self.assertIn(opportunity.SKIP_FLAG, rows[0]["flags"])
        self.assertEqual(rows[0]["exit"], 6)

    def test_skip_is_recorded_once_not_every_call(self):
        opportunity.scan_for_opportunities(self.engine)
        opportunity.scan_for_opportunities(self.engine)
        rows = self.ledger.read()
        self.assertEqual(len(rows), 1)


class TestScanGateChecksActualDispatchTarget(OpportunityTestBase):
    """The gate used to check select_route(prefer="cloud")'s hardcoded
    default (openrouter/claude-3.5-sonnet) even when a caller-supplied
    model=/provider= override -- or the deployment's own configured
    routes.cloud_model -- meant something else entirely would actually be
    dispatched. That let it both false-skip a fully-available override
    (blocking on a key the deployment never needed) and false-pass an
    unavailable one (letting a doomed dispatch through because the
    *default*'s key happened to be set)."""

    def setUp(self):
        super().setUp()
        self._old_openrouter = os.environ.pop("OPENROUTER_API_KEY", None)
        self._old_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        for k, v in (("OPENROUTER_API_KEY", self._old_openrouter),
                    ("ANTHROPIC_API_KEY", self._old_anthropic)):
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        super().tearDown()

    def test_override_to_an_available_provider_is_not_blocked_by_the_default(self):
        # only ANTHROPIC_API_KEY is set -- the module default (openrouter)
        # has no key, but that's not what's being requested.
        os.environ["ANTHROPIC_API_KEY"] = "sk-test"
        vault_dir = os.path.join(self.data_dir, "vault")
        opp_dir = os.path.join(vault_dir, "notes", "opportunities")
        executor = WritingScanExecutor(opp_dir, [])
        self.engine.executor = executor
        opportunity.scan_for_opportunities(
            self.engine, model="anthropic/claude-3-opus", provider="anthropic")
        self.assertEqual(executor.calls, 1)
        rows = self.ledger.read()
        self.assertEqual(len(rows), 1)
        self.assertNotIn(opportunity.SKIP_FLAG, rows[0]["flags"])

    def test_override_to_an_unavailable_provider_is_blocked_not_the_default(self):
        # OPENROUTER_API_KEY (the default route's key) IS set, but the
        # override requests anthropic, which is not.
        os.environ["OPENROUTER_API_KEY"] = "sk-test"
        from anton.executor.base import Executor

        class StubRealExecutor(Executor):
            def available(self):
                return True
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                raise AssertionError("must not dispatch to the unavailable override")
        self.engine.executor = StubRealExecutor()
        found = opportunity.scan_for_opportunities(
            self.engine, model="anthropic/claude-3-opus", provider="anthropic")
        self.assertEqual(found, [])
        rows = self.ledger.read()
        self.assertIn(opportunity.SKIP_FLAG, rows[0]["flags"])
        self.assertIn("ANTHROPIC_API_KEY", rows[0]["output"])


if __name__ == "__main__":
    unittest.main()
