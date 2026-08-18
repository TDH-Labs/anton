import datetime as dt
import os
import tempfile
import unittest
from harbor.metering import connect, daily_totals, lifetime_totals, record
from harbor.models import RunRecord


class TestMetering(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.conn = connect(os.path.join(self.dir.name, "isolation.db"))

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def test_local_runs_not_metered(self):
        record(self.conn, RunRecord.new(task="t", exit_code=0, model="[REDACTED-LOCAL-INFERENCE]/q",
                                        provider="[REDACTED-LOCAL-INFERENCE]", tokens_in=999))
        self.assertEqual(lifetime_totals(self.conn)["runs"], 0)

    def test_cloud_runs_metered(self):
        r = RunRecord.new(task="t", exit_code=0, model="openrouter/x",
                          provider="openrouter", tokens_in=100, tokens_out=50,
                          cost_usd=0.01)
        record(self.conn, r, job_id="job1")
        rec2 = RunRecord.new(task="t2", exit_code=0, model="openrouter/x",
                             provider="openrouter", tokens_in=200, tokens_out=100,
                             cost_usd=0.02)
        record(self.conn, rec2, job_id="job2")
        lt = lifetime_totals(self.conn)
        self.assertEqual(lt["runs"], 2)
        self.assertEqual(lt["tokens_in"], 300)
        self.assertEqual(lt["cost_usd"], 0.03)
