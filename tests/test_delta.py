import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from anton.delta import scan_ledger_failures, scan_upskill_candidates
from anton.ledger import Ledger
from anton.models import RunRecord


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

    def test_single_failure_is_not_an_upskill_candidate(self):
        # a one-off failure is scan_ledger_failures' territory (a repair
        # candidate); repeated failure of the SAME task is a competence gap.
        self.ledger.append(RunRecord.new(task="cookie-sync", exit_code=1))
        self.assertEqual(scan_upskill_candidates(self.ledger, self.conn), [])

    def test_repeated_failure_emits_upskill_candidate_and_dedupes(self):
        self.ledger.append(RunRecord.new(task="cookie-sync", exit_code=1))
        self.ledger.append(RunRecord.new(task="cookie-sync", exit_code=1))
        slugs = scan_upskill_candidates(self.ledger, self.conn)
        self.assertEqual(slugs, ["upskill-cookie-sync"])
        self.assertEqual(scan_upskill_candidates(self.ledger, self.conn), [])
