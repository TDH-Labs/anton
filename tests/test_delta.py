import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from anton.delta import scan_ledger_failures, scan_upskill_candidates
from anton.ledger import Ledger
from anton.models import RunRecord
from anton.scheduler import SKIP_FLAG


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

    def test_skipped_no_provider_run_is_not_a_failure_candidate(self):
        # exit=6/SKIP_FLAG (scheduler.py's run_job / opportunity.py's
        # scan_for_opportunities / upskill.py's _dispatch, all gated on
        # provider availability) is an honest non-event, not a failure --
        # before this fix, the very first skip on a fresh install with no
        # provider configured spawned a `remediate-opportunity:scan`
        # initiative that nothing ever marks dispatched, so it sat
        # permanently `pending` and leaked into every future `anton
        # digest`, even after a working key was later added.
        self.ledger.append(RunRecord.new(
            task="opportunity:scan", exit_code=6, flags=SKIP_FLAG))
        self.assertEqual(scan_ledger_failures(self.ledger, self.conn), [])

    def test_skipped_no_provider_run_is_not_an_upskill_candidate(self):
        self.ledger.append(RunRecord.new(
            task="opportunity:scan", exit_code=6, flags=SKIP_FLAG))
        self.ledger.append(RunRecord.new(
            task="opportunity:scan", exit_code=6, flags=SKIP_FLAG))
        self.assertEqual(scan_upskill_candidates(self.ledger, self.conn), [])

    def test_real_failure_after_a_skip_still_emits_a_candidate(self):
        # the skip exclusion must not swallow a genuine failure that
        # happens to follow a skip for the same task.
        self.ledger.append(RunRecord.new(
            task="opportunity:scan", exit_code=6, flags=SKIP_FLAG))
        self.ledger.append(RunRecord.new(task="opportunity:scan", exit_code=1))
        self.assertEqual(scan_ledger_failures(self.ledger, self.conn),
                         ["remediate-opportunity:scan"])
