import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

from anton import browser_login
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.executor.opencode_executor import OpenCodeExecutor
from anton.executor.n8n_executor import N8NExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine

JOBS = """
- id: default-job
  trigger: { type: webhook }
  recipe: default-recipe
- id: check-quickbooks-balance
  trigger: { type: webhook }
  recipe: "check the balance"
  executor: { name: opencode, mcp_profile: quickbooks }
- id: check-another-service
  trigger: { type: webhook }
  recipe: "check something else"
  executor: { name: opencode, mcp_profile: another-service }
- id: reconcile-via-n8n
  trigger: { type: webhook }
  recipe: "reconcile stripe vs qbo"
  executor: { name: n8n, webhook_url: "https://n8n.example/webhook/reconcile" }
- id: notify-via-n8n
  trigger: { type: webhook }
  recipe: "notify slack"
  executor: { name: n8n, webhook_url: "https://n8n.example/webhook/notify" }
- id: n8n-job-missing-webhook-url
  trigger: { type: webhook }
  recipe: "whatever"
  executor: { name: n8n }
- id: unknown-executor-job
  trigger: { type: webhook }
  recipe: "whatever"
  executor: { name: not-a-real-executor }
"""


class JobExecutorOverrideTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.dir.name, "data")
        os.makedirs(self.data_dir)
        init_db(os.path.join(self.data_dir, "isolation.db"))
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))
        self.default_executor = FakeExecutor()
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, self.default_executor,
                                load_config(), data_dir=self.data_dir)

    def tearDown(self):
        self.dir.cleanup()


class TestResolveExecutor(JobExecutorOverrideTestBase):
    def test_job_with_no_override_uses_the_engine_default(self):
        job = self.engine.by_id("default-job")
        self.assertIs(self.engine._resolve_executor(job), self.default_executor)

    def test_opencode_override_builds_an_opencode_executor(self):
        job = self.engine.by_id("check-quickbooks-balance")
        executor = self.engine._resolve_executor(job)
        self.assertIsInstance(executor, OpenCodeExecutor)
        self.assertNotEqual(executor, self.default_executor)

    def test_opencode_override_points_at_the_right_persistent_session(self):
        job = self.engine.by_id("check-quickbooks-balance")
        executor = self.engine._resolve_executor(job)
        install_dir = os.path.dirname(self.data_dir)
        self.assertEqual(executor.playwright_profile_dir,
                         browser_login.session_dir(install_dir, "quickbooks"))

    def test_same_mcp_profile_reuses_the_cached_executor_instance(self):
        job = self.engine.by_id("check-quickbooks-balance")
        first = self.engine._resolve_executor(job)
        second = self.engine._resolve_executor(job)
        self.assertIs(first, second)

    def test_different_mcp_profiles_get_different_executor_instances(self):
        qbo_executor = self.engine._resolve_executor(self.engine.by_id("check-quickbooks-balance"))
        other_executor = self.engine._resolve_executor(self.engine.by_id("check-another-service"))
        self.assertIsNot(qbo_executor, other_executor)
        self.assertNotEqual(qbo_executor.playwright_profile_dir, other_executor.playwright_profile_dir)

    def test_unknown_executor_name_fails_loud_not_a_silent_fallback(self):
        job = self.engine.by_id("unknown-executor-job")
        with self.assertRaises(ValueError):
            self.engine._resolve_executor(job)

    def test_n8n_override_builds_an_n8n_executor_at_the_right_webhook(self):
        job = self.engine.by_id("reconcile-via-n8n")
        executor = self.engine._resolve_executor(job)
        self.assertIsInstance(executor, N8NExecutor)
        self.assertEqual(executor.webhook_url, "https://n8n.example/webhook/reconcile")

    def test_same_n8n_webhook_reuses_the_cached_executor_instance(self):
        job = self.engine.by_id("reconcile-via-n8n")
        first = self.engine._resolve_executor(job)
        second = self.engine._resolve_executor(job)
        self.assertIs(first, second)

    def test_different_n8n_webhooks_get_different_executor_instances(self):
        reconcile = self.engine._resolve_executor(self.engine.by_id("reconcile-via-n8n"))
        notify = self.engine._resolve_executor(self.engine.by_id("notify-via-n8n"))
        self.assertIsNot(reconcile, notify)
        self.assertNotEqual(reconcile.webhook_url, notify.webhook_url)

    def test_n8n_override_without_webhook_url_fails_loud(self):
        job = self.engine.by_id("n8n-job-missing-webhook-url")
        with self.assertRaises(ValueError):
            self.engine._resolve_executor(job)


class TestRunJobUsesResolvedExecutor(JobExecutorOverrideTestBase):
    def test_default_job_still_dispatches_through_the_engine_default(self):
        rec = self.engine.run_job(self.engine.by_id("default-job"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(rec.exit, 0)
        self.assertTrue(rec.output.startswith("[fake]"))  # FakeExecutor's own marker

    @patch("anton.executor.opencode_executor.shutil.which", return_value=None)
    def test_override_job_never_touches_the_engine_default_executor(self, _mock_which):
        # opencode may genuinely be installed on the machine running this
        # test suite -- force the unavailable path deterministically rather
        # than relying on its absence. The point being verified: this job's
        # run went through OpenCodeExecutor (one honest skip naming its
        # missing binary), not FakeExecutor (self.executor, which always
        # succeeds with exit_code=0 and a "[fake]"-prefixed output).
        rec = self.engine.run_job(self.engine.by_id("check-quickbooks-balance"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertFalse(rec.output.startswith("[fake]"))
        self.assertEqual(rec.exit, 6)  # skipped, not a fake success
        self.assertIn("skipped:no-provider", rec.flags)
        self.assertIn("opencode binary not found", rec.output)

    @patch("anton.executor.n8n_executor._http_get", return_value=200)
    @patch("anton.executor.n8n_executor._http_post_json")
    def test_n8n_override_job_dispatches_to_its_webhook_not_the_engine_default(self, mock_post, _mock_get):
        # _http_get mocked reachable: the governor's own provider-block gate
        # calls executor.available() before dispatch (same gate every
        # executor goes through) -- proving it fires for N8NExecutor too,
        # not something this override bypasses.
        mock_post.return_value = (200, '{"output": "reconciled", "exit_code": 0}')
        rec = self.engine.run_job(self.engine.by_id("reconcile-via-n8n"),
                                  now=dt.datetime.now(dt.timezone.utc))
        self.assertFalse(rec.output.startswith("[fake]"))
        self.assertEqual(rec.exit, 0)
        self.assertEqual(rec.output, "reconciled")
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args[0][0], "https://n8n.example/webhook/reconcile")


if __name__ == "__main__":
    unittest.main()
