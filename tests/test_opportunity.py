import os
import sqlite3
import tempfile
import unittest

from anton import opportunity
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.executor.base import Executor, RunResult
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


class WritingScanExecutor(Executor):
    """Deterministic double: writes conforming opportunity notes on every
    call, regardless of prompt content."""

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


if __name__ == "__main__":
    unittest.main()
