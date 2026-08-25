import os
import tempfile
import unittest

from anton import experience, upskill
from anton.config import load_config
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.executor.base import RunResult
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.models import RunRecord
from anton.scheduler import JobEngine
from anton.vault import provision_vault

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
"""


class WritingExecutor(FakeExecutor):
    """Same pattern as test_upskill.py's double: writes a valid distillation
    regardless of prompt content. Subclasses FakeExecutor so _dispatch's
    provider-prerequisite gate exempts it (see test_upskill.py's identical
    fix)."""

    def __init__(self, out_dir: str, slug: str):
        self.out_dir = out_dir
        self.slug = slug

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        os.makedirs(os.path.join(self.out_dir, "scripts"), exist_ok=True)
        with open(os.path.join(self.out_dir, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(
                f"---\nname: {self.slug}\ndescription: fixed the thing\n---\n\n"
                "# Fix\n\n## Do\nx\n\n## Don't\ny\n\n## Measure\nz\n\n## Validation\nw\n"
            )
        script = os.path.join(self.out_dir, "scripts", f"{self.slug}_evaluator.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(
                "import sys\n"
                "def evaluate(x):\n    return x > 0.5\n\n"
                "if __name__ == '__main__':\n"
                "    if len(sys.argv) > 1 and sys.argv[1] == '--selftest':\n"
                "        assert evaluate(0.9) is True\n"
                "        assert evaluate(0.1) is False\n"
                "        sys.exit(0)\n"
                "    sys.exit(0)\n"
            )
        return RunResult(exit_code=0, output="ok", stderr="", duration_ms=1,
                         model=model, provider=provider)


class ExperienceTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = self.dir.name
        init_db(os.path.join(self.data_dir, "isolation.db"))
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        provision_vault(os.path.join(self.data_dir, "vault"))
        self.ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(),
                                load_config(), data_dir=self.data_dir)

    def tearDown(self):
        self.dir.cleanup()


class TestGatherFailureSamples(ExperienceTestBase):
    def test_only_failures_for_the_named_task(self):
        self.ledger.append(RunRecord.new(task="widget-sync", exit_code=1, output="boom"))
        self.ledger.append(RunRecord.new(task="widget-sync", exit_code=0, output="ok"))
        self.ledger.append(RunRecord.new(task="other-task", exit_code=1, output="unrelated"))
        samples = experience.gather_failure_samples(self.ledger, "widget-sync")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0]["output"], "boom")

    def test_most_recent_first_and_bounded_by_limit(self):
        for i in range(7):
            self.ledger.append(RunRecord.new(task="widget-sync", exit_code=1, output=f"fail-{i}",
                                             ts=f"2026-01-0{i + 1}T00:00:00Z"))
        samples = experience.gather_failure_samples(self.ledger, "widget-sync", limit=3)
        self.assertEqual(len(samples), 3)
        self.assertEqual(samples[0]["output"], "fail-6")


class TestDispatchExperienceIteration(ExperienceTestBase):
    def test_no_failure_samples_is_insufficient_not_a_crash(self):
        result = experience.dispatch_experience_iteration(self.engine, "never-failed-task")
        self.assertEqual(result.status, "insufficient_research")

    def test_real_failure_evidence_is_required_before_dispatch(self):
        # even with a real failure present, FakeExecutor writes nothing --
        # confirms this path also never fabricates a promotion from thin air.
        self.ledger.append(RunRecord.new(task="widget-sync", exit_code=1, output="boom"))
        result = experience.dispatch_experience_iteration(self.engine, "widget-sync")
        self.assertIn(result.status, ("sandbox_failed",))

    def test_promotes_when_diagnosis_produces_a_valid_distillation(self):
        self.ledger.append(RunRecord.new(task="widget-sync", exit_code=1, output="boom"))
        slug = upskill.slugify("widget-sync")
        out_dir = os.path.join(self.data_dir, "staging", slug)
        self.engine.executor = WritingExecutor(out_dir, slug)
        result = experience.dispatch_experience_iteration(self.engine, "widget-sync")
        self.assertEqual(result.status, "promoted")
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "skills", slug, "SKILL.md")))

    def test_skipped_dispatch_does_not_bank_a_false_dont_lesson(self):
        # No provider -> out_dir is never touched by _dispatch. Before the
        # fix, dispatch_experience_iteration called validate_distilled_skill
        # unconditionally right after _dispatch, so the skip read as "the
        # diagnosis produced invalid output" and banked a permanent false
        # 'dont' lesson blaming the diagnosis for a stage never attempted.
        from anton.executor.base import Executor
        from anton.learning import unconsumed_lessons

        class StubRealExecutor(Executor):
            def available(self):
                return True
            def run(self, task, *, model, provider, cwd=None, timeout_s=None):
                raise AssertionError("executor.run must never be reached when blocked")
        self.engine.executor = StubRealExecutor()
        old_key = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            self.ledger.append(RunRecord.new(task="widget-sync", exit_code=1, output="boom"))
            result = experience.dispatch_experience_iteration(self.engine, "widget-sync")
            self.assertEqual(result.status, "skipped_no_provider")
            db_path = os.path.join(self.data_dir, "isolation.db")
            self.assertEqual(unconsumed_lessons(db_path, result.slug), [])
        finally:
            if old_key is not None:
                os.environ["OPENROUTER_API_KEY"] = old_key


if __name__ == "__main__":
    unittest.main()
