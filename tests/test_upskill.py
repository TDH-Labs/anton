import datetime as dt
import os
import sqlite3
import tempfile
import unittest

def dt_datetime_utcnow_str():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
from unittest.mock import patch

from anton import upskill
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


def _write_research_note(research_dir, subject_slug, source_type, n, *, valid=True):
    os.makedirs(research_dir, exist_ok=True)
    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(research_dir, f"{date}-{subject_slug}-{source_type}-{n}.md")
    if valid:
        text = (
            "---\n"
            "type: research\n"
            f"subject: {subject_slug}\n"
            f"source_type: {source_type}\n"
            "source_title: Example Source\n"
            "source_ref: https://example.com/source\n"
            f"captured: {dt.datetime.now(dt.timezone.utc).isoformat()}\n"
            "---\n\n"
            "## Key claims\nSomething.\n\n## Edge cases\nSomething else.\n\n"
            "## Anti-patterns\nDon't do X.\n"
        )
    else:
        text = "not frontmatter at all"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestVerifyResearch(unittest.TestCase):
    def test_counts_conforming_notes_across_types(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            rdir = os.path.join(vault_dir, "notes", "research", "widgets")
            _write_research_note(rdir, "widgets", "TRADES", 1)
            _write_research_note(rdir, "widgets", "TRADES", 2)
            _write_research_note(rdir, "widgets", "INTERVIEW", 1)
            _write_research_note(rdir, "widgets", "BOOK", 1)
            _write_research_note(rdir, "widgets", "WEB", 1)
            report = upskill.verify_research(vault_dir, "widgets")
            self.assertTrue(report.sufficient)
            self.assertEqual(len(report.sources), 5)
            self.assertEqual(len(report.by_type), 4)

    def test_five_sources_one_type_is_insufficient(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            rdir = os.path.join(vault_dir, "notes", "research", "widgets")
            for n in range(1, 6):
                _write_research_note(rdir, "widgets", "WEB", n)
            report = upskill.verify_research(vault_dir, "widgets")
            self.assertFalse(report.sufficient)
            self.assertIn("source types", " ".join(report.reasons))

    def test_four_sources_three_types_is_insufficient(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            rdir = os.path.join(vault_dir, "notes", "research", "widgets")
            _write_research_note(rdir, "widgets", "TRADES", 1)
            _write_research_note(rdir, "widgets", "INTERVIEW", 1)
            _write_research_note(rdir, "widgets", "BOOK", 1)
            _write_research_note(rdir, "widgets", "WEB", 1)
            report = upskill.verify_research(vault_dir, "widgets")
            self.assertFalse(report.sufficient)
            self.assertIn("5 sources", " ".join(report.reasons))

    def test_malformed_frontmatter_not_counted(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            rdir = os.path.join(vault_dir, "notes", "research", "widgets")
            _write_research_note(rdir, "widgets", "WEB", 1, valid=False)
            report = upskill.verify_research(vault_dir, "widgets")
            self.assertEqual(len(report.sources), 0)


class WritingExecutor(FakeExecutor):
    """Deterministic double: writes conforming research notes + a valid
    distilled skill on every call, regardless of prompt content -- exercises
    the sufficient-research path without depending on prompt parsing.
    Subclasses FakeExecutor (not the bare Executor base) so _dispatch's
    provider-prerequisite gate exempts it, same as scheduler.py's job-gate
    already exempts FakeExecutor -- there is no real provider behind it by
    construction."""

    def __init__(self, research_dir: str, out_dir: str, slug: str):
        self.research_dir = research_dir
        self.out_dir = out_dir
        self.slug = slug
        self.calls = 0

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        self.calls += 1
        for i, t in enumerate(("TRADES", "INTERVIEW", "BOOK", "WEB", "WEB"), start=1):
            _write_research_note(self.research_dir, self.slug, t, i)
        os.makedirs(os.path.join(self.out_dir, "scripts"), exist_ok=True)
        with open(os.path.join(self.out_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                f"---\nname: {self.slug}\ndescription: test skill\n---\n\n"
                "# Test\n\n## Do\nx\n\n## Don't\ny\n\n## Measure\nz\n\n## Validation\nw\n"
            )
        script = os.path.join(self.out_dir, "scripts", f"{self.slug}_evaluator.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import sys\n"
                "def evaluate(x):\n    return x > 0.5\n\n"
                "if __name__ == '__main__':\n"
                "    if len(sys.argv) > 1 and sys.argv[1] == '--selftest':\n"
                "        assert evaluate(0.9) is True\n"
                "        assert evaluate(0.1) is False\n"
                "        sys.exit(0)\n"
                "    sys.exit(0)\n"
            )
        return RunResult(exit_code=0, output="ok", stderr="", duration_ms=1,
                         model=model, provider=provider)


class UpskillTestBase(unittest.TestCase):
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

    def _initiatives(self):
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        rows = conn.execute("SELECT slug, source, status FROM initiatives").fetchall()
        conn.close()
        return rows


class TestDispatchProviderPrerequisiteGate(UpskillTestBase):
    """_dispatch() (upskill.py) is the single funnel all three of
    run_upskill's/consolidate_skill's real-executor calls go through --
    every one of them sits behind meta_learning.process_pending_candidates,
    which the scheduler poll loop calls every tick. Before this gate, a
    fresh install with no provider configured hit the real executor
    max_research_attempts times per run_upskill call, every poll tick for
    as long as the candidate stayed eligible: the same fabricated-failure
    spam scheduler.py's run_job and opportunity.py's scan_for_opportunities
    were fixed for, in a third place those fixes missed."""

    def setUp(self):
        super().setUp()

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
        result = upskill.run_upskill(self.engine, "widget repair", max_research_attempts=3)
        self.assertEqual(result.status, "insufficient_research")
        rows = self.ledger.read()
        skips = [r for r in rows if r["task"] == "upskill:widget-repair:research"]
        # bounded by dedup, not by max_research_attempts: the loop calls
        # _dispatch 3 times, but only the first records a row.
        self.assertEqual(len(skips), 1)
        self.assertIn("skipped:no-provider", skips[0]["flags"])
        self.assertEqual(skips[0]["exit"], 6)

    def test_skipped_attempt_is_not_recorded_in_upskill_runs(self):
        upskill.run_upskill(self.engine, "widget repair", max_research_attempts=2)
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        attempts = conn.execute(
            "SELECT COUNT(*) FROM upskill_runs WHERE stage='research'").fetchone()[0]
        conn.close()
        self.assertEqual(attempts, 0)

    def test_skip_does_not_spawn_a_stuck_remediation_initiative(self):
        # delta.py's scan_ledger_failures must not treat this skip as a
        # failure (see test_delta.py's dedicated coverage) -- cross-checked
        # here end-to-end through the real upskill.py code path.
        from anton.delta import scan_ledger_failures
        upskill.run_upskill(self.engine, "widget repair", max_research_attempts=1)
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        try:
            self.assertEqual(scan_ledger_failures(self.ledger, conn), [])
        finally:
            conn.close()


class TestRunUpskillInsufficientResearch(UpskillTestBase):
    def test_fake_executor_never_promotes_a_skill(self):
        # FakeExecutor writes nothing to disk -- this deterministically
        # exercises the bounded-retry-then-block path (requirement: never
        # derive a skill from insufficient research).
        result = upskill.run_upskill(self.engine, "widget repair", max_research_attempts=2)
        self.assertEqual(result.status, "insufficient_research")
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "skills", result.slug)))
        rows = self._initiatives()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], f"upskill-{result.slug}")

    def test_retries_are_bounded_and_recorded(self):
        upskill.run_upskill(self.engine, "widget repair", max_research_attempts=2)
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        attempts = conn.execute(
            "SELECT COUNT(*) FROM upskill_runs WHERE stage='research'").fetchone()[0]
        conn.close()
        self.assertEqual(attempts, 2)


class TestRunUpskillSufficientResearch(UpskillTestBase):
    def test_promotes_when_research_and_sandbox_gate_pass(self):
        slug = upskill.slugify("widget repair")
        research_dir = os.path.join(self.data_dir, "vault", "notes", "research", slug)
        out_dir = os.path.join(self.data_dir, "staging", slug)
        self.engine.executor = WritingExecutor(research_dir, out_dir, slug)
        result = upskill.run_upskill(self.engine, "widget repair")
        self.assertEqual(result.status, "promoted")
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "skills", slug, "SKILL.md")))
        self.assertTrue(os.path.exists(
            os.path.join(self.data_dir, "skills", slug, f"{slug}_evaluator.py")))

    def test_promotion_requires_governor_approval_when_not_low_risk(self):
        slug = upskill.slugify("widget repair")
        research_dir = os.path.join(self.data_dir, "vault", "notes", "research", slug)
        out_dir = os.path.join(self.data_dir, "staging", slug)
        self.engine.executor = WritingExecutor(research_dir, out_dir, slug)
        with patch.dict(upskill._PROMOTION_RISK_PROFILE, {"risk": "high"}):
            result = upskill.run_upskill(self.engine, "widget repair")
        self.assertEqual(result.status, "pending_approval")
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "skills", slug)))
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        row = conn.execute(
            "SELECT status FROM approvals WHERE action=?", (f"upskill_promote:{slug}",)).fetchone()
        conn.close()
        self.assertEqual(row[0], "pending")

    def test_approve_pending_promotion_completes_it(self):
        slug = upskill.slugify("widget repair")
        research_dir = os.path.join(self.data_dir, "vault", "notes", "research", slug)
        out_dir = os.path.join(self.data_dir, "staging", slug)
        self.engine.executor = WritingExecutor(research_dir, out_dir, slug)
        with patch.dict(upskill._PROMOTION_RISK_PROFILE, {"risk": "high"}):
            upskill.run_upskill(self.engine, "widget repair")
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        conn.execute("UPDATE approvals SET status='approved', approver_human='owner', "
                     "approver_principal='owner', decided_at=? WHERE action=?",
                     (dt_datetime_utcnow_str(), f"upskill_promote:{slug}"))
        conn.commit()
        conn.close()
        ok = upskill.approve_pending_promotion(self.engine, slug)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "skills", slug, "SKILL.md")))


class TestConsolidateSkill(UpskillTestBase):
    def test_does_nothing_below_threshold(self):
        did = upskill.consolidate_skill(self.engine, "some-skill", threshold=3)
        self.assertFalse(did)

    def test_consolidates_and_marks_lessons_consumed_at_threshold(self):
        from anton.learning import record_lesson, unconsumed_lessons
        db_path = os.path.join(self.data_dir, "isolation.db")
        skill_dir = os.path.join(self.data_dir, "skills", "some-skill")
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: some-skill\n---\n\n## Do\nx\n\n## Don't\ny\n")
        for i in range(3):
            record_lesson(db_path, "some-skill", "dont", f"lesson {i}", source="test")
        did = upskill.consolidate_skill(self.engine, "some-skill", threshold=3)
        self.assertTrue(did)
        self.assertEqual(unconsumed_lessons(db_path, "some-skill"), [])


if __name__ == "__main__":
    unittest.main()
