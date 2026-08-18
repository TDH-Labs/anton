import os
import sqlite3
import tempfile
import unittest
from harbor.learning import author_skill


class TestSkillsIndex(unittest.TestCase):
    def test_index_populates_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            # build a skills dir with one promoted skill
            out = os.path.join(d, "staging")
            slug = author_skill(title="Bayesian Predictor",
                                description="Update beliefs from evidence.",
                                condition="new evidence",
                                steps=("Set prior", "Update", "Act"), out_dir=out)
            skills_dir = os.path.join(d, "skills")
            from harbor.sandbox import promote
            promote(os.path.join(out, "scripts", f"{slug}_evaluator.py"), skills_dir, slug=slug)
            import shutil
            shutil.copy2(os.path.join(out, "SKILL.md"),
                         os.path.join(skills_dir, slug, "SKILL.md"))  # cmd_skills does this too

            from harbor.cli import _index_skills
            rc = _index_skills(d)
            self.assertEqual(rc, 0)
            conn = sqlite3.connect(os.path.join(d, "isolation.db"))
            row = conn.execute("SELECT skill_slug, target_capability FROM skill_dependencies").fetchone()
            conn.close()
            self.assertEqual(row[0], "bayesian-predictor")
            self.assertIn("beliefs", row[1])
