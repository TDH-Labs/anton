import os
import sqlite3
import stat
import tempfile
import unittest
from anton.config import load_config
from anton.setup import run_setup


class TestSetup(unittest.TestCase):
    def test_run_setup_provisions_install(self):
        with tempfile.TemporaryDirectory() as d:
            info = run_setup(d, executor="fake", provider_keys={"OPENROUTER_API_KEY": "sk-test"})
            for f in ("config.yaml", "secrets.yaml"):
                self.assertTrue(os.path.exists(os.path.join(d, f)))
            for f in ("jobs.yaml", "runs.jsonl"):
                pass
            self.assertTrue(os.path.exists(os.path.join(info["data_dir"], "jobs.yaml")))
            self.assertTrue(os.path.exists(os.path.join(info["data_dir"], "isolation.db")))
            self.assertTrue(os.path.exists(os.path.join(info["vault"], "index.md")))
            self.assertTrue(os.path.exists(os.path.join(info["vault"], "vault.db")))
            mode = os.stat(os.path.join(d, "secrets.yaml")).st_mode
            self.assertEqual(stat.S_IMODE(mode), stat.S_IRUSR | stat.S_IWUSR)
            conn = sqlite3.connect(os.path.join(info["data_dir"], "isolation.db"))
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertIn("approvals", tables)
            self.assertIn("metering", tables)

    def test_default_jobs_seed_only_webhook_triggered_job(self):
        # Fresh installs must not seed cron jobs whose only execution path is
        # an LLM call that structurally cannot succeed out-of-the-box (the old
        # e2e-canary / daily-digest seeds spammed exit-1 ledger rows at cron
        # cadence on any install without a reachable provider).
        with tempfile.TemporaryDirectory() as d:
            info = run_setup(d)
            import yaml
            with open(os.path.join(info["data_dir"], "jobs.yaml"), encoding="utf-8") as f:
                jobs = yaml.safe_load(f) or []
            self.assertEqual([j["id"] for j in jobs], ["smoke-hook"])
            self.assertEqual(jobs[0]["trigger"]["type"], "webhook")

    def test_run_setup_persists_executor_choice_to_disk(self):
        # run_setup() used to mutate the loaded config dict's executor field
        # and discard it without writing back — config.yaml always kept
        # DEFAULT_CONFIG_YAML's literal "executor: pi" regardless of what was
        # passed here.
        with tempfile.TemporaryDirectory() as d:
            info = run_setup(d, executor="ssh")
            self.assertEqual(info["executor"], "ssh")
            on_disk = load_config(info["config"])
            self.assertEqual(on_disk["general"]["executor"], "ssh")

    def test_run_setup_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            run_setup(d)
            cfg1 = open(os.path.join(d, "config.yaml")).read()
            run_setup(d)
            cfg2 = open(os.path.join(d, "config.yaml")).read()
            self.assertEqual(cfg1, cfg2)  # no clobber without --force

    def test_run_setup_seeds_and_indexes_all_three_standard_meta_skills(self):
        with tempfile.TemporaryDirectory() as d:
            info = run_setup(d)
            for slug in ("upskill-from-research", "upskill-from-experience", "meta-learning"):
                self.assertTrue(os.path.exists(
                    os.path.join(info["data_dir"], "skills", slug, "SKILL.md")))
            conn = sqlite3.connect(os.path.join(info["data_dir"], "isolation.db"))
            indexed = {r[0] for r in conn.execute("SELECT skill_slug FROM skill_dependencies")}
            conn.close()
            self.assertIn("upskill-from-research", indexed)
            self.assertIn("upskill-from-experience", indexed)
            self.assertIn("meta-learning", indexed)
