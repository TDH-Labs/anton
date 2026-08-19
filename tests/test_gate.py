import datetime as dt
import os
import sqlite3
import tempfile
import unittest

from harbor.config import load_config
from harbor.db import init_db
from harbor.executor import FakeExecutor
from harbor.jobs import load_jobs
from harbor.ledger import Ledger
from harbor.scheduler import JobEngine

JOBS = """
- id: email-client
  trigger: { type: webhook, path: /hooks/email-client }
  recipe: notify-client
  gate: { outbound: true }
"""


class TestGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(),
                                load_config(), data_dir=self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def test_outbound_job_blocked_without_approval(self):
        rec = self.engine.run_job(self.engine.by_id("email-client"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec.exit, 5)
        self.assertIn("gate-blocked", rec.flags)

    def test_outbound_job_runs_after_approval(self):
        with sqlite3.connect(os.path.join(self.dir.name, "isolation.db"), timeout=10.0) as conn:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts) VALUES(?,?,?,?)",
                         ("nonce1", "email-client", "approved",
                          dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
            conn.commit()
        rec = self.engine.run_job(self.engine.by_id("email-client"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec.exit, 0)

    def test_outbound_job_nonce_consumed_after_single_use(self):
        with sqlite3.connect(os.path.join(self.dir.name, "isolation.db"), timeout=10.0) as conn:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts) VALUES(?,?,?,?)",
                         ("nonce1", "email-client", "approved",
                          dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
            conn.commit()
        # First run consumes approval
        rec1 = self.engine.run_job(self.engine.by_id("email-client"),
                                   now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec1.exit, 0)

        # Second run fails closed because approval is consumed
        rec2 = self.engine.run_job(self.engine.by_id("email-client"),
                                   now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec2.exit, 5)
        self.assertIn("gate-blocked", rec2.flags)

