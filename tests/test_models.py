import unittest
from harbor.models import RunRecord


class TestRunRecord(unittest.TestCase):
    def test_local_provider_never_records_tokens(self):
        r = RunRecord.new(task="t", exit_code=0, model="[REDACTED-LOCAL-INFERENCE]/qwen", provider="[REDACTED-LOCAL-INFERENCE]",
                          tokens_in=999, tokens_out=999, cost_usd=1.5)
        self.assertEqual(r.token_accounting, "local")
        self.assertIsNone(r.tokens_in)
        self.assertIsNone(r.tokens_out)
        self.assertIsNone(r.cost_usd)

    def test_cloud_provider_keeps_usage(self):
        r = RunRecord.new(task="t", exit_code=0, model="openrouter/anthropic/claude-3.5-sonnet",
                          provider="openrouter", tokens_in=100, tokens_out=50, cost_usd=0.01)
        self.assertEqual(r.token_accounting, "cloud")
        self.assertEqual(r.tokens_in, 100)
        self.assertEqual(r.tokens_out, 50)
        self.assertEqual(r.cost_usd, 0.01)

    def test_required_fields_present(self):
        r = RunRecord.new(task="t", exit_code=1)
        self.assertTrue(r.ts)
        self.assertTrue(r.host)
        self.assertTrue(r.session_id)
        self.assertEqual(r.org_id, "default")
        self.assertEqual(r.exit, 1)
