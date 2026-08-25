"""Ops Center ↔ dashboard authz contract (apiproxy machine principal).

The apiproxy (anton-studio's Node half) forwards cookie-only browser
requests to the dashboard on :8799. Under authz mode every such request
needs a bearer identity: a dedicated kind="service" principal ("apiproxy"),
scoped by guards.MACHINE_TOKEN_SCOPES to exactly the routes the proxy
registers. These tests pin the previously-403ing proxied surfaces — they
must succeed for the proxy's scoped credential and for an authenticated
Owner session, and stay 401/403 for unauthenticated, legacy-token, or
out-of-scope callers. A non-authz regression class pins legacy-token
behavior as unchanged.
"""
import os
import unittest

from helpers import build_env, raw_sqlite


def _read_token(data_dir: str) -> str:
    with open(os.path.join(data_dir, "authz", "apiproxy.token"),
              encoding="utf-8") as f:
        return f.read().strip()


class ApiProxyPrincipalBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        # bootstrap provisions the apiproxy credential as a side effect
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.proxy_h = {"Authorization": f"Bearer {_read_token(self.env.data_dir)}"}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)


class TestApiProxyScopedSurfaces(ApiProxyPrincipalBase):
    """The previously-403ing Ops Center surfaces now pass under the
    proxy's own scoped machine credential."""

    def test_proxy_reads_succeed(self):
        for path in ("/api/systems", "/api/approvals", "/api/initiatives",
                     "/api/jobs", "/api/learning", "/api/incidents",
                     "/api/agent/worklog", "/api/wizard/catalog",
                     "/api/wizard/keys", "/api/mode",
                     # Add-ons connectors: bundled+registry catalog and the
                     # Composio/Nango bridge-status read (previously 403 for
                     # the proxy credential, leaving Add-ons silently empty).
                     "/api/connections/catalog", "/api/integrations/bridges"):
            r = self.env.client.get(path, headers=self.proxy_h)
            self.assertEqual(r.status_code, 200,
                             f"GET {path}: {r.status_code} {r.text}")

    def test_proxy_mutations_within_scope_succeed(self):
        r = self.env.client.post("/api/wizard/providers", headers=self.proxy_h,
                                 json={"provider": "openai", "key": "sk-test"})
        self.assertEqual(r.status_code, 200)
        r = self.env.client.post("/api/setup", headers=self.proxy_h,
                                 json={"step": "work", "picks": ["email"]})
        self.assertEqual(r.status_code, 200)

    def test_proxy_connect_mutations_within_scope_succeed(self):
        # POST /api/connections/connect is fully exercisable: it persists a
        # catalog entry into mcp_servers (same payload shape as
        # tests/test_connections.py).
        r = self.env.client.post("/api/connections/connect", headers=self.proxy_h,
                                 json={"id": "github", "name": "GitHub",
                                       "what": "Repos, PRs",
                                       "url": "https://api.githubcopilot.com/mcp",
                                       "auth": "oauth"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "saved")
        # POST /api/integrations/connect/start needs a configured bridge to
        # complete; an unconfigured bridge must fail at the ROUTE (400) —
        # never 403 at the guard, which would mean the scope regressed.
        r = self.env.client.post("/api/integrations/connect/start",
                                 headers=self.proxy_h,
                                 json={"bridge": "composio",
                                       "provider": "quickbooks"})
        self.assertEqual(r.status_code, 400, r.text)

    def test_proxy_bridge_credential_paste_within_scope(self):
        # POST /api/integrations/bridges/configure is fully exercisable
        # through the apiproxy credential (the Add-ons paste field rides
        # it): persists 0600 + hot-applies. The key must never be echoed.
        r = self.env.client.post("/api/integrations/bridges/configure",
                                 headers=self.proxy_h,
                                 json={"bridge": "composio",
                                       "key": "ak_test_pin_key"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["configured"]["composio"])
        self.assertNotIn("ak_test_pin_key", r.text)
        import os as _os
        spath = _os.path.join(self.env.data_dir, "secrets.yaml")
        self.assertTrue(_os.path.exists(spath))

    def test_out_of_scope_denied_with_alert(self):
        r = self.env.client.get("/api/ledger", headers=self.proxy_h)
        self.assertEqual(r.status_code, 403)
        # /api/agentPreset.* is an in-process dsh-web RPC that never touches
        # FastAPI; pin that even if something ever forwards it here, the
        # apiproxy credential cannot ride it.
        r = self.env.client.get("/api/agentPreset.list", headers=self.proxy_h)
        self.assertEqual(r.status_code, 403)
        alerts = raw_sqlite(self.env.authz_db,
                            "SELECT detail FROM authz_alerts "
                            "WHERE kind='machine_token_violation'")
        self.assertTrue(any("/api/ledger" in row[0] for row in alerts))


class TestOwnerSessionAndDenyDefaults(unittest.TestCase):
    """Same surfaces for an authenticated Owner session; unauthenticated and
    legacy-token callers stay denied."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.owner_h = self.env.login("owner", "Owner-Pass-1!")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_owner_session_reaches_previously_403ing_surfaces(self):
        for path in ("/api/systems", "/api/approvals", "/api/initiatives",
                     "/api/jobs", "/api/learning", "/api/incidents",
                     "/api/agent/worklog", "/api/wizard/catalog",
                     "/api/wizard/keys"):
            r = self.env.client.get(path, headers=self.owner_h)
            self.assertEqual(r.status_code, 200,
                             f"GET {path}: {r.status_code} {r.text}")

    def test_unauthenticated_and_legacy_token_denied(self):
        for headers in ({}, {"Authorization": "Bearer s3cret-legacy"}):
            for path in ("/api/systems", "/api/wizard/catalog",
                         "/api/agent/worklog"):
                r = self.env.client.get(path, headers=headers)
                self.assertEqual(
                    r.status_code, 401,
                    f"GET {path} with {headers or 'no auth'}: {r.status_code}")

    def test_owner_wizard_save_round_trip(self):
        r = self.env.client.post("/api/wizard/providers", headers=self.owner_h,
                                 json={"provider": "anthropic",
                                       "key": "sk-ant-test",
                                       "model": "claude-x"})
        self.assertEqual(r.status_code, 200, r.text)


class TestCredentialSeparationAndRotation(ApiProxyPrincipalBase):
    """Distinct tokens per consumer; rotation is self-healing."""

    def test_executor_token_cannot_use_apiproxy_surface(self):
        owner = self.store.get_user_by_username("owner")
        svc = self.store.create_service_identity("executor-svc", owner["id"])
        exec_token, _ = self.store.mint_machine_token(svc["id"])
        h = {"Authorization": f"Bearer {exec_token}"}
        # executor keeps its callback allowlist entry...
        r = self.env.client.post("/api/exec/result", headers=h,
                                 json={"execution_id": "e1", "status": "ok"})
        self.assertEqual(r.status_code, 200)
        # ...but shares nothing of the apiproxy's surface
        r = self.env.client.get("/api/systems", headers=h)
        self.assertEqual(r.status_code, 403)

    def test_revoked_credential_self_heals_on_next_provision(self):
        from anton.authz.provision import ensure_apiproxy_credential
        old = _read_token(self.env.data_dir)
        jti = raw_sqlite(
            self.env.authz_db,
            "SELECT m.id FROM machine_tokens m JOIN users u "
            "ON u.id=m.service_user_id WHERE u.username='apiproxy'")[0][0]
        self.store.revoke_machine_token(jti)
        r = self.env.client.get("/api/systems",
                                headers={"Authorization": f"Bearer {old}"})
        self.assertEqual(r.status_code, 401)
        # next provision pass mints a fresh, working token into the file
        fresh = ensure_apiproxy_credential(self.store, os.path.join(
            self.env.data_dir, "authz"))
        self.assertIsNotNone(fresh)
        self.assertNotEqual(fresh, old)
        r = self.env.client.get("/api/systems",
                                headers={"Authorization": f"Bearer {fresh}"})
        self.assertEqual(r.status_code, 200)

    def test_provision_idempotent_while_valid(self):
        from anton.authz.provision import ensure_apiproxy_credential
        azdir = os.path.join(self.env.data_dir, "authz")
        again = ensure_apiproxy_credential(self.store, azdir)
        self.assertEqual(again, _read_token(self.env.data_dir))

    def test_provision_deferred_without_human_owner(self):
        env2 = build_env(authz_enabled=True)  # pristine: no bootstrap
        try:
            self.assertIsNone(_read_token(env2.data_dir))
        except FileNotFoundError:
            pass  # equally fine: nothing provisioned yet
        finally:
            import shutil
            shutil.rmtree(env2.dir, ignore_errors=True)


class TestNonAuthzLegacyTokenRegression(unittest.TestCase):
    """Backward compat: with the authz spine OFF, the legacy shared token
    still authenticates the proxied surfaces exactly as before."""

    def setUp(self):
        self.env = build_env(authz_enabled=False)
        self.legacy = {"Authorization": "Bearer s3cret-legacy"}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_legacy_token_still_works_off_authz(self):
        for path in ("/api/systems", "/api/approvals", "/api/wizard/catalog",
                     "/api/wizard/keys"):
            r = self.env.client.get(path, headers=self.legacy)
            self.assertEqual(r.status_code, 200,
                             f"GET {path}: {r.status_code} {r.text}")
        r = self.env.client.post("/api/setup", headers=self.legacy,
                                 json={"step": "work", "picks": ["email"]})
        self.assertEqual(r.status_code, 200)

    def test_wrong_still_token_rejected_off_authz(self):
        # NB: read-only ops routes (e.g. GET /api/systems) were never
        # token-checked pre-authz — use a guarded surface here.
        r = self.env.client.get("/api/wizard/catalog",
                                headers={"Authorization": "Bearer nope"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
