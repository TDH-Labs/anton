"""dsh_bridge: Anton's saved provider keys must reach the dsh web host's own
settings document (llm-pi-ai profiles, .credentials.yaml, agent-default-model)
so the chat composer reflects what the user configured — hot-reloaded there,
no restart."""

import os
import unittest

from anton.dsh_bridge import sync_dsh_settings


class TestDshBridge(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="anton-dsh-bridge-")
        self.data_dir = os.path.join(self.tmp, "data")
        os.makedirs(self.data_dir)
        self.home = os.path.join(self.tmp, "dsh-home")
        os.environ["DSH_HOME"] = self.home
        with open(os.path.join(self.data_dir, "secrets.yaml"), "w") as f:
            f.write("openrouter: sk-or-test\n")

    def tearDown(self):
        os.environ.pop("DSH_HOME", None)

    def _settings(self):
        import yaml
        with open(os.path.join(self.home, "settings.yaml")) as f:
            return yaml.safe_load(f) or {}

    def _creds(self):
        import yaml
        with open(os.path.join(self.home, ".credentials.yaml")) as f:
            return yaml.safe_load(f) or {}

    def test_registers_route_and_credential(self):
        config = {"routes": {"prefer": "local", "cloud_model": ""}}
        notes = sync_dsh_settings(self.data_dir, config)
        self.assertTrue(notes)
        settings = self._settings()
        profile = settings["llm-pi-ai"]["providers"]["openrouter"]
        self.assertEqual(profile["apiKeyEnv"], "OPENROUTER_API_KEY")
        self.assertEqual(self._creds().get("OPENROUTER_API_KEY"), "sk-or-test")
        # no default-model section without an actual cloud pick
        self.assertNotIn("agent-default-model", settings)

    def test_credentials_document_is_owner_only(self):
        import stat as statmod
        sync_dsh_settings(self.data_dir, {"routes": {}})
        mode = statmod.S_IMODE(os.stat(os.path.join(self.home, ".credentials.yaml")).st_mode)
        self.assertEqual(mode, 0o600)

    def test_cloud_model_picks_custom_route_and_default_model(self):
        config = {"routes": {"prefer": "cloud",
                             "cloud_model": "openrouter/ox-alpha"}}
        sync_dsh_settings(self.data_dir, config)
        settings = self._settings()
        custom = settings["llm-pi-ai"]["providers"]["openrouter-custom"]
        self.assertEqual(custom["baseURL"], "https://openrouter.ai/api/v1")
        self.assertEqual([m["id"] for m in custom["models"]], ["ox-alpha"])
        self.assertEqual(settings["agent-default-model"],
                         {"provider": "openrouter-custom", "model": "ox-alpha"})

    def test_merges_with_existing_settings_document(self):
        settings_path = os.path.join(self.home, "settings.yaml")
        os.makedirs(self.home, exist_ok=True)
        with open(settings_path, "w") as f:
            f.write("conversation:\n  enterBehavior: send\n")
        sync_dsh_settings(self.data_dir, {"routes": {}})
        settings = self._settings()
        self.assertEqual(settings["conversation"]["enterBehavior"], "send")
        self.assertIn("openrouter", settings["llm-pi-ai"]["providers"])

    def test_idempotent_second_run_changes_nothing(self):
        config = {"routes": {"prefer": "cloud",
                             "cloud_model": "openrouter/ox-alpha"}}
        first = sync_dsh_settings(self.data_dir, config)
        second = sync_dsh_settings(self.data_dir, config)
        self.assertTrue(first)
        self.assertEqual(second, [])

    def test_no_saved_keys_is_a_clean_noop(self):
        os.remove(os.path.join(self.data_dir, "secrets.yaml"))
        notes = sync_dsh_settings(self.data_dir, {"routes": {}})
        self.assertEqual(notes, [])
        self.assertFalse(os.path.exists(os.path.join(self.home, "settings.yaml")))


if __name__ == "__main__":
    unittest.main()
