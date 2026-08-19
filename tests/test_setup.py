import os
import sqlite3
import stat
import tempfile
import unittest
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

    def test_run_setup_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            run_setup(d)
            cfg1 = open(os.path.join(d, "config.yaml")).read()
            run_setup(d)
            cfg2 = open(os.path.join(d, "config.yaml")).read()
            self.assertEqual(cfg1, cfg2)  # no clobber without --force
