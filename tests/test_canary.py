import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from anton.canary import (REPAIR_RECIPES, attempt_repairs, compute_tripwires,
                          register_repair_recipe)
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import Job, load_jobs
from anton.ledger import Ledger
from anton.models import RunRecord
from anton.scheduler import JobEngine

NOW = dt.datetime(2026, 8, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
NOW_ISO = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestCanary(unittest.TestCase):
    def test_never_ran_trips(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "runs.jsonl"))
            job = Job(id="cos-maintenance-sweep", trigger={"type": "cron", "expr": "0 7 * * *"},
                      recipe="x", expected_cadence_min=1440)
            trips = compute_tripwires([job], led, now=NOW)
            self.assertEqual(len(trips), 1)
            self.assertEqual(trips[0]["status"], "tripwire")

    def test_recent_run_ok(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "runs.jsonl"))
            led.append(RunRecord.new(task="e2e-canary", exit_code=0))
            job = Job(id="e2e-canary", trigger={"type": "cron", "expr": "*/5 * * * *"},
                      recipe="x", expected_cadence_min=5)
            self.assertEqual(compute_tripwires([job], led, now=NOW), [])

    def test_stale_run_trips(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "runs.jsonl"))
            old = NOW - dt.timedelta(days=5)
            led.append(RunRecord.new(task="sweep", exit_code=0))
            rows = led.read()
            rows[-1]["ts"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(led.path, "w") as f:
                import json
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            job = Job(id="sweep", trigger={"type": "cron", "expr": "0 0 * * *"},
                      recipe="x", expected_cadence_min=1440)
            trips = compute_tripwires([job], led, now=NOW)
            self.assertEqual(len(trips), 1)
            self.assertGreater(trips[0]["age_min"], 2 * 1440)


class TestAttemptRepairs(unittest.TestCase):
    JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        init_db(os.path.join(self.dir.name, "isolation.db"))
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(self.JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger,
                                FakeExecutor(), load_config(), data_dir=self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def _initiatives(self):
        conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        rows = conn.execute("SELECT slug, source, status FROM initiatives").fetchall()
        conn.close()
        return rows

    def test_mapped_recipe_auto_repairs_and_clears_the_tripwire(self):
        # e2e-canary is in REPAIR_RECIPES as low-risk/high-EV -> auto_execute.
        trip = {"job_id": "e2e-canary", "last_seen": None, "expected_min": 5,
               "status": "tripwire"}
        outcomes = attempt_repairs(self.engine, [trip])
        self.assertEqual(outcomes, [{"job_id": "e2e-canary", "action": "auto_repaired",
                                     "exit_code": 0, "route": "auto_execute"}])
        # run_job() re-recorded last_run: the tripwire is gone on the next check.
        self.assertEqual(compute_tripwires(self.engine.jobs, self.ledger,
                                           now=dt.datetime.now(dt.timezone.utc)), [])
        self.assertEqual(self._initiatives(), [])  # no candidate needed — it auto-repaired

    def test_unmapped_job_records_no_recipe_not_silence(self):
        # A real job (registered in jobs.yaml) with no entry in
        # REPAIR_RECIPES -- distinct from a job that no longer exists at
        # all, which is job_missing below. The engine has to resolve the Job
        # object regardless (to check whether it is n8n-backed), so the two
        # cases must be told apart by whether by_id() actually returns
        # something, not by which check happens to run first. A dedicated
        # engine/jobs.yaml, not self.engine: adding this job to the shared
        # fixture would make it a second tripwire in every other test in
        # this class (expected_cadence_min: 5, never run).
        with tempfile.TemporaryDirectory() as d:
            init_db(os.path.join(d, "isolation.db"))
            jobs_path = os.path.join(d, "jobs.yaml")
            with open(jobs_path, "w", encoding="utf-8") as f:
                f.write("- id: unmapped-job\n  trigger: { type: cron, expr: \"*/5 * * * *\" }\n"
                        "  recipe: x\n  expected_cadence_min: 5\n")
            engine = JobEngine(load_jobs(jobs_path), Ledger(os.path.join(d, "runs.jsonl")),
                               FakeExecutor(), load_config(), data_dir=d)
            trip = {"job_id": "unmapped-job", "last_seen": None, "expected_min": 5,
                   "status": "tripwire"}
            outcomes = attempt_repairs(engine, [trip])
        self.assertEqual(outcomes, [{"job_id": "unmapped-job", "action": "no_recipe"}])

    def test_deleted_job_records_job_missing_not_no_recipe(self):
        trip = {"job_id": "never-existed", "last_seen": None, "expected_min": 5,
               "status": "tripwire"}
        outcomes = attempt_repairs(self.engine, [trip])
        self.assertEqual(outcomes, [{"job_id": "never-existed", "action": "job_missing"}])

    def test_high_risk_recipe_records_a_pending_candidate_not_silence(self):
        register_repair_recipe("e2e-canary", ev=0.9, feasibility=0.9, risk="high", kind="internal")
        self.addCleanup(register_repair_recipe, "e2e-canary", ev=0.9, feasibility=0.9,
                        risk="low", kind="internal")
        trip = {"job_id": "e2e-canary", "last_seen": None, "expected_min": 5,
               "status": "tripwire"}
        outcomes = attempt_repairs(self.engine, [trip])
        self.assertEqual(outcomes[0]["job_id"], "e2e-canary")
        self.assertEqual(outcomes[0]["action"], "pending_approval")
        rows = self._initiatives()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "repair_e2e-canary")
        self.assertEqual(rows[0][2], "pending")

    def test_repeated_polls_do_not_spam_duplicate_candidates(self):
        register_repair_recipe("e2e-canary", ev=0.9, feasibility=0.9, risk="high", kind="internal")
        self.addCleanup(register_repair_recipe, "e2e-canary", ev=0.9, feasibility=0.9,
                        risk="low", kind="internal")
        trip = {"job_id": "e2e-canary", "last_seen": None, "expected_min": 5,
               "status": "tripwire"}
        attempt_repairs(self.engine, [trip])
        attempt_repairs(self.engine, [trip])
        attempt_repairs(self.engine, [trip])
        self.assertEqual(len(self._initiatives()), 1)


class TestN8nUnreachableDiagnosis(unittest.TestCase):
    """A tripwired job backed by N8NExecutor gets a DIAGNOSIS step before any
    repair decision: re-running is meaningless if the n8n instance itself is
    down, and worse, could mislabel a real outage as 'auto_repaired' the
    moment an unrelated retry happened to land after n8n came back on its
    own. N8NExecutor.available() is patched at the class level rather than
    given a fake transport, because the object under test here is
    attempt_repairs()'s branching, not N8NExecutor's own HTTP behavior
    (already covered in tests/test_n8n_executor.py)."""

    JOBS = """
- id: reconcile-payments
  trigger: { type: cron, expr: "0 7 * * *" }
  recipe: reconcile
  expected_cadence_min: 60
  model_route: cloud
  executor: { name: n8n, webhook_url: "http://n8n.example/webhook/reconcile" }
"""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        init_db(os.path.join(self.dir.name, "isolation.db"))
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(self.JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger,
                                FakeExecutor(), load_config(), data_dir=self.dir.name)
        self.trip = {"job_id": "reconcile-payments", "last_seen": None,
                    "expected_min": 60, "status": "tripwire"}

    def tearDown(self):
        self.dir.cleanup()

    def _initiatives(self):
        conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        rows = conn.execute("SELECT slug, source, status FROM initiatives").fetchall()
        conn.close()
        return rows

    def test_unreachable_n8n_is_diagnosed_not_blindly_repaired(self):
        from unittest.mock import patch
        from anton.executor.n8n_executor import N8NExecutor
        with patch.object(N8NExecutor, "available", return_value=False):
            outcomes = attempt_repairs(self.engine, [self.trip])
        self.assertEqual(outcomes, [{"job_id": "reconcile-payments",
                                     "action": "n8n_unreachable"}])
        rows = self._initiatives()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "repair_reconcile-payments")
        self.assertIn("n8n_unreachable", rows[0][1])
        self.assertEqual(rows[0][2], "pending")

    def test_unreachable_n8n_never_auto_executes_regardless_of_a_registered_recipe(self):
        # Even a job explicitly registered as safe-to-auto-repair must not
        # bypass the reachability diagnosis -- re-running a job whose target
        # is down cannot be a repair.
        register_repair_recipe("reconcile-payments", ev=0.95, feasibility=0.95,
                               risk="low", kind="internal")
        from unittest.mock import patch
        from anton.executor.n8n_executor import N8NExecutor
        with patch.object(N8NExecutor, "available", return_value=False):
            outcomes = attempt_repairs(self.engine, [self.trip])
        self.assertEqual(outcomes[0]["action"], "n8n_unreachable")

    def test_reachable_n8n_falls_through_to_the_ordinary_recipe_decision(self):
        # n8n is UP but the job still went quiet for some other reason
        # (cron never fired, a real prior failure) -- re-running is a
        # legitimate repair here, so this must reach the same
        # REPAIR_RECIPES-based path every other job uses.
        register_repair_recipe("reconcile-payments", ev=0.95, feasibility=0.95,
                               risk="low", kind="internal")
        self.addCleanup(lambda: REPAIR_RECIPES.pop("reconcile-payments", None))
        from unittest.mock import patch
        from anton.executor.base import RunResult
        from anton.executor.n8n_executor import N8NExecutor
        with patch.object(N8NExecutor, "available", return_value=True), \
             patch.object(N8NExecutor, "run",
                         return_value=RunResult(0, "ok", "", 1, "cloud/x", "cloud")):
            outcomes = attempt_repairs(self.engine, [self.trip])
        self.assertEqual(outcomes[0]["action"], "auto_repaired")
        self.assertEqual(self._initiatives(), [])

    def test_non_n8n_job_is_unaffected_by_the_new_check(self):
        # The diagnosis only applies to N8NExecutor-backed jobs; an
        # ordinary job with no `executor:` override must never call
        # N8NExecutor.available() at all.
        from unittest.mock import patch
        from anton.executor.n8n_executor import N8NExecutor
        jobs_path = os.path.join(self.dir.name, "other.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write("- id: plain-job\n  trigger: { type: cron, expr: \"*/5 * * * *\" }\n"
                    "  recipe: x\n  expected_cadence_min: 5\n")
        engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(),
                           load_config(), data_dir=self.dir.name)
        trip = {"job_id": "plain-job", "last_seen": None, "expected_min": 5,
               "status": "tripwire"}
        with patch.object(N8NExecutor, "available") as avail:
            outcomes = attempt_repairs(engine, [trip])
        avail.assert_not_called()
        self.assertEqual(outcomes, [{"job_id": "plain-job", "action": "no_recipe"}])
