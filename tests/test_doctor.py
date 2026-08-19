import os
import tempfile
import unittest
from anton.doctor import run_doctor
from anton.setup import run_setup


class TestDoctor(unittest.TestCase):
    def test_doctor_reports_ok_on_fresh_install(self):
        with tempfile.TemporaryDirectory() as d:
            run_setup(d, executor="fake")
            lines, ok = run_doctor(os.path.join(d, "data"))
            joined = "\n".join(lines)
            self.assertTrue(ok)
            self.assertIn("✓ python", joined)
            self.assertIn("✓ jobs parse", joined)
            self.assertIn("✓ db isolation.db — ok", joined)
            self.assertIn("✓ vault index", joined)
