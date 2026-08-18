import os
import sqlite3
import tempfile
import unittest
from harbor.sandbox import promote, run_sandbox_gate

BAD = "def broken(:\n    pass\n"
GOOD = """import sys
def evaluate(x: float) -> float:
    return x * 2
if __name__ == "__main__":
    print(evaluate(float(sys.argv[1])))
"""


class TestSandbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_syntax_failure_logged(self):
        p = os.path.join(self.dir.name, "bad.py")
        open(p, "w").write(BAD)
        db = os.path.join(self.dir.name, "isolation.db")
        self.assertFalse(run_sandbox_gate(p, db_path=db, slug="bad-skill"))
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT slug, stage, ok FROM sandbox_log").fetchone()
        conn.close()
        self.assertEqual(row, ("bad-skill", "py_compile", 0))

    def test_good_script_passes_and_promotes(self):
        p = os.path.join(self.dir.name, "good.py")
        open(p, "w").write(GOOD)
        self.assertTrue(run_sandbox_gate(p, golden_payload="3"))
        skills = os.path.join(self.dir.name, "skills")
        dst = promote(p, skills, slug="good-skill")
        self.assertTrue(os.path.exists(dst))
        self.assertTrue(dst.endswith("good-skill/good.py"))
