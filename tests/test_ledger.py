import os
import tempfile
import unittest
from anton.ledger import Ledger
from anton.models import RunRecord


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))

    def tearDown(self):
        self.dir.cleanup()

    def test_append_read_last(self):
        self.ledger.append(RunRecord.new(task="e2e-canary", exit_code=0))
        self.ledger.append(RunRecord.new(task="cos-maintenance-sweep", exit_code=1))
        rows = self.ledger.read()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["task"], "e2e-canary")
        last = self.ledger.last_run("cos-maintenance-sweep")
        self.assertEqual(last["exit"], 1)
        self.assertIsNone(self.ledger.last_run("never-ran"))

    def test_r9_fields_present_in_line(self):
        self.ledger.append(RunRecord.new(task="t", exit_code=0, model="m", provider="cloud",
                                         tokens_in=1, tokens_out=2, duration_ms=3))
        raw = open(self.ledger.path, encoding="utf-8").read()
        for field in ("model", "provider", "fallback_used", "tokens_in", "duration_ms",
                      "host", "session_id", "org_id"):
            self.assertIn(f'"{field}"', raw)
