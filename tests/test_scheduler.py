import datetime as dt
import os
import tempfile
import unittest
from harbor.executor import FakeExecutor
from harbor.jobs import load_jobs
from harbor.ledger import Ledger
from harbor.scheduler import JobEngine
from harbor.config import load_config

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
- id: sweep
  trigger: { type: cron, expr: "0 0 * * *" }
  recipe: sweep-recipe
  verify: "grep -q NEVER_MARKER <output>"
  expected_cadence_min: 1440
"""


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(self.jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                                FakeExecutor(), load_config())

    def tearDown(self):
        self.dir.cleanup()

    def test_due_jobs_fires_on_matching_minute(self):
        now = dt.datetime(2026, 8, 18, 10, 10, 0, tzinfo=dt.timezone.utc)  # */5 matches :10
        due = self.engine.due_jobs(now)
        ids = {j.id for j in due}
        self.assertIn("e2e-canary", ids)
        self.assertNotIn("sweep", ids)

    def test_due_jobs_idempotent_within_minute(self):
        now = dt.datetime(2026, 8, 18, 10, 10, 0, tzinfo=dt.timezone.utc)
        job = self.engine.by_id("e2e-canary")
        self.engine.run_job(job, now=now)
        # after running this minute, it must not be due again until the next matching minute
        self.assertEqual(self.engine.due_jobs(now), [])

    def test_run_job_records_r9(self):
        job = self.engine.by_id("e2e-canary")
        rec = self.engine.run_job(job)
        self.assertEqual(rec.exit, 0)
        row = self.ledger.last_run("e2e-canary")
        self.assertEqual(row["model"], "[REDACTED-LOCAL-MODEL]")
        self.assertEqual(row["provider"], "local")
        self.assertIn("duration_ms", row)

    def test_verify_failure_sets_exit_4(self):
        job = self.engine.by_id("sweep")
        rec = self.engine.run_job(job)
        self.assertEqual(rec.exit, 4)
        self.assertIn("verify-fail", rec.flags)

    def test_canary_writes_flag(self):
        trips = self.engine.run_canary()
        self.assertGreaterEqual(len(trips), 1)  # sweep never ran
        self.assertIsNotNone(self.ledger.last_run("fleet-canary"))
