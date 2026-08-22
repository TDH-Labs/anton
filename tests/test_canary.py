import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from anton.canary import attempt_repairs, compute_tripwires, register_repair_recipe
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
        trip = {"job_id": "some-other-job", "last_seen": None, "expected_min": 5,
               "status": "tripwire"}
        outcomes = attempt_repairs(self.engine, [trip])
        self.assertEqual(outcomes, [{"job_id": "some-other-job", "action": "no_recipe"}])

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
