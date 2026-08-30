"""The suite's environment neutralization is itself under test.

tests/conftest.py exists because ambient developer state -- a local Ollama,
provider keys, vendor OAuth credentials under $HOME -- silently changed what
scheduler._provider_block decided, so bugs passed locally and failed only on
CI. That protection is invisible: nothing else fails if someone deletes the
conftest, and the suite goes back to lying. These tests make that loud.
"""
from __future__ import annotations

import os
import unittest

from anton.scheduler import _local_endpoint, _tcp_reachable


class TestEnvironmentIsSuiteControlled(unittest.TestCase):
    def test_the_local_model_endpoint_is_pinned_unreachable(self):
        host, port = _local_endpoint()
        self.assertFalse(
            _tcp_reachable(host, port, timeout_s=0.25),
            f"a local model server is reachable at {host}:{port} during tests. "
            "Every dispatch gated on a local route will now behave differently "
            "here than on CI. tests/conftest.py should have pinned OLLAMA_HOST.")

    def test_no_provider_api_key_is_visible(self):
        leaked = [name for name in (
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
            "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
            "MISTRAL_API_KEY", "XAI_API_KEY") if os.environ.get(name)]
        self.assertEqual(
            leaked, [],
            f"provider keys visible to the suite: {leaked}. A cloud-routed job "
            "will dispatch here and be skipped on CI.")

    def test_home_is_not_the_developers_real_home(self):
        # qbo_oauth reads ~/.secrets/qbo_vendor.json and ~/secrets/... ; those
        # are credential legs no env var covers.
        home = os.environ.get("HOME", "")
        self.assertIn("anton-test-home-", home,
                      f"$HOME is {home!r} -- credential files under the real "
                      "home directory are reachable from tests.")


if __name__ == "__main__":
    unittest.main()
