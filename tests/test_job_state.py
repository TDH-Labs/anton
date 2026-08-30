"""In-flight state and operator steering (anton/job_state.py + the scheduler
and API wiring that consume it)."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from anton import job_state
from anton.config import load_config
from anton.dashboard import create_app
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.executor.base import RunResult
from anton.jobs import Job, load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine
from anton.vault import provision_vault

JOBS = """
- id: every-minute
  trigger: { type: cron, expr: "* * * * *" }
  recipe: "tick"
- id: webhook-only
  trigger: { type: webhook }
  recipe: "on demand"
"""


# Both subclass the real FakeExecutor rather than Executor directly.
# scheduler._provider_block exempts FakeExecutor by isinstance -- there is no
# real provider behind a deterministic stub, so gating one on a reachable
# Ollama or a cloud key is meaningless. A stub deriving straight from
# Executor misses that exemption and gets SKIPPED instead of dispatched,
# which passes on a developer machine that happens to run Ollama and fails
# on CI, which runs neither.


class SpyRunningExecutor(FakeExecutor):
    """Reads the in-flight table from inside the dispatch, which is the only
    moment a row is supposed to exist."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.seen_running: list = []

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        self.seen_running = job_state.list_running(self.data_dir)
        return RunResult(0, "ok", "", 1, model, provider)


class BoomExecutor(FakeExecutor):
    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        raise RuntimeError("executor exploded mid-dispatch")


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = self.dir.name
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.data_dir, "isolation.db"))
        provision_vault(os.path.join(self.data_dir, "vault"))
        self.jobs = load_jobs(jobs_path)
        self.ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))

    def tearDown(self):
        self.dir.cleanup()

    def engine(self, executor=None):
        return JobEngine(self.jobs, self.ledger, executor or FakeExecutor(),
                         load_config(), data_dir=self.data_dir)


class TestInFlightState(_Base):
    def test_no_rows_before_anything_runs(self):
        self.assertEqual(job_state.list_running(self.data_dir), [])

    def test_mark_and_clear_round_trip(self):
        job_state.mark_running(self.data_dir, "every-minute")
        running = job_state.list_running(self.data_dir)
        self.assertEqual([r["job_id"] for r in running], ["every-minute"])
        self.assertIsNotNone(running[0]["started_at"])
        job_state.clear_running(self.data_dir, "every-minute")
        self.assertEqual(job_state.list_running(self.data_dir), [])

    def test_clearing_an_absent_row_is_not_an_error(self):
        job_state.clear_running(self.data_dir, "never-ran")

    def test_row_exists_during_dispatch_and_is_gone_after(self):
        spy = SpyRunningExecutor(self.data_dir)
        engine = self.engine(spy)
        engine.run_job(engine.by_id("every-minute"), now=dt.datetime.now(dt.timezone.utc))
        # Observed from inside executor.run: the job WAS marked in flight.
        self.assertEqual([r["job_id"] for r in spy.seen_running], ["every-minute"])
        # And the finally cleared it.
        self.assertEqual(job_state.list_running(self.data_dir), [])

    def test_a_raising_executor_still_clears_its_in_flight_row(self):
        engine = self.engine(BoomExecutor())
        with self.assertRaises(RuntimeError):
            engine.run_job(engine.by_id("every-minute"), now=dt.datetime.now(dt.timezone.utc))
        self.assertEqual(job_state.list_running(self.data_dir), [],
                         "a crashed dispatch must not strand a phantom running row")

    def test_stale_rows_are_hidden_from_readers_and_swept_at_boot(self):
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=7200)).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
        conn = sqlite3.connect(os.path.join(self.data_dir, "isolation.db"))
        conn.executescript(job_state.SCHEMA)
        conn.execute("INSERT INTO running_jobs(job_id, started_at, host) VALUES(?,?,?)",
                     ("killed-mid-run", old, "somehost"))
        conn.commit()
        conn.close()
        # A reader hides it without mutating the writer's table.
        self.assertEqual(job_state.list_running(self.data_dir), [])
        # Boot sweeps it for real.
        self.assertEqual(job_state.clear_stale_running(self.data_dir), 1)
        self.assertEqual(job_state.clear_stale_running(self.data_dir), 0)

    def test_a_fresh_row_survives_the_stale_sweep(self):
        job_state.mark_running(self.data_dir, "every-minute")
        self.assertEqual(job_state.clear_stale_running(self.data_dir), 0)
        self.assertEqual(len(job_state.list_running(self.data_dir)), 1)


class TestSteering(_Base):
    def test_unsteered_job_defaults_to_all_false(self):
        self.assertEqual(
            job_state.get_state(self.data_dir, "every-minute"),
            {"job_id": "every-minute", "paused": False, "run_now": False, "skip_next": False})

    def test_pause_then_resume(self):
        self.assertTrue(job_state.set_paused(self.data_dir, "every-minute", True)["paused"])
        self.assertFalse(job_state.set_paused(self.data_dir, "every-minute", False)["paused"])

    def test_paused_job_is_not_due(self):
        engine = self.engine()
        at = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
        self.assertIn("every-minute", [j.id for j in engine.due_jobs(now=at)])
        job_state.set_paused(self.data_dir, "every-minute", True)
        self.assertNotIn("every-minute", [j.id for j in engine.due_jobs(now=at)])

    def test_run_now_makes_a_webhook_job_due_and_is_consumed(self):
        engine = self.engine()
        at = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
        # A webhook-triggered job has no cron and is never otherwise due.
        self.assertNotIn("webhook-only", [j.id for j in engine.due_jobs(now=at)])
        job_state.request_run_now(self.data_dir, "webhook-only")
        self.assertIn("webhook-only", [j.id for j in engine.due_jobs(now=at)])
        # Exactly once: the request is consumed by the tick that satisfied it.
        self.assertNotIn("webhook-only", [j.id for j in engine.due_jobs(now=at)])
        self.assertFalse(job_state.get_state(self.data_dir, "webhook-only")["run_now"])

    def test_run_now_outranks_pause_being_absent_not_present(self):
        # A paused job stays paused even with run-now pending: pause is the
        # operator's standing instruction, run-now is a single request.
        engine = self.engine()
        at = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
        job_state.set_paused(self.data_dir, "webhook-only", True)
        job_state.request_run_now(self.data_dir, "webhook-only")
        self.assertNotIn("webhook-only", [j.id for j in engine.due_jobs(now=at)])

    def test_skip_next_skips_one_window_then_normal_cadence_resumes(self):
        engine = self.engine()
        first = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
        second = dt.datetime(2026, 1, 1, 12, 1, tzinfo=dt.timezone.utc)
        job_state.request_skip_next(self.data_dir, "every-minute")
        self.assertNotIn("every-minute", [j.id for j in engine.due_jobs(now=first)])
        self.assertIn("every-minute", [j.id for j in engine.due_jobs(now=second)])

    def test_steering_survives_an_unreadable_store_without_stopping_dispatch(self):
        engine = JobEngine(self.jobs, self.ledger, FakeExecutor(), load_config(),
                           data_dir="/nonexistent/path/that/cannot/be/opened")
        at = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)
        self.assertIn("every-minute", [j.id for j in engine.due_jobs(now=at)])


class TestSteeringApi(_Base):
    def client(self):
        engine = self.engine()
        return TestClient(create_app(engine, self.data_dir, load_config()))

    def test_worklog_reports_running_separately_from_scheduled(self):
        job_state.mark_running(self.data_dir, "every-minute")
        body = self.client().get("/api/agent/worklog").json()
        running = [o for o in body["ongoing"] if o.get("status") == "running"]
        self.assertEqual(len(running), 1)
        self.assertIn("every-minute", running[0]["text"])

    def test_a_running_job_is_not_also_listed_as_scheduled(self):
        job_state.mark_running(self.data_dir, "every-minute")
        body = self.client().get("/api/agent/worklog").json()
        mentions = [o for o in body["ongoing"] if "every-minute" in o["text"]]
        self.assertEqual(len(mentions), 1, "in-flight and due must not double-count")

    def test_job_state_endpoint_lists_every_job(self):
        body = self.client().get("/api/jobs/state").json()
        self.assertEqual({j["job_id"] for j in body["jobs"]},
                         {"every-minute", "webhook-only"})

    def test_steer_pause_persists_and_is_honest_about_timing(self):
        c = self.client()
        r = c.post("/api/jobs/every-minute/steer", json={"action": "pause"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["state"]["paused"])
        self.assertFalse(body["interrupts_running_job"])
        self.assertIn("next poll tick", body["takes_effect"])
        self.assertTrue(job_state.get_state(self.data_dir, "every-minute")["paused"])

    def test_steer_each_verb(self):
        c = self.client()
        for action, field in (("pause", "paused"), ("run-now", "run_now"),
                              ("skip-next", "skip_next")):
            r = c.post("/api/jobs/webhook-only/steer", json={"action": action})
            self.assertEqual(r.status_code, 200, action)
            self.assertTrue(r.json()["state"][field], action)
        self.assertFalse(
            c.post("/api/jobs/webhook-only/steer",
                   json={"action": "resume"}).json()["state"]["paused"])

    def test_unknown_job_is_404(self):
        r = self.client().post("/api/jobs/no-such-job/steer", json={"action": "pause"})
        self.assertEqual(r.status_code, 404)

    def test_unknown_action_is_400(self):
        r = self.client().post("/api/jobs/every-minute/steer", json={"action": "delete"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
