"""#5 — QBO OAuth end-to-end: code exchange, secure storage via the
credential broker, grant recording with OAuth scopes, revocation-triggered
refresh rotation. Intuit's endpoints are injected so CI never touches the
network; one test drives the real localhost callback loop."""
import unittest
import urllib.parse

from helpers import build_env, raw_sqlite


def fake_intuit(tokens_by_call):
    """Returns a transport asserting the Intuit token-endpoint contract."""
    calls = []

    def transport(url, client_id, client_secret, form):
        calls.append({"url": url, "form": dict(form)})
        assert url == "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
        resp = tokens_by_call[len(calls) - 1]
        return resp

    transport.calls = calls
    return transport


class TestQboExchange(unittest.TestCase):
    def test_exchange_code_speaks_intuit_contract(self):
        from anton.qbo_oauth import TOKEN_URL, exchange_code
        t = fake_intuit([{"access_token": "at1", "refresh_token": "rt1",
                          "expires_in": 3600,
                          "scope": "com.intuit.quickbooks.accounting"}])
        out = exchange_code("cid", "csec", "the-code",
                            "http://localhost:9999/callback", transport=t)
        self.assertEqual(out["access_token"], "at1")
        call = t.calls[0]
        self.assertEqual(call["url"], TOKEN_URL)
        self.assertEqual(call["form"]["grant_type"], "authorization_code")
        self.assertEqual(call["form"]["code"], "the-code")

    def test_refresh_uses_refresh_grant(self):
        from anton.qbo_oauth import refresh_tokens
        t = fake_intuit([{"access_token": "at2", "refresh_token": "rt2"}])
        out = refresh_tokens("cid", "csec", "rt-old", transport=t)
        self.assertEqual(out["refresh_token"], "rt2")
        self.assertEqual(t.calls[0]["form"]["grant_type"], "refresh_token")
        self.assertEqual(t.calls[0]["form"]["refresh_token"], "rt-old")


class TestQboStorage(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.broker = self.env.app.state.authz_broker
        self.store.broker = self.broker  # revocation-rotation path
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _store(self):
        from anton.qbo_oauth import store_tokens
        store_tokens(
            self.broker, self.store, self.audit, actor=self.owner_p,
            provider="quickbooks",
            tokens={"access_token": "AT-xyz", "refresh_token": "RT-old",
                    "expires_in": 3600,
                    "scope": "com.intuit.quickbooks.accounting"})

    def test_tokens_stored_encrypted_with_scopes_recorded(self):
        self._store()
        # refresh token never sits in plaintext anywhere readable
        blob = str(raw_sqlite(self.broker.db_path,
                              "SELECT ciphertext, key_version FROM broker_secrets"))
        self.assertNotIn("RT-old", blob)
        self.assertNotIn("AT-xyz", blob)
        # granted OAuth scopes recorded on the connection (REQ-GRNT-01/04)
        row = raw_sqlite(self.env.authz_db,
                         "SELECT oauth_scopes_json FROM connection_scopes "
                         "WHERE connection_id='quickbooks'")[0][0]
        self.assertIn("com.intuit.quickbooks.accounting", row)
        # fetch through the broker returns the real value
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id="e1", connection_ids=["quickbooks"],
            ttl_s=60)
        cap = self.broker.mint_capability_token(
            lease, ["quickbooks:access_token", "quickbooks:refresh_token"])
        self.assertEqual(self.broker.fetch(cap, "quickbooks:refresh_token",
                                           purpose="t"), "RT-old")

    def test_revoke_rotates_via_refresh_endpoint(self):
        from anton.authz.grants import create_grant, revoke_grant
        from anton.qbo_oauth import wire_rotation
        t = fake_intuit([{"access_token": "AT-new", "refresh_token": "RT-new"}])
        rotated = {}
        wire_rotation(self.store, "cid", "csec", transport=t,
                      sink=lambda conn, tok: rotated.update({conn: tok}))
        self._store()

        appr = self.store.create_user("appr2", "Role-Pass-1!")
        self.store.assign_role(appr["id"], "Approver",
                               actor_id=self.owner_p.user_id)
        gid = create_grant(self.store, self.audit, granter=self.owner_p,
                           grantee_user_id=appr["id"],
                           connection_id="quickbooks", scope="full",
                           oauth_scopes=["com.intuit.quickbooks.accounting"])
        revoke_grant(self.store, self.audit, actor=self.owner_p, grant_id=gid)

        self.assertEqual(t.calls[0]["form"]["grant_type"], "refresh_token")
        self.assertEqual(rotated.get("quickbooks"), "RT-new")


class TestCallbackLoop(unittest.TestCase):
    def test_local_callback_server_receives_provider_redirect(self):
        from anton.oauth import CallbackServer
        srv = CallbackServer(port=0, timeout_s=10)
        srv.start()
        try:
            import httpx
            params = urllib.parse.urlencode({"code": "AB-123", "state": "s1"})
            r = httpx.get(f"http://127.0.0.1:{srv.port}/callback?{params}")
            self.assertEqual(r.status_code, 200)
            result = srv.wait()
            self.assertEqual(result["code"], "AB-123")
        finally:
            srv.stop()


if __name__ == "__main__":
    unittest.main()
