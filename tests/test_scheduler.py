import datetime as dt
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine, _ollama_model_missing

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
- id: sweep
  trigger: { type: cron, expr: "0 0 * * *" }
  recipe: sweep-recipe
  verify: "grep -q NEVER_MARKER <output>"
  expected_cadence_min: 1440
"""


class TestScheduler(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(self.jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                                FakeExecutor(), load_config(), data_dir=self.dir.name)


    def tearDown(self):
        self.dir.cleanup()

    def test_due_jobs_fires_on_matching_minute(self):
        now = dt.datetime(2026, 8, 18, 10, 10, 0, tzinfo=dt.timezone.utc)  # */5 matches :10
        due = self.engine.due_jobs(now)
        ids = {j.id for j in due}
        self.assertIn("e2e-canary", ids)
        self.assertNotIn("sweep", ids)

    def test_due_jobs_idempotent_within_minute(self):
        now = dt.datetime(2026, 8, 18, 10, 10, 0, tzinfo=dt.timezone.utc)
        job = self.engine.by_id("e2e-canary")
        self.engine.run_job(job, now=now)
        # after running this minute, it must not be due again until the next matching minute
        self.assertEqual(self.engine.due_jobs(now), [])

    def test_run_job_records_r9(self):
        job = self.engine.by_id("e2e-canary")
        rec = self.engine.run_job(job)
        self.assertEqual(rec.exit, 0)
        row = self.ledger.last_run("e2e-canary")
        self.assertEqual(row["model"], "ollama/llama3.1:8b")
        self.assertEqual(row["provider"], "local")
        self.assertIn("duration_ms", row)

    def test_verify_failure_sets_exit_4(self):
        job = self.engine.by_id("sweep")
        rec = self.engine.run_job(job)
        self.assertEqual(rec.exit, 4)
        self.assertIn("verify-fail", rec.flags)

    def test_canary_writes_flag(self):
        trips = self.engine.run_canary()
        self.assertGreaterEqual(len(trips), 1)  # sweep never ran
        self.assertIsNotNone(self.ledger.last_run("fleet-canary"))

    def test_budget_breach_preserves_accounting(self):
        class MeteredExecutor(FakeExecutor):
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                from anton.executor.base import RunResult
                return RunResult(0, "output", "", 100, model, provider,
                                 tokens_in=10000, tokens_out=5000, cost_usd=0.25)

        cfg = load_config()
        cfg["budgets"] = {"tokens_max_per_job": 1000}
        engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                           MeteredExecutor(), cfg, data_dir=self.dir.name)
        job = engine.by_id("e2e-canary")
        job.model_route = "cloud"
        rec = engine.run_job(job)
        self.assertEqual(rec.exit, 3)
        self.assertEqual(rec.flags, "budget-breach")
        self.assertEqual(rec.tokens_in, 10000)
        self.assertEqual(rec.tokens_out, 5000)
        self.assertEqual(rec.cost_usd, 0.25)

        import sqlite3
        conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        row = conn.execute("SELECT tokens_in, tokens_out, cost_usd FROM metering ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 10000)

    def test_executor_timeout_passed(self):
        class TimeoutExecutor(FakeExecutor):
            def __init__(self):
                self.received_timeout = None
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                self.received_timeout = timeout_s
                return super().run(task, model=model, provider=provider, cwd=cwd, timeout_s=timeout_s)

        texe = TimeoutExecutor()
        cfg = load_config()
        cfg.setdefault("general", {})["job_timeout_seconds"] = 42
        engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                           texe, cfg, data_dir=self.dir.name)
        engine.run_job(engine.by_id("e2e-canary"))
        self.assertEqual(texe.received_timeout, 42)



class TestJobsHotReload(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(self.jobs_path, "w") as f:
            f.write("- id: a\n  trigger: { type: webhook }\n  recipe: r1\n")
        init_db(os.path.join(self.dir.name, "isolation.db"))
        cfg = load_config()
        self.engine = JobEngine(load_jobs(self.jobs_path), Ledger(
            os.path.join(self.dir.name, "runs.jsonl")),
            FakeExecutor(), cfg, data_dir=self.dir.name)

    def test_reload_picks_up_new_job_without_restart(self):
        self.assertIsNone(self.engine.by_id("b"))
        # bump mtime (some filesystems have 1s resolution)
        import time as _t
        _t.sleep(0.05)
        with open(self.jobs_path, "a") as f:
            f.write("- id: b\n  trigger: { type: webhook }\n  recipe: r2\n")
        os.utime(self.jobs_path, (_t.time() + 2, _t.time() + 2))
        changed = self.engine.reload_jobs_if_changed()
        self.assertTrue(changed)
        self.assertIsNotNone(self.engine.by_id("b"))

    def test_no_reload_when_unchanged(self):
        self.assertFalse(self.engine.reload_jobs_if_changed())


class TestSonOfAntonPersistence(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        init_db(os.path.join(self.dir.name, "isolation.db"))

    def test_mode_roundtrip_across_processes(self):
        from anton.scheduler import get_son_of_anton_mode, set_son_of_anton_mode
        self.assertFalse(get_son_of_anton_mode(self.dir.name))
        set_son_of_anton_mode(self.dir.name, True)
        # a fresh engine in a *different process* would read the same DB
        self.assertTrue(get_son_of_anton_mode(self.dir.name))
        set_son_of_anton_mode(self.dir.name, False)
        self.assertFalse(get_son_of_anton_mode(self.dir.name))

    def test_gated_job_runs_when_mode_persisted_true(self):
        from anton.scheduler import set_son_of_anton_mode
        set_son_of_anton_mode(self.dir.name, True)
        with open(self.jobs_path if hasattr(self, "jobs_path") else
                  os.path.join(self.dir.name, "jobs.yaml"), "w") as f:
            f.write("- id: gated\n  trigger: { type: webhook }\n  recipe: money\n"
                    "  gate: { money: true }\n")
        engine = JobEngine(load_jobs(os.path.join(self.dir.name, "jobs.yaml")),
                           Ledger(os.path.join(self.dir.name, "runs.jsonl")),
                           FakeExecutor(), load_config(), data_dir=self.dir.name)
        rec = engine.run_job(engine.by_id("gated"))
        self.assertEqual(rec.exit, 0)


class TestSonOfAntonToggleOff(unittest.TestCase):
    def test_stale_true_resyncs_to_false(self):
        import tempfile
        from anton.scheduler import get_son_of_anton_mode, set_son_of_anton_mode
        d = tempfile.TemporaryDirectory()
        init_db(os.path.join(d.name, "isolation.db"))
        set_son_of_anton_mode(d.name, True)
        jp = os.path.join(d.name, "jobs.yaml")
        with open(jp, "w") as f:
            f.write("- id: gated\n  trigger: { type: webhook }\n  recipe: money\n"
                    "  gate: { money: true }\n")
        cfg = load_config()
        eng = JobEngine(load_jobs(jp), Ledger(os.path.join(d.name, "runs.jsonl")),
                        FakeExecutor(), cfg, data_dir=d.name)
        self.assertEqual(eng.run_job(eng.by_id("gated")).exit, 0)   # bypass runs
        set_son_of_anton_mode(d.name, False)
        # engine's in-memory flag was left True by the bypass run — the next
        # gated run must re-read the DB and block again
        rec = eng.run_job(eng.by_id("gated"))
        self.assertEqual(rec.exit, 5)


class TestProviderPrerequisiteGate(unittest.TestCase):
    """A job whose routed executor/provider structurally cannot succeed must
    record one honest skip-with-reason (exit 6, skipped:no-provider) — not an
    endless stream of exit-1 subprocess failures at cron cadence."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(self.jobs_path, "w", encoding="utf-8") as f:
            f.write("- id: cron-job\n  trigger: { type: cron, expr: \"*/15 * * * *\" }\n"
                    "  recipe: some-recipe\n")
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        # A real-executor-shaped stub: available(), not the FakeExecutor the
        # gate exempts.
        from anton.executor.base import Executor

        class StubPiExecutor(Executor):
            def available(self):
                return True
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                raise AssertionError("executor.run must never be reached when blocked")
        self.executor = StubPiExecutor()
        # OLLAMA_HOST is already pinned at an unreachable port for the whole
        # suite (tests/conftest.py) and restored per test, so this class no
        # longer juggles it by hand. 127.0.0.1:59999 also sat inside macOS's
        # ephemeral port range, where something could legitimately be
        # listening.

    def tearDown(self):
        self.dir.cleanup()

    def _engine(self, executor=None):
        return JobEngine(load_jobs(self.jobs_path), self.ledger,
                         executor or self.executor, load_config(),
                         data_dir=self.dir.name)

    def test_unreachable_local_provider_records_skip_once(self):
        engine = self._engine()
        rec = engine.run_job(engine.by_id("cron-job"))
        self.assertEqual(rec.exit, 6)
        self.assertIn("skipped:no-provider", rec.flags)
        # Follows whatever the suite pins OLLAMA_HOST to (tests/conftest.py)
        # rather than restating a literal that has to be kept in sync.
        self.assertIn(f"nothing listening on {os.environ['OLLAMA_HOST']}", rec.output)
        row = self.ledger.last_run("cron-job")
        self.assertIsNotNone(row)
        self.assertEqual(row["exit"], 6)
        self.assertEqual(row["output"], rec.output)
        # condition persists -> suppressed, no new ledger rows
        for _ in range(3):
            engine.run_job(engine.by_id("cron-job"))
        self.assertEqual(len([r for r in self.ledger.read()
                              if r.get("task") == "cron-job"]), 1)

    def test_missing_cloud_key_blocks_dispatch_with_reason(self):
        job = load_jobs(self.jobs_path)[0]
        job.model_route = "cloud"
        engine = self._engine()
        saved = {k: os.environ.get(k) for k in ("OPENROUTER_API_KEY",)}
        for k in saved:
            os.environ.pop(k, None)
        try:
            rec = engine.run_job(job)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)
        self.assertEqual(rec.exit, 6)
        self.assertIn("skipped:no-provider", rec.flags)
        self.assertIn("OPENROUTER_API_KEY", rec.output)

    def test_unavailable_executor_records_skip(self):
        from anton.executor.base import Executor

        class GoneExecutor(Executor):
            def available(self):
                return False
            def run(self, task, **kw):  # pragma: no cover
                raise AssertionError("unavailable executor must not run")
        engine = self._engine(GoneExecutor())
        rec = engine.run_job(engine.by_id("cron-job"))
        self.assertEqual(rec.exit, 6)
        self.assertIn("unavailable", rec.output)

    def test_recovered_provider_runs_again_after_skip(self):
        engine = self._engine()
        self.assertEqual(engine.run_job(engine.by_id("cron-job")).exit, 6)
        # provider comes back: last ledger row still says skipped, so the next
        # run must actually execute (and overwrite the skip as latest state).
        from anton.executor.fake import FakeExecutor
        healthy_engine = JobEngine(load_jobs(self.jobs_path), self.ledger,
                                   FakeExecutor(), load_config(),
                                   data_dir=self.dir.name)
        rec = healthy_engine.run_job(healthy_engine.by_id("cron-job"))
        self.assertEqual(rec.exit, 0)
        row = self.ledger.last_run("cron-job")
        self.assertEqual(row["exit"], 0)
        self.assertNotIn("skipped:no-provider", row["flags"])


def _tags_response(names: list[str]) -> "io.BytesIO":
    """A fake urlopen() context manager response for /api/tags."""
    body = json.dumps({"models": [{"name": n} for n in names]}).encode()
    return io.BytesIO(body)


class TestOllamaModelAvailabilityGate(unittest.TestCase):
    """_provider_block's TCP check only proves something is listening on the
    Ollama port -- not that the CONFIGURED model is actually pulled there.
    Found on a real machine: routes.local_model pointed at a model that was
    never `ollama pull`ed, so every local dispatch reached a live Ollama and
    still failed (pi's provider client 404s), burning the run as an opaque
    exit 1 instead of a clear skip. Ollama itself is real and reachable in
    every test below (self._reachable patches only _tcp_reachable's result,
    not the process) -- these tests isolate the NEW check, /api/tags."""

    def _job_engine(self, model_tag: str):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        init_db(os.path.join(d.name, "isolation.db"))
        jobs_path = os.path.join(d.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write("- id: local-job\n  trigger: { type: cron, expr: \"*/15 * * * *\" }\n"
                    "  recipe: r\n")
        cfg = load_config()
        cfg["routes"]["local_model"] = model_tag
        from anton.executor.base import Executor

        class StubPiExecutor(Executor):
            def available(self):
                return True
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                raise AssertionError("run() must not be reached when the model is missing")
        ledger = Ledger(os.path.join(d.name, "runs.jsonl"))
        return JobEngine(load_jobs(jobs_path), ledger, StubPiExecutor(), cfg, data_dir=d.name), ledger

    def test_unit_missing_model_is_detected(self):
        with patch("urllib.request.urlopen", return_value=_tags_response(["phi4:latest"])):
            self.assertTrue(_ollama_model_missing("h", 1, "ollama/llama3.1:8b"))

    def test_unit_present_model_is_not_missing(self):
        with patch("urllib.request.urlopen",
                   return_value=_tags_response(["llama3.1:8b", "phi4:latest"])):
            self.assertFalse(_ollama_model_missing("h", 1, "ollama/llama3.1:8b"))

    def test_unit_a_probe_failure_does_not_add_a_new_block(self):
        # _tcp_reachable already owns "Ollama is down"; this check must stay
        # silent on ambiguous evidence rather than invent a second reason.
        with patch("urllib.request.urlopen", side_effect=OSError("connection reset")):
            self.assertFalse(_ollama_model_missing("h", 1, "ollama/llama3.1:8b"))

    def test_unit_an_empty_tags_list_does_not_add_a_new_block(self):
        with patch("urllib.request.urlopen", return_value=_tags_response([])):
            self.assertFalse(_ollama_model_missing("h", 1, "ollama/llama3.1:8b"))

    def test_unit_malformed_json_does_not_add_a_new_block(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"not json")):
            self.assertFalse(_ollama_model_missing("h", 1, "ollama/llama3.1:8b"))

    def test_dispatch_skips_with_a_pull_instruction_when_the_model_is_missing(self):
        engine, ledger = self._job_engine("ollama/totally-fake-model:1b")
        with patch("anton.scheduler._tcp_reachable", return_value=True), \
             patch("urllib.request.urlopen", return_value=_tags_response(["phi4:latest"])):
            rec = engine.run_job(engine.by_id("local-job"))
        self.assertEqual(rec.exit, 6)
        self.assertIn("skipped:no-provider", rec.flags)
        self.assertIn("not pulled", rec.output)
        self.assertIn("ollama pull totally-fake-model:1b", rec.output)

    def test_dispatch_proceeds_past_the_gate_when_the_model_is_present(self):
        engine, ledger = self._job_engine("ollama/llama3.1:8b")
        with patch("anton.scheduler._tcp_reachable", return_value=True), \
             patch("urllib.request.urlopen",
                   return_value=_tags_response(["llama3.1:8b"])):
            # StubPiExecutor.run() raises if reached -- reaching it (rather
            # than a skip) IS the assertion that the gate let this through.
            with self.assertRaises(AssertionError):
                engine.run_job(engine.by_id("local-job"))
