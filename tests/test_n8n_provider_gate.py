"""Regression pin: an n8n webhook job must never be provider-blocked.

The n8n job's work happens inside the operator's workflow (its own
connectors, its own AI Agent node) — Anton POSTs a payload, it does not
make a model call. But the job carries no model route of its own, so it
falls back to the default route, and _provider_block used to gate the
dispatch on that route: on any machine without a reachable Ollama the
job was skipped exit-6 "nothing listening on 127.0.0.1:11434" forever.
CI caught it; this file pins the fix deterministically (the local-model
probe is forced unreachable rather than relying on what's listening).
"""
import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.executor.n8n_executor import N8NExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine

JOBS = """
- id: heartbeat
  trigger: { type: webhook }
  recipe: heartbeat-recipe
- id: reconcile-via-n8n
  trigger: { type: webhook }
  recipe: "reconcile stripe vs qbo"
  executor: { name: n8n, webhook_url: "https://n8n.example/webhook/reconcile" }
"""


class N8NJobNeverProviderBlocked(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.dir.name, "data")
        os.makedirs(self.data_dir)
        init_db(os.path.join(self.data_dir, "isolation.db"))
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.engine = JobEngine(load_jobs(jobs_path),
                                Ledger(os.path.join(self.data_dir, "runs.jsonl")),
                                FakeExecutor(), load_config(),
                                data_dir=self.data_dir)

    def tearDown(self):
        self.dir.cleanup()

    def test_n8n_job_dispatches_even_when_the_local_model_endpoint_is_dead(self):
        webhook_url = "https://n8n.example/webhook/reconcile"
        posted = {}

        def fake_post(url, payload, headers, timeout_s):
            posted.update(url=url)
            return 200, '{"output": "reconciled", "exit_code": 0}'

        # Same injection path run_job resolves through (_resolve_executor's
        # cache), with transports stubbed so CI never touches the network.
        self.engine._job_executor_cache[("n8n", webhook_url)] = N8NExecutor(
            webhook_url, post_transport=fake_post,
            get_transport=lambda url, timeout_s: 200)

        # Force the exact condition that broke CI: nothing reachable on the
        # default local-model endpoint — and prove the n8n dispatch is not
        # gated by it.
        with patch("anton.scheduler._tcp_reachable", return_value=False):
            rec = self.engine.run_job(
                self.engine.by_id("reconcile-via-n8n"),
                now=dt.datetime.now(dt.timezone.utc))

        self.assertEqual(rec.exit, 0,
                         msg=f"flags={rec.flags!r} output={rec.output!r}")
        self.assertEqual(rec.output, "reconciled")
        self.assertEqual(posted["url"], webhook_url)

    def test_unreachable_n8n_instance_is_still_skipped_honestly(self):
        # The inverse stays true: when the n8n instance itself is down,
        # availability still gates the dispatch (no fake success).
        with patch("anton.scheduler._tcp_reachable", return_value=False):
            rec = self.engine.run_job(
                self.engine.by_id("reconcile-via-n8n"),
                now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec.exit, 6)
        self.assertIn("skipped:no-provider", rec.flags)


if __name__ == "__main__":
    unittest.main()
