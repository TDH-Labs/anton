import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anton import meta_learning, upskill
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.meta_skills import seed_meta_skills
from anton.models import RunRecord
from anton.scheduler import JobEngine

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
"""


class MetaLearningTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = self.dir.name
        init_db(os.path.join(self.data_dir, "isolation.db"))
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(),
                                load_config(), data_dir=self.data_dir)

    def tearDown(self):
        self.dir.cleanup()


class TestFindExistingSkill(MetaLearningTestBase):
    def test_exact_slug_match(self):
        seed_meta_skills(self.data_dir)
        self.assertEqual(meta_learning.find_existing_skill(self.data_dir, "upskill from research"),
                         "upskill-from-research")

    def test_no_match_returns_none(self):
        seed_meta_skills(self.data_dir)
        self.assertIsNone(meta_learning.find_existing_skill(self.data_dir, "totally unrelated widget"))

    def test_keyword_overlap_match(self):
        skill_dir = os.path.join(self.data_dir, "skills", "sage-invoice-reconciliation")
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: sage-invoice-reconciliation\ndescription: reconcile sage invoices\n---\n")
        from anton.learning import index_skills
        index_skills(self.data_dir)
        self.assertEqual(meta_learning.find_existing_skill(self.data_dir, "reconcile sage invoices"),
                         "sage-invoice-reconciliation")


class TestDecide(MetaLearningTestBase):
    def test_reuses_when_pool_already_has_it(self):
        seed_meta_skills(self.data_dir)
        d = meta_learning.decide(self.engine, "upskill from research")
        self.assertEqual(d.action, "reuse")

    def test_new_subject_routes_to_research(self):
        d = meta_learning.decide(self.engine, "brand new subject nobody knows")
        self.assertEqual(d.action, "learn_from_research")

    def test_repeated_failure_routes_to_experience(self):
        d = meta_learning.decide(self.engine, "widget-sync", is_repeated_failure=True)
        self.assertEqual(d.action, "learn_from_experience")

    def test_stops_when_already_pending_approval(self):
        slug = upskill.slugify("widget-sync")
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        conn.execute(
            "INSERT INTO approvals(nonce, action, amount, recipient, status, ts) "
            "VALUES (?,?,?,?,?,?)",
            ("n1", f"upskill_promote:{slug}", "", "", "pending", "2026-01-01T00:00:00Z"))
        conn.commit()
        conn.close()
        with patch("anton.meta_learning.dt") as mock_dt:
            import datetime as real_dt
            mock_dt.datetime.now.return_value = real_dt.datetime(2026, 1, 1, 1, 0, 0, tzinfo=real_dt.timezone.utc)
            mock_dt.timedelta = real_dt.timedelta
            d = meta_learning.decide(self.engine, "widget-sync")
        self.assertEqual(d.action, "stop")


class TestRoute(MetaLearningTestBase):
    def test_reuse_short_circuits_without_dispatching(self):
        seed_meta_skills(self.data_dir)
        result = meta_learning.route(self.engine, "upskill from research")
        self.assertEqual(result.status, "reused")
        # no new ledger rows -- nothing was dispatched
        self.assertEqual(self.ledger.read(), [])


class TestSequencePendingUpskills(MetaLearningTestBase):
    def test_orders_by_repeat_count_then_recency(self):
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        conn.executemany(
            "INSERT INTO initiatives(slug, source, status, ts) VALUES (?,?,?,?)",
            [
                ("upskill-a", "ledger:a:repeated_failures:2", "pending", "2026-01-01T00:00:00Z"),
                ("upskill-b", "ledger:b:repeated_failures:5", "pending", "2026-01-02T00:00:00Z"),
                ("upskill-c", "ledger:c:repeated_failures:2", "pending", "2026-01-01T00:00:01Z"),
            ])
        conn.commit()
        conn.close()
        ordered = meta_learning.sequence_pending_upskills(self.engine)
        # b has the most repeats -> first; a and c tie on repeats -> older ts first
        self.assertEqual(ordered, ["upskill-b", "upskill-a", "upskill-c"])


class TestSequencePendingOpportunities(MetaLearningTestBase):
    def test_orders_by_worth_then_recency(self):
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        conn.executemany(
            "INSERT INTO initiatives(slug, source, status, ts) VALUES (?,?,?,?)",
            [
                ("opportunity-a", "scan:email:worth=medium", "pending", "2026-01-01T00:00:00Z"),
                ("opportunity-b", "scan:qbo:worth=high", "pending", "2026-01-02T00:00:00Z"),
                ("opportunity-c", "scan:drive:worth=medium", "pending", "2026-01-01T00:00:01Z"),
            ])
        conn.commit()
        conn.close()
        ordered = meta_learning.sequence_pending_opportunities(self.engine)
        self.assertEqual(ordered, ["opportunity-b", "opportunity-a", "opportunity-c"])


class TestProcessPendingOpportunities(MetaLearningTestBase):
    def setUp(self):
        super().setUp()
        # Default is now autonomous (upskill._DISPATCH_RISK_PROFILE
        # ev 0.9/fe 0.9/risk low -> AUTO_EXECUTE) -- the earlier
        # conservative default was reversed by explicit operator
        # direction (Anton should upskill+execute without prompting).
        # The force is still explicit here so the test is deterministic
        # regardless of future default drift.
        upskill.set_dispatch_risk_profile(ev=0.9, feasibility=0.9, risk="low")

    def tearDown(self):
        upskill.set_dispatch_risk_profile(ev=0.9, feasibility=0.9, risk="low")
        super().tearDown()

    def test_reuses_existing_skill_without_dispatch(self):
        seed_meta_skills(self.data_dir)
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        conn.execute(
            "INSERT INTO initiatives(slug, source, status, ts) VALUES (?,?,?,?)",
            ("opportunity-upskill-from-research", "scan:vault:worth=high", "pending",
             "2026-01-01T00:00:00Z"))
        conn.commit()
        conn.close()
        outcomes = meta_learning.process_pending_opportunities(self.engine)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["action"], "dispatched")
        self.assertEqual(outcomes[0]["status"], "reused")
        # reuse short-circuits before any research dispatch -- no ledger rows
        self.assertEqual(self.ledger.read(), [])

    def test_default_dispatch_profile_is_autonomous_but_self_bound(self):
        """Operator direction: Anton upskills+executes without prompting.
        The automatic dispatch profile clears auto_execute for internal
        work, but the governor hard-gates money/outbound regardless of
        how high the score is -- autonomy is bounded, not unbounded."""
        from anton.governor import AUTO_EXECUTE, PRESENT_FOR_APPROVAL, classify
        r = classify(0.9, 0.9, risk="low", kind="internal")
        self.assertEqual(r.route, AUTO_EXECUTE)
        for kind in ("money", "outbound"):
            r_kind = classify(0.9, 0.9, risk="low", kind=kind)
            self.assertEqual(r_kind.route, PRESENT_FOR_APPROVAL)

class TestTriageSkillPortfolio(MetaLearningTestBase):
    def _make_skill(self, slug):
        d = os.path.join(self.data_dir, "skills", slug)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(f"---\nname: {slug}\ndescription: test\n---\n")
        from anton.learning import index_skills
        index_skills(self.data_dir)

    def test_archives_unused_skill(self):
        self._make_skill("dormant-skill")
        report = meta_learning.triage_skill_portfolio(self.engine, stale_days=90)
        self.assertIn("dormant-skill", report.archived)
        self.assertFalse(os.path.exists(os.path.join(self.data_dir, "skills", "dormant-skill")))
        self.assertTrue(os.path.exists(
            os.path.join(self.data_dir, "skills-archive", "dormant-skill", "SKILL.md")))

    def test_keeps_recently_applied_skill(self):
        self._make_skill("active-skill")
        self.ledger.append(RunRecord.new(task="active-skill:apply", exit_code=0))
        report = meta_learning.triage_skill_portfolio(self.engine, stale_days=90)
        self.assertIn("active-skill", report.active)
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "skills", "active-skill")))

    def test_never_archives_the_standard_meta_skills(self):
        seed_meta_skills(self.data_dir)
        report = meta_learning.triage_skill_portfolio(self.engine, stale_days=0)
        self.assertNotIn("upskill-from-research", report.archived)
        self.assertNotIn("upskill-from-experience", report.archived)
        self.assertNotIn("meta-learning", report.archived)


if __name__ == "__main__":
    unittest.main()
