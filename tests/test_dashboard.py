import datetime as dt
import os
import tempfile
import unittest
from fastapi.testclient import TestClient

from harbor.config import load_config
from harbor.dashboard import create_app
from harbor.db import init_db
from harbor.executor import FakeExecutor
from harbor.jobs import load_jobs
from harbor.ledger import Ledger
from harbor.scheduler import JobEngine
from harbor.vault import provision_vault

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
"""


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(), load_config())
        provision_vault(os.path.join(self.dir.name, "vault"))
        self.engine.run_job(self.engine.by_id("e2e-canary"),
                            now=dt.datetime.now(dt.timezone.utc))
        app = create_app(self.engine, self.dir.name, load_config())
        self.client = TestClient(app)

    def tearDown(self):
        self.dir.cleanup()

    def test_index_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("harbor-sas", r.text)

    def test_ledger_api(self):
        r = self.client.get("/api/ledger")
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task"], "e2e-canary")
        self.assertIn("model", rows[0])  # R9 fields served

    def test_canary_and_usage(self):
        self.assertEqual(self.client.get("/api/canary").json(), [])
        u = self.client.get("/api/usage").json()
        self.assertEqual(u["cloud_runs"], 0)

    def test_approval_flow_writes_only_table(self):
        r = self.client.post("/api/approvals", json={"action": "move_20k_transfer",
                                                     "amount": "20000", "recipient": "vendor"})
        self.assertEqual(r.status_code, 200)
        aid = r.json()["id"]
        # pending visible
        pending = self.client.get("/api/approvals").json()
        self.assertEqual(len(pending), 1)
        # resolve approve
        r = self.client.post(f"/api/approvals/{aid}/resolve", json={"decision": "approve"})
        self.assertEqual(r.status_code, 200)
        # no longer pending, and no job executed anywhere
        self.assertEqual(self.client.get("/api/approvals").json(), [])
        rows = self.ledger.read()
        self.assertEqual(len(rows), 1)  # only the canary run; approval never executed

    def test_digest_endpoint(self):
        r = self.client.get("/api/digest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("## 1. Fleet status", r.text)
