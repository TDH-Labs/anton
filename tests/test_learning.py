import os
import sqlite3
import tempfile
import unittest
from harbor.learning import author_skill, extract_playbook


class TestLearning(unittest.TestCase):
    def test_author_skill_vercel_contract(self):
        with tempfile.TemporaryDirectory() as d:
            slug = author_skill(title="Optimal Stopping Decider",
                                description="Decide when to stop researching.",
                                condition="research loop detected",
                                steps=("Set horizon", "Compute threshold", "Commit"),
                                out_dir=d)
            self.assertEqual(slug, "optimal-stopping-decider")
            with open(os.path.join(d, "SKILL.md")) as f:
                content = f.read()
            for field in ("name:", "description:", "author: Hyperagent-Autonomous-Builder",
                          "compatibility:", "room_scope:", "Operational Directive",
                          "Algorithmic Procedure", "Execution Artifact"):
                self.assertIn(field, content)
            ev = os.path.join(d, "scripts", f"{slug}_evaluator.py")
            self.assertTrue(os.path.exists(ev))
            import subprocess
            self.assertEqual(subprocess.run(["python3", ev, "4"], capture_output=True).returncode, 0)

    def test_extract_playbook(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "isolation.db")
            extract_playbook(db, task="reconcile-unapplied-payments", exit_code=0,
                             flags="dry-run", method="re-read-before-write; cap=min(unapplied,balance)")
            conn = sqlite3.connect(db)
            row = conn.execute("SELECT slug, method FROM playbooks").fetchone()
            conn.close()
            self.assertEqual(row[0], "reconcile-unapplied-payments")
            self.assertIn("re-read-before-write", row[1])
