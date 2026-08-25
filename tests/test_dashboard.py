import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from anton import browser_vault
from anton.browser_login import LoginResult
from anton.config import load_config
from anton.dashboard import create_app
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine
from anton.vault import provision_vault

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
  expected_cadence_min: 5
"""


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.dir.name, "isolation.db"))
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(), load_config())
        provision_vault(os.path.join(self.dir.name, "vault"))
        self.engine.run_job(self.engine.by_id("e2e-canary"),
                            now=dt.datetime.now(dt.timezone.utc))
        app = create_app(self.engine, self.dir.name, load_config())
        self.client = TestClient(app)

    def tearDown(self):
        self.dir.cleanup()

    def test_index_page(self):
        # This port is never published in the real Docker deployment -- the
        # Ops Center at :3080 is. This is just the honest "you're on the
        # wrong port" landing page, not a real UI (see dashboard.py's PAGE
        # comment for why the old fake-demo chat prototype was removed).
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Anton", r.text)
        self.assertIn("3080", r.text)

    def test_n8n_config_defaults_to_unset(self):
        r = self.client.get("/api/n8n/config")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["base_url"])

    def test_ledger_api(self):
        r = self.client.get("/api/ledger")
        self.assertEqual(r.status_code, 200)
        rows = r.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task"], "e2e-canary")
        self.assertIn("model", rows[0])  # R9 fields served

    def test_canary_and_usage(self):
        self.assertEqual(self.client.get("/api/canary").json(), [])
        u = self.client.get("/api/usage").json()
        self.assertEqual(u["cloud_runs"], 0)

    def test_approval_flow_writes_only_table(self):
        r = self.client.post("/api/approvals", json={"action": "move_20k_transfer",
                                                     "amount": "20000", "recipient": "vendor"})
        self.assertEqual(r.status_code, 200)
        aid = r.json()["id"]
        # pending visible
        pending = self.client.get("/api/approvals").json()
        self.assertEqual(len(pending), 1)
        # resolve approve
        r = self.client.post(f"/api/approvals/{aid}/resolve", json={"decision": "approve"})
        self.assertEqual(r.status_code, 200)
        # no longer pending, and no job executed anywhere
        self.assertEqual(self.client.get("/api/approvals").json(), [])
        rows = self.ledger.read()
        self.assertEqual(len(rows), 1)  # only the canary run; approval never executed

    def test_digest_endpoint(self):
        r = self.client.get("/api/digest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("## 1. Fleet status", r.text)

    def test_vault_graph_before_vault_db_exists_is_honest_not_fabricated(self):
        # This test's own setUp already provisions vault.db (provision_vault),
        # so it doesn't exercise the "vault.db doesn't exist at all yet"
        # branch -- build a separate app against a data_dir where it
        # genuinely doesn't, matching the real state of a container between
        # first boot and the vault's first provisioning step.
        with tempfile.TemporaryDirectory() as fresh_dir:
            fresh_engine = JobEngine([], Ledger(os.path.join(fresh_dir, "runs.jsonl")),
                                     FakeExecutor(), load_config(), data_dir=fresh_dir)
            fresh_app = create_app(fresh_engine, fresh_dir, load_config())
            fresh_client = TestClient(fresh_app)
            r = fresh_client.get("/api/vault/graph")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        titles = [n["title"] for n in body["nodes"]]
        self.assertNotIn("Operations MOC", titles)
        self.assertEqual(titles, ["Second Brain Root"])

    def test_chat_dispatches_through_the_real_executor_not_a_keyword_stub(self):
        # /api/chat used to keyword-match ("reconcil"/"award"/"skill") into
        # fabricated canned replies -- these prompts would each have hit a
        # different fake branch before. Now every one must show real
        # dispatch: FakeExecutor echoes the actual prompt back, so the reply
        # containing it (rather than one of the old fixed fake strings)
        # proves the real path is used regardless of prompt content.
        for prompt in ("please reconcile the accounts", "plan the award campaign",
                       "what skill should I learn", "anything else entirely"):
            r = self.client.post("/api/chat", json={"prompt": prompt})
            self.assertEqual(r.status_code, 200)
            self.assertIn(prompt, r.json()["reply"])
            self.assertNotIn("Second Brain", r.json()["reply"])

    def test_chat_is_ledger_accounted(self):
        self.client.post("/api/chat", json={"prompt": "hello"})
        rows = self.ledger.read()
        self.assertIn("chat", [row["task"] for row in rows])

    def test_mcp_register_room_default_is_generic_not_a_leaked_personal_default(self):
        r = self.client.post("/api/wizard/mcp", json={"name": "quickbooks", "command": "run"})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["room"], "devops")

    def test_seeded_mcp_defaults_have_no_leaked_room_value(self):
        import sqlite3
        self.client.get("/api/wizard/mcp")  # triggers the first-read seed of the two defaults
        conn = sqlite3.connect(os.path.join(self.dir.name, "isolation.db"))
        rooms = [r[0] for r in conn.execute("SELECT room FROM mcp_servers")]
        conn.close()
        self.assertTrue(rooms)  # the seed actually ran
        self.assertNotIn("devops", rooms)

    def test_oauth_start_is_honest_when_no_app_is_registered(self):
        # No oauth.<provider>.client_id is configured here. On a machine
        # with NO provisioned credentials anywhere (config/env/secrets.env)
        # this must say so plainly instead of returning a fake URL. On a
        # machine WITH provisioned vendor credentials (e.g. the reference
        # Mac), a real auth_url is correct behavior — both are honest.
        r = self.client.get("/api/wizard/oauth/start", params={"provider": "quickbooks"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        from anton.qbo_oauth import load_qbo_credentials
        cid, _ = load_qbo_credentials()
        if cid:
            self.assertEqual(body["status"], "listening")
            self.assertIn("state", body)
            self.assertIn("appcenter.intuit.com", body["auth_url"])
        else:
            self.assertEqual(body["status"], "not_configured")

    def test_oauth_start_unknown_provider_is_also_honest(self):
        r = self.client.get("/api/wizard/oauth/start", params={"provider": "some-unknown-service"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "not_configured")

    def test_mcp_register_with_api_key_saves_it_to_secrets_yaml(self):
        r = self.client.post("/api/wizard/mcp", json={
            "name": "QuickBooks", "command": "n/a", "what": "accounting data", "api_key": "sk-qbo-test-1",
        })
        self.assertEqual(r.status_code, 200)
        import yaml
        # _save_secret writes inside data_dir (volume-root safe), matching
        # how the wizard's own provider-key save works.
        secrets_path = os.path.join(self.dir.name, "secrets.yaml")
        self.assertTrue(os.path.exists(secrets_path))
        with open(secrets_path) as f:
            saved = yaml.safe_load(f)
        self.assertEqual(saved.get("mcp:quickbooks"), "sk-qbo-test-1")

    def test_mcp_register_without_api_key_does_not_touch_secrets(self):
        r = self.client.post("/api/wizard/mcp", json={"name": "no-key-service", "command": "n/a"})
        self.assertEqual(r.status_code, 200)
        import yaml
        for candidate in (os.path.join(self.dir.name, "secrets.yaml"),
                          os.path.join(os.path.dirname(self.dir.name), "secrets.yaml")):
            if os.path.exists(candidate):
                with open(candidate) as f:
                    saved = yaml.safe_load(f) or {}
                self.assertNotIn("mcp:no-key-service", saved)

    def test_browser_login_success_stores_credential_and_activates(self):
        with patch("anton.browser_login.perform_login",
                   return_value=LoginResult("success", "logged in")) as mock_login:
            r = self.client.post("/api/wizard/browser-login", json={
                "name": "QuickBooks Portal", "login_url": "https://example.com/login",
                "username": "alice", "password": "hunter2",
                "success_selector": "#dashboard",
            })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["id"], "quickbooks-portal")
        self.assertNotIn("password", body)
        self.assertNotIn("hunter2", str(body))
        # the real vault, not mocked -- the credential genuinely landed.
        # Stored inside the data dir (volume-root safe).
        self.assertEqual(
            browser_vault.get_credential(self.dir.name, "quickbooks-portal"),
            ("alice", "hunter2"))
        # mock_login called with the real stored credential's service_id
        self.assertEqual(mock_login.call_args.args[1], "quickbooks-portal")

        rows = self.client.get("/api/wizard/mcp").json()
        registered = next(a for a in rows if a["id"] == "quickbooks-portal")
        self.assertEqual(registered["status"], "active")

    def test_browser_login_needs_human_stays_pending(self):
        with patch("anton.browser_login.perform_login",
                   return_value=LoginResult("needs_human", "MFA prompt")):
            r = self.client.post("/api/wizard/browser-login", json={
                "name": "Some Portal", "login_url": "https://example.com/login",
                "username": "alice", "password": "hunter2", "success_selector": "#dashboard",
            })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "needs_human")
        rows = self.client.get("/api/wizard/mcp").json()
        registered = next(a for a in rows if a["id"] == "some-portal")
        self.assertEqual(registered["status"], "pending")

    def test_oauth_start_works_once_a_real_app_is_registered(self):
        app = create_app(self.engine, self.dir.name,
                         {**load_config(), "oauth": {"quickbooks": {"client_id": "real-client-id-123"}}})
        client = TestClient(app)
        r = client.get("/api/wizard/oauth/start", params={"provider": "quickbooks"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "listening")
        self.assertIn("real-client-id-123", body["auth_url"])
        self.assertIn("appcenter.intuit.com", body["auth_url"])


class TestN8NConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.dir.name, "isolation.db"))
        ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), ledger, FakeExecutor(), load_config())
        provision_vault(os.path.join(self.dir.name, "vault"))

    def tearDown(self):
        self.dir.cleanup()

    def test_config_yaml_base_url_is_returned(self):
        config = load_config()
        config["n8n"] = {"base_url": "https://n8n.example.com"}
        client = TestClient(create_app(self.engine, self.dir.name, config))
        r = client.get("/api/n8n/config")
        self.assertEqual(r.json()["base_url"], "https://n8n.example.com")

    @patch.dict(os.environ, {"ANTON_N8N_BASE_URL": "https://from-env.example.com"})
    def test_env_var_used_when_config_yaml_unset(self):
        client = TestClient(create_app(self.engine, self.dir.name, load_config()))
        r = client.get("/api/n8n/config")
        self.assertEqual(r.json()["base_url"], "https://from-env.example.com")

    @patch.dict(os.environ, {"ANTON_N8N_BASE_URL": "https://from-env.example.com"})
    def test_config_yaml_wins_over_env_var(self):
        config = load_config()
        config["n8n"] = {"base_url": "https://from-config.example.com"}
        client = TestClient(create_app(self.engine, self.dir.name, config))
        r = client.get("/api/n8n/config")
        self.assertEqual(r.json()["base_url"], "https://from-config.example.com")


class TestVolumeRootDataDir(unittest.TestCase):
    """Umbrel runs with ANTON_DATA_DIR=/data -- a volume ROOT, so
    os.path.dirname(data_dir) is "/" and every secrets/vault path built from
    it either HTTP-500s or lands somewhere fragile. The container dir here
    plays "/" and is made read-only, so any write that escapes the data dir
    fails loudly instead of silently succeeding like it does on a dev box."""

    def setUp(self):
        self.outer = tempfile.TemporaryDirectory()
        self.addCleanup(self._restore_perms)
        # "/data"-style layout: the data dir IS the volume root's child and
        # the volume root itself must never be written to.
        self.data_dir = os.path.join(self.outer.name, "data")
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        os.makedirs(self.data_dir)
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.data_dir, "isolation.db"))
        ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))
        self.engine = JobEngine(load_jobs(jobs_path), ledger, FakeExecutor(), load_config())
        provision_vault(os.path.join(self.data_dir, "vault"))
        app = create_app(self.engine, self.data_dir, load_config())
        self.client = TestClient(app)

    def lock_volume_root(self):
        """Lock the "volume root" so writes outside the data dir raise
        PermissionError rather than quietly passing. Call after seeding any
        legacy files outside the data dir."""
        os.chmod(self.outer.name, 0o555)

    def _restore_perms(self):
        os.chmod(self.outer.name, 0o755)
        self.outer.cleanup()

    def test_provider_key_save_writes_inside_data_dir_not_volume_root(self):
        # Keep the executor-env side effect out of other tests' process env.
        with patch("anton.cli._load_secrets_into_env"):
            self.lock_volume_root()
            r = self.client.post("/api/wizard/providers", json={
                "provider": "openai", "key": "sk-volume-root-test",
                "model": "", "base_url": ""})
        self.assertEqual(r.status_code, 200, r.text)
        import yaml
        secrets_path = os.path.join(self.data_dir, "secrets.yaml")
        self.assertTrue(os.path.exists(secrets_path))
        with open(secrets_path) as f:
            saved = yaml.safe_load(f) or {}
        self.assertEqual(saved.get("openai"), "sk-volume-root-test")
        # And /secrets.yaml (the old dirname(data_dir) target) was never created.
        self.assertFalse(os.path.exists(os.path.join(self.outer.name, "secrets.yaml")))
        # Settings reads back what was just saved.
        keys = self.client.get("/api/wizard/keys").json()
        self.assertTrue(keys["have_key"].get("openai"))

    def test_provider_key_save_merges_legacy_secrets_yaml(self):
        """Pre-upgrade installs keep their secrets in dirname(data_dir)/
        secrets.yaml; saving a new key must carry those entries forward."""
        import yaml
        legacy = {"anthropic": "sk-old-anthropic-key"}
        with open(os.path.join(self.outer.name, "secrets.yaml"), "w") as f:
            yaml.safe_dump(legacy, f)
        with patch("anton.cli._load_secrets_into_env"):
            self.lock_volume_root()
            r = self.client.post("/api/wizard/providers", json={
                "provider": "openai", "key": "sk-new-openai-key",
                "model": "", "base_url": ""})
        self.assertEqual(r.status_code, 200, r.text)
        with open(os.path.join(self.data_dir, "secrets.yaml")) as f:
            saved = yaml.safe_load(f) or {}
        self.assertEqual(saved.get("openai"), "sk-new-openai-key")
        self.assertEqual(saved.get("anthropic"), "sk-old-anthropic-key")

    def test_browser_login_credential_stored_inside_data_dir(self):
        self.lock_volume_root()
        with patch("anton.browser_login.perform_login",
                   return_value=LoginResult("success", "logged in")):
            r = self.client.post("/api/wizard/browser-login", json={
                "name": "Vendor Portal", "login_url": "https://example.com/login",
                "username": "alice", "password": "hunter2",
                "success_selector": "#dashboard"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "success")
        # Readable through the data-dir base...
        self.assertEqual(
            browser_vault.get_credential(self.data_dir, "vendor-portal"),
            ("alice", "hunter2"))
        # ...and physically inside the data dir, not at the volume root.
        self.assertTrue(os.path.exists(
            os.path.join(self.data_dir, "browser-vault", "vendor-portal.enc")))
        self.assertFalse(os.path.exists(
            os.path.join(self.outer.name, "browser-vault.key")))

    def test_legacy_secrets_yaml_still_visible_to_settings(self):
        """Backward compat: an upgraded install with only the legacy file
        keeps reporting its saved keys instead of showing empty state."""
        import yaml
        with open(os.path.join(self.outer.name, "secrets.yaml"), "w") as f:
            yaml.safe_dump({"groq": "gsk_legacy_key"}, f)
        self.lock_volume_root()
        keys = self.client.get("/api/wizard/keys").json()
        self.assertTrue(keys["have_key"].get("groq"))
