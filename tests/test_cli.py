import argparse
import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

from anton.cli import _load_secrets_into_env, cmd_serve
from anton.config import load_config


class TestLoadSecretsIntoEnv(unittest.TestCase):
    def setUp(self):
        self._saved_env = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_saved_provider_key_reaches_the_matching_env_var(self):
        # secrets.yaml written by POST /api/wizard/providers keyed by
        # provider name (dashboard.py's save_provider_key); this must map
        # that to the exact env var pi's own subprocess call reads.
        with tempfile.TemporaryDirectory() as install_dir:
            data_dir = os.path.join(install_dir, "data")
            os.makedirs(data_dir)
            secrets_path = os.path.join(install_dir, "secrets.yaml")
            with open(secrets_path, "w", encoding="utf-8") as f:
                yaml.safe_dump({"anthropic": "sk-test-123"}, f)
            os.environ.pop("ANTHROPIC_API_KEY", None)
            _load_secrets_into_env(data_dir)
            self.assertEqual(os.environ.get("ANTHROPIC_API_KEY"), "sk-test-123")

    def test_unknown_provider_name_is_ignored_not_crashed(self):
        with tempfile.TemporaryDirectory() as install_dir:
            data_dir = os.path.join(install_dir, "data")
            os.makedirs(data_dir)
            with open(os.path.join(install_dir, "secrets.yaml"), "w", encoding="utf-8") as f:
                yaml.safe_dump({"some-future-provider": "sk-test"}, f)
            _load_secrets_into_env(data_dir)  # must not raise

    def test_missing_secrets_file_is_a_noop(self):
        with tempfile.TemporaryDirectory() as install_dir:
            data_dir = os.path.join(install_dir, "data")
            os.makedirs(data_dir)
            _load_secrets_into_env(data_dir)  # must not raise

    def test_does_not_override_an_env_var_already_set(self):
        with tempfile.TemporaryDirectory() as install_dir:
            data_dir = os.path.join(install_dir, "data")
            os.makedirs(data_dir)
            with open(os.path.join(install_dir, "secrets.yaml"), "w", encoding="utf-8") as f:
                yaml.safe_dump({"openai": "sk-from-file"}, f)
            os.environ["OPENAI_API_KEY"] = "sk-from-operator"
            _load_secrets_into_env(data_dir)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "sk-from-operator")


class TestServeLoopReloadsSecrets(unittest.TestCase):
    """A key saved through the setup wizard after `anton serve` has already
    booted lands in secrets.yaml from a *different* process (the dashboard) --
    _load_secrets_into_env must be re-checked on every poll tick, not only
    once before the loop starts, or a freshly-connected provider is silently
    invisible to every scheduled dispatch until the container restarts."""

    @patch("anton.cli.WebhookServer")
    @patch("anton.cli._load_secrets_into_env")
    @patch("anton.cli.time.sleep", side_effect=KeyboardInterrupt)
    def test_reloads_secrets_inside_the_loop_not_only_at_boot(
        self, _mock_sleep, mock_load_secrets, mock_webhook_cls
    ):
        mock_webhook_cls.return_value.port = 8799
        with tempfile.TemporaryDirectory() as data_dir:
            args = argparse.Namespace(data_dir=data_dir, executor="fake", port=None)
            cmd_serve(args, load_config())
        # one call from _build() at startup, one from inside the loop body
        # before the (mocked, immediately-interrupting) sleep -- proves the
        # loop itself re-checks secrets.yaml each tick.
        self.assertGreaterEqual(mock_load_secrets.call_count, 2)
