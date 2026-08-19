import datetime as dt
import os
import tempfile
import unittest
from harbor.config import load_config
from harbor.db import init_db
from harbor.executor import FakeExecutor
from harbor.jobs import load_jobs
from harbor.ledger import Ledger
from harbor.scheduler import JobEngine

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
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(self.jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                                FakeExecutor(), load_config(), data_dir=self.dir.name)


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

    def test_budget_breach_preserves_accounting(self):
        class MeteredExecutor(FakeExecutor):
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                from harbor.executor.base import RunResult
                return RunResult(0, "output", "", 100, model, provider,
                                 tokens_in=10000, tokens_out=5000, cost_usd=0.25)

        cfg = load_config()
        cfg["budgets"] = {"tokens_max_per_job": 1000}
        engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                           MeteredExecutor(), cfg, data_dir=self.dir.name)
        job = engine.by_id("e2e-canary")
        job.model_route = "cloud"
        rec = engine.run_job(job)
        self.assertEqual(rec.exit, 3)
        self.assertEqual(rec.flags, "budget-breach")
        self.assertEqual(rec.tokens_in, 10000)
        self.assertEqual(rec.tokens_out, 5000)
        self.assertEqual(rec.cost_usd, 0.25)

        import sqlite3
        conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        row = conn.execute("SELECT tokens_in, tokens_out, cost_usd FROM metering ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 10000)

    def test_executor_timeout_passed(self):
        class TimeoutExecutor(FakeExecutor):
            def __init__(self):
                self.received_timeout = None
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                self.received_timeout = timeout_s
                return super().run(task, model=model, provider=provider, cwd=cwd, timeout_s=timeout_s)

        texe = TimeoutExecutor()
        cfg = load_config()
        cfg.setdefault("general", {})["job_timeout_seconds"] = 42
        engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                           texe, cfg, data_dir=self.dir.name)
        engine.run_job(engine.by_id("e2e-canary"))
        self.assertEqual(texe.received_timeout, 42)

