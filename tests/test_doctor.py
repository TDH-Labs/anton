import os
import tempfile
import unittest
from unittest.mock import patch
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

    @patch("anton.executor.pi_executor.shutil.which", return_value=None)
    @patch("anton.executor.oi_executor.shutil.which", return_value=None)
    @patch("anton.executor.opencode_executor.shutil.which", return_value=None)
    def test_fake_executor_is_ok_even_with_no_agent_binaries_installed(self, *_mocks):
        # This is the exact bug a bare CI runner (no pi/oi/opencode on PATH)
        # surfaced: doctor used to hard-fail on pi/oi being absent
        # regardless of which executor the install actually uses. A `fake`
        # install needs none of them.
        with tempfile.TemporaryDirectory() as d:
            run_setup(d, executor="fake")
            lines, ok = run_doctor(os.path.join(d, "data"), executor_name="fake")
            self.assertTrue(ok)
            joined = "\n".join(lines)
            self.assertIn("· executor pi — binary not installed", joined)

    @patch("anton.executor.pi_executor.shutil.which", return_value=None)
    def test_configured_executor_missing_its_binary_fails_the_check(self, _mock_which):
        # The other side of the same fix: the check still means something
        # for the executor that's actually configured.
        with tempfile.TemporaryDirectory() as d:
            run_setup(d, executor="fake")
            lines, ok = run_doctor(os.path.join(d, "data"), executor_name="pi")
            self.assertFalse(ok)
            self.assertIn("✗ executor pi (configured)", "\n".join(lines))
