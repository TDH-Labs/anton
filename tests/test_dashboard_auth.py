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
"""


class TestDashboardAuth(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.dir.name, "isolation.db"))
        ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        engine = JobEngine(load_jobs(jobs_path), ledger, FakeExecutor(), load_config())
        provision_vault(os.path.join(self.dir.name, "vault"))
        cfg = load_config()
        cfg.setdefault("general", {})["dashboard_token"] = "s3cret"
        self.client = TestClient(create_app(engine, self.dir.name, cfg))

    def tearDown(self):
        self.dir.cleanup()

    def test_writes_require_token(self):
        r = self.client.post("/api/approvals", json={"action": "x"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/approvals", json={"action": "x"},
                             headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/approvals", json={"action": "x"},
                             headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(r.status_code, 200)

    def test_reads_stay_open(self):
        self.assertEqual(self.client.get("/api/ledger").status_code, 200)
        self.assertEqual(self.client.get("/api/jobs").status_code, 200)

    def test_wizard_endpoints_require_token(self):
        r = self.client.post("/api/wizard/providers", json={"provider": "openai", "key": "sk-test"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/wizard/oauth/start")
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/wizard/mcp")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/wizard/mcp", json={"name": "test", "command": "run"})
        self.assertEqual(r.status_code, 401)

        # Authenticated requests work
        r = self.client.post("/api/wizard/providers", json={"provider": "openai", "key": "sk-test"},
                             headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(r.status_code, 200)

