import datetime as dt
import os
import tempfile
import unittest
from anton.canary import compute_tripwires
from anton.jobs import Job
from anton.ledger import Ledger
from anton.models import RunRecord

NOW = dt.datetime(2026, 8, 18, 10, 0, 0, tzinfo=dt.timezone.utc)
NOW_ISO = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestCanary(unittest.TestCase):
    def test_never_ran_trips(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "runs.jsonl"))
            job = Job(id="cos-maintenance-sweep", trigger={"type": "cron", "expr": "0 7 * * *"},
                      recipe="x", expected_cadence_min=1440)
            trips = compute_tripwires([job], led, now=NOW)
            self.assertEqual(len(trips), 1)
            self.assertEqual(trips[0]["status"], "tripwire")

    def test_recent_run_ok(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "runs.jsonl"))
            led.append(RunRecord.new(task="e2e-canary", exit_code=0))
            job = Job(id="e2e-canary", trigger={"type": "cron", "expr": "*/5 * * * *"},
                      recipe="x", expected_cadence_min=5)
            self.assertEqual(compute_tripwires([job], led, now=NOW), [])

    def test_stale_run_trips(self):
        with tempfile.TemporaryDirectory() as d:
            led = Ledger(os.path.join(d, "runs.jsonl"))
            old = NOW - dt.timedelta(days=5)
            led.append(RunRecord.new(task="sweep", exit_code=0))
            rows = led.read()
            rows[-1]["ts"] = old.strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(led.path, "w") as f:
                import json
                for r in rows:
                    f.write(json.dumps(r) + "\n")
            job = Job(id="sweep", trigger={"type": "cron", "expr": "0 0 * * *"},
                      recipe="x", expected_cadence_min=1440)
            trips = compute_tripwires([job], led, now=NOW)
            self.assertEqual(len(trips), 1)
            self.assertGreater(trips[0]["age_min"], 2 * 1440)
