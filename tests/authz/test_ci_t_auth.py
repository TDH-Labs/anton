"""CI-T-AUTH-01..03 — §1 Identity, Sessions, RBAC (spec v1.1, FROZEN)."""
import unittest

from helpers import build_env, raw_sqlite


class TestAuth01LegacyTokenAndIdentityChain(unittest.TestCase):
    """CI-T-AUTH-01: legacy shared token 401 after migration flag flips;
    every audited mutation row has all four identity fields non-null."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_legacy_shared_token_rejected(self):
        r = self.client_post_with("s3cret-legacy")
        self.assertEqual(r.status_code, 401)
        # wrong token too
        r = self.client_post_with("garbage")
        self.assertEqual(r.status_code, 401)

    def client_post_with(self, token):
        return self.env.client.post(
            "/api/approvals", json={"action": "x"},
            headers={"Authorization": f"Bearer {token}"})

    def test_session_token_accepted_and_mutation_audited_with_four_identities(self):
        self.env.bootstrap_owner()
        h = self.env.login("owner", "Owner-Pass-1!")
        r = self.env.client.post("/api/approvals", json={"action": "x"}, headers=h)
        self.assertEqual(r.status_code, 200)
        rows = raw_sqlite(
            self.env.authz_db,
            "SELECT event_type, sponsor_user, workspace, agent_instance, "
            "tool_credential FROM audit_chain WHERE event_type='mutation'")
        self.assertTrue(rows, "expected an audited mutation row")
        for (_t, sponsor, workspace, agent_inst, tool_cred) in rows:
            for field in (sponsor, workspace, agent_inst, tool_cred):
                self.assertIsNotNone(field)
                self.assertNotEqual(field, "")

    def test_first_run_owner_claim_is_explicit_not_predictable(self):
        # bootstrap without the out-of-band claim code must fail
        r = self.env.client.post("/api/auth/bootstrap", json={
            "username": "attacker", "password": "pw12345!", "claim": "000000"})
        self.assertEqual(r.status_code, 403)
        # claim code is single-use: second bootstrap with it fails
        claim = self.env.owner_claim()
        self.env.bootstrap_owner()
        r = self.env.client.post("/api/auth/bootstrap", json={
            "username": "second", "password": "Other-Pass-1!",
            "claim": claim})
        self.assertIn(r.status_code, (403, 409))


class TestAuth02SessionLifecycle(unittest.TestCase):
    """CI-T-AUTH-02: server-side revocable device-bound sessions; immediate
    revocation reach-through; separate machine-token signing material;
    login rate limiting + lockout."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        from anton.authz.store import open_store
        self.store = open_store(self.env.authz_db)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _admin_session(self):
        from anton.authz.store import open_store
        s = open_store(self.env.authz_db)
        owner = s.get_user_by_username("owner")
        dev = s.create_device(owner["id"], "test-device")
        return s, owner, s.create_session(owner["id"], dev)

    def test_revoke_mid_job_next_call_401_and_tokens_die_within_poll_interval(self):
        s, owner, token = self._admin_session()
        broker = getattr(self.env.app.state, "authz_broker", None)
        broker.register_secret("conn-a", "v", connection_id="conn-a")
        lease = broker.issue_execution_lease(
            s.resolve_session(token), execution_id="exec-1",
            connection_ids=["conn-a"], ttl_s=120)
        cap = broker.mint_capability_token(lease, ["conn-a"])

        # revoke the session mid-job
        sid_rows = raw_sqlite(self.env.authz_db,
                              "SELECT id FROM sessions_authz WHERE revoked=0")
        self.assertTrue(sid_rows)
        s.revoke_session(sid_rows[0][0], actor_id="owner-test")

        # next API call from that session 401s (no cached auth decision)
        r = self.env.client.get("/api/ledger",
                                headers=self.env.headers_for(token))
        self.assertEqual(r.status_code, 401)

        # outstanding capability token killed within one poll interval
        status = broker.check_capability(cap)
        self.assertFalse(status["valid"])

    def test_machine_token_material_differs_from_session_token(self):
        s, owner, session_token = self._admin_session()
        svc = s.create_service_identity("executor-svc", owning_human_id=owner["id"])
        machine_token, jti = s.mint_machine_token(svc["id"])
        self.assertNotEqual(machine_token.split("_")[0], session_token.split("_")[0])

        sess_hash = raw_sqlite(self.env.authz_db,
                               "SELECT token_hash FROM sessions_authz LIMIT 1")[0][0]
        mach_hash = raw_sqlite(self.env.authz_db,
                               "SELECT token_hash FROM machine_tokens WHERE id=?",
                               (jti,))[0][0]
        self.assertNotEqual(sess_hash, mach_hash)
        # distinct scheme namespaces, not merely different randomness
        self.assertIn("session:", sess_hash)
        self.assertIn("machine:", mach_hash)

    def test_login_rate_limit_lockout(self):
        for i in range(5):
            r = self.env.client.post("/api/auth/login",
                                     json={"username": "owner", "password": "wrong"})
            self.assertEqual(r.status_code, 401)
        # locked even with correct password
        r = self.env.client.post("/api/auth/login",
                                 json={"username": "owner", "password": "Owner-Pass-1!"})
        self.assertEqual(r.status_code, 429)


class TestAuth03RbacMatrix(unittest.TestCase):
    """CI-T-AUTH-03: role×capability matrix against actual route behavior,
    including negative cases."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        from anton.authz.store import open_store
        from anton.authz.rbac import ROLES
        self.store = open_store(self.env.authz_db)
        owner = self.store.get_user_by_username("owner")
        self.tokens = {"Owner": self.env.login("owner", "Owner-Pass-1!")}
        for role in ROLES:
            if role == "Owner":
                continue
            uname = f"u_{role.lower()}"
            u = self.store.create_user(uname, "Role-Pass-1!")
            self.store.assign_role(u["id"], role, actor_id=owner["id"])
            self.tokens[role] = self.env.login(uname, "Role-Pass-1!")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_matrix_matches_declared_capabilities(self):
        from anton.authz.rbac import CAPABILITIES, ROLE_CAPABILITIES
        for role, caps in ROLE_CAPABILITIES.items():
            for capability in sorted(CAPABILITIES):
                with self.subTest(role=role, capability=capability):
                    r = self.env.client.get(f"/api/authz/probe/{capability}",
                                            headers=self.tokens[role])
                    if capability in caps:
                        self.assertEqual(r.status_code, 200,
                                         f"{role} should hold {capability}")
                    else:
                        self.assertEqual(r.status_code, 403,
                                         f"{role} must NOT hold {capability}")

    def test_negative_real_routes(self):
        # Viewer invoking run-class route -> 403
        r = self.env.client.post("/api/chat",
                                 json={"prompt": "hi"}, headers=self.tokens["Viewer"])
        self.assertEqual(r.status_code, 403)
        # Operator attempting to approve -> 403 (no approvals.decide)
        r = self.env.client.post("/api/approvals/1/resolve",
                                 json={"decision": "approve"},
                                 headers=self.tokens["Operator"])
        self.assertEqual(r.status_code, 403)
        # Operator managing users -> 403
        r = self.env.client.get("/api/authz/users", headers=self.tokens["Operator"])
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
