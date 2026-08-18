import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from harbor.delta import scan_ledger_failures
from harbor.ledger import Ledger
from harbor.models import RunRecord


class TestDelta(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        self.conn.execute("""CREATE TABLE IF NOT EXISTS initiatives (
            id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
            slug TEXT, source TEXT, risk TEXT, score REAL, status TEXT, ts TEXT)""")

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def test_failure_emits_candidate_and_dedupes(self):
        self.ledger.append(RunRecord.new(task="cookie-sync", exit_code=1))
        slugs = scan_ledger_failures(self.ledger, self.conn)
        self.assertEqual(slugs, ["remediate-cookie-sync"])
        # second pass: no duplicate (pending already exists)
        slugs2 = scan_ledger_failures(self.ledger, self.conn)
        self.assertEqual(slugs2, [])

    def test_success_no_candidate(self):
        self.ledger.append(RunRecord.new(task="e2e-canary", exit_code=0))
        self.assertEqual(scan_ledger_failures(self.ledger, self.conn), [])
