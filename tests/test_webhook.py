import http.client
import os
import tempfile
import unittest

from anton.config import load_config
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine
from anton.webhook import WebhookServer

JOBS = """
- id: bill-email
  trigger: { type: webhook, path: /hooks/bill-email }
  recipe: bill-capture
"""


class TestWebhook(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(), load_config())
        self.srv = WebhookServer(self.engine, "127.0.0.1", 0)
        self.srv.start()

    def tearDown(self):
        self.srv.stop()
        self.dir.cleanup()

    def test_post_dispatches_job(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        conn.request("POST", "/hooks/bill-email", body='{"vendor":"x"}')
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('"exit": 0', body)
        self.assertIsNotNone(self.ledger.last_run("bill-email"))

    def test_unknown_job_404(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        conn.request("POST", "/hooks/nope")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)

    def test_post_with_query_string_dispatches_job(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        conn.request("POST", "/hooks/bill-email?key=val&token=123", body='{"vendor":"x"}')
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('"exit": 0', body)

