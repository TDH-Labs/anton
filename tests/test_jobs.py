import tempfile
import os
import unittest
from anton.jobs import load_jobs

JOBS = """
- id: chief-of-staff-briefing-7am
  trigger: { type: cron, expr: "0 7 * * *" }
  recipe: chief-of-staff-vault-briefing
  budget: { tokens_max: 120000 }
  verify: "grep -q ACTION <output>"
  expected_cadence_min: 1440
- id: on-incoming-bill-email
  trigger: { type: webhook, path: /hooks/bill-email }
  recipe: bill-capture
  gate: { outbound: true }
- id: sweep-unapplied-payments
  trigger: { type: delta, source: qbo, condition: "unapplied > 500" }
  recipe: reconcile-payments
  dry_run: true
- id: check-quickbooks-balance
  trigger: { type: webhook }
  recipe: "Using the browser tools available, check the current account balance and report it back."
  executor: { name: opencode, mcp_profile: quickbooks }
  gate: { outbound: true }
"""


class TestJobs(unittest.TestCase):
    def test_load_and_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "jobs.yaml")
            open(p, "w").write(JOBS)
            jobs = load_jobs(p)
            self.assertEqual(len(jobs), 4)
            cron_job = jobs[0]
            self.assertIsNotNone(cron_job.cron)
            self.assertEqual(cron_job.expected_cadence_min, 1440)
            self.assertEqual(jobs[2].dry_run, True)
            self.assertEqual(jobs[1].trigger["type"], "webhook")

    def test_executor_override_is_optional_and_parses_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "jobs.yaml")
            open(p, "w").write(JOBS)
            jobs = load_jobs(p)
            self.assertIsNone(jobs[0].executor)  # no override -- engine default
            self.assertEqual(jobs[3].executor, {"name": "opencode", "mcp_profile": "quickbooks"})
