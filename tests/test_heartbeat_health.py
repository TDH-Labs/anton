import http.client
import os
import tempfile
import unittest

from harbor.config import load_config
from harbor.db import init_db
from harbor.executor import FakeExecutor
from harbor.jobs import load_jobs
from harbor.ledger import Ledger
from harbor.scheduler import JobEngine
from harbor.webhook import WebhookServer

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
"""


class TestHeartbeatHealth(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(),
                                load_config(), data_dir=self.dir.name)
        self.srv = WebhookServer(self.engine, "127.0.0.1", 0)
        self.srv.start()

    def tearDown(self):
        self.srv.stop()
        self.dir.cleanup()

    def test_run_job_touches_heartbeat(self):
        self.engine.run_job(self.engine.by_id("e2e-canary"))
        self.assertTrue(os.path.exists(os.path.join(self.dir.name, "last-heartbeat")))

    def test_health_endpoint(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('"ok": true', body)
        self.assertIn('"jobs": 1', body)
