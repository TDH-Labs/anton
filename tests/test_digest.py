import datetime as dt
import os
import tempfile
import unittest

from anton.config import load_config
from anton.digest import build_digest, write_digest
from anton.executor import FakeExecutor
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


class TestDigest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(), load_config())
        self.vault = provision_vault(os.path.join(self.dir.name, "vault"))
        job = self.engine.by_id("e2e-canary")
        self.engine.run_job(job, now=dt.datetime.now(dt.timezone.utc))

    def tearDown(self):
        self.dir.cleanup()

    def test_digest_has_all_sections(self):
        content = build_digest(self.engine, self.vault, load_config())
        for header in ("## 1. Fleet status", "## 2. Completed", "## 3. Running now",
                       "## 4. Pipeline ahead", "## 5. LLM usage", "## 6. Gate & budget",
                       "## 7. Registry"):
            self.assertIn(header, content)
        self.assertIn("e2e-canary", content)

    def test_write_digest_atomic_and_indexed(self):
        content = build_digest(self.engine, self.vault, load_config())
        path = write_digest(os.path.join(self.vault, "digests", "daily-digest.md"),
                            content, self.vault)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), content)
        import sqlite3
        conn = sqlite3.connect(os.path.join(self.vault, "vault.db"))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM digest_history").fetchone()[0], 1)
        conn.close()
