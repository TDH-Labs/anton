import datetime as dt
import os
import sqlite3
import tempfile
import unittest

from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine

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

    def _seed_approved(self, action: str, nonce: str):
        with sqlite3.connect(os.path.join(self.dir.name, "isolation.db"),
                             timeout=10.0) as conn:
            conn.execute(
                "INSERT INTO approvals(nonce, action, status, ts, initiator_human,"
                " initiator_principal) VALUES(?,?,?,?,?,?)",
                (nonce, action, "pending",
                 dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "system", "system:gate"))
            conn.execute(
                "UPDATE approvals SET status='approved', approver_human='owner',"
                " approver_principal='owner' WHERE nonce=?", (nonce,))
            conn.commit()

    def test_outbound_job_runs_after_approval(self):
        self._seed_approved("email-client", "nonce1")
        rec = self.engine.run_job(self.engine.by_id("email-client"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec.exit, 0)

    def test_outbound_job_nonce_consumed_after_single_use(self):
        self._seed_approved("email-client", "nonce1")
        rec1 = self.engine.run_job(self.engine.by_id("email-client"),
                                   now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec1.exit, 0)
        # Second run fails-closed: approval already consumed
        rec2 = self.engine.run_job(self.engine.by_id("email-client"),
                                   now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec2.exit, 5)
        self.assertIn("gate-blocked", rec2.flags)

    def test_son_of_anton_mode_bypasses_human_gate(self):
        # Enable Son of Anton permissionless mode — via the persisted setting,
        # since _is_approved treats isolation.db as cross-process truth
        from anton.scheduler import set_son_of_anton_mode
        set_son_of_anton_mode(self.dir.name, True)
        self.engine.son_of_anton_mode = True
        # Gated job runs without manual approval
        rec = self.engine.run_job(self.engine.by_id("email-client"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec.exit, 0)
        self.assertIn("son_of_anton_bypass", rec.flags)
        
        # Verify auto-recorded approval row
        with sqlite3.connect(os.path.join(self.dir.name, "isolation.db"), timeout=10.0) as conn:
            row = conn.execute("SELECT status, hmac FROM approvals WHERE action='email-client'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "consumed")
            self.assertEqual(row[1], "son_of_anton_bypass")
