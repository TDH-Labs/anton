"""CI-T-CRED-01..06 — §3 credential broker (spec v1.1, FROZEN)."""
import os
import socket
import subprocess
import sys
import time
import unittest

from helpers import build_env, raw_sqlite


class BrokerTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker
        # real secret material so capability-token minting has a target
        self.broker.register_secret("conn-a", "test-secret-value",
                                    connection_id="conn-a")
        self.owner = self.store.get_user_by_username("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _lease_and_cap(self, exec_id="exec-1", conns=("conn-a",),
                       secrets=("conn-a",), ttl_s=120):
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id=exec_id,
            connection_ids=list(conns), ttl_s=ttl_s)
        return self.broker.mint_capability_token(lease, list(secrets))


class TestCred01BrokerArchitecture(BrokerTestBase):
    """CI-T-CRED-01: secrets never in env/prompts; DB holds ciphertext."""

    def test_canary_never_in_executor_environ_and_db_is_ciphertext(self):
        CANARY = "sk-canary-DO-NOT-LEAK-9f3b"
        self.broker.register_secret("conn-a", CANARY, connection_id="conn-a")

        # full executor-style fetch flow through the broker socket client
        from anton.authz.broker import BrokerClient
        client = BrokerClient(self.broker.socket_path)
        cap = self._lease_and_cap()
        value = client.fetch(cap, "conn-a", purpose="tool-call")
        self.assertEqual(value, CANARY)

        # canary absent from this process environment (executor process env)
        for v in os.environ.values():
            self.assertNotIn(CANARY, v)

        # direct DB read of the credentials table yields ciphertext
        rows = raw_sqlite(self.env.app.state.authz_broker.db_path,
                          "SELECT ciphertext FROM broker_secrets WHERE id='conn-a'")
        self.assertEqual(len(rows), 1)
        blob = rows[0][0]
        self.assertIsInstance(blob, (bytes, str))
        self.assertNotIn(CANARY, blob if isinstance(blob, str) else blob.decode("latin-1"))


class TestCred02CapabilityTokens(BrokerTestBase):
    """CI-T-CRED-02: attestation (lease + peer cred), TTL, scoping, audit."""

    def test_unattested_socket_request_denied(self):
        from anton.authz.broker import BrokerDenied, BrokerClient
        client = BrokerClient(self.broker.socket_path)
        with self.assertRaises(BrokerDenied):
            client.call({"op": "fetch", "secret_id": "conn-a", "purpose": "x",
                         "token": "forged"})
        # no token at all
        with self.assertRaises(BrokerDenied):
            client.call({"op": "fetch", "secret_id": "conn-a", "purpose": "x"})

    def test_token_replay_after_ttl_denied(self):
        from anton.authz.broker import TokenExpired
        cap = self._lease_and_cap(ttl_s=1)
        self.broker.fetch(cap, "conn-a", purpose="t")
        time.sleep(1.3)
        with self.assertRaises(TokenExpired):
            self.broker.fetch(cap, "conn-a", purpose="t")

    def test_scope_escape_a_denied(self):
        from anton.authz.broker import BrokerDenied
        cap = self._lease_and_cap(secrets=("conn-a",))
        self.broker.register_secret("conn-b", "other", connection_id="conn-b")
        with self.assertRaises(BrokerDenied):
            self.broker.fetch(cap, "conn-b", purpose="escape")

    def test_each_fetch_exactly_one_audit_row(self):
        before = self._fetch_rows()
        cap = self._lease_and_cap()
        self.broker.fetch(cap, "conn-a", purpose="audited")
        after = self._fetch_rows()
        self.assertEqual(len(after) - len(before), 1)

    def _fetch_rows(self):
        return raw_sqlite(self.env.authz_db,
                          "SELECT seq FROM audit_chain WHERE event_type='secret_fetch'")


class TestCred03MachineTokenMinimalCallback(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        owner = self.store.get_user_by_username("owner")
        svc = self.store.create_service_identity("executor-svc", owner["id"])
        self.machine_token, _ = self.store.mint_machine_token(svc["id"])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_machine_token_outside_allowlist_403_plus_alert(self):
        h = {"Authorization": f"Bearer {self.machine_token}"}
        r = self.env.client.post("/api/exec/result", json={"execution_id": "e1",
                                                           "status": "ok"}, headers=h)
        self.assertEqual(r.status_code, 200)  # allowlisted callback passes

        r = self.env.client.get("/api/vault/note?path=index", headers=h)
        self.assertEqual(r.status_code, 403)

        alerts = raw_sqlite(self.env.authz_db,
                            "SELECT kind FROM authz_alerts WHERE kind='machine_token_violation'")
        self.assertTrue(alerts)


class TestCred04KillSwitch(BrokerTestBase):
    def test_kill_switch_mid_execution_fails_closed_explicitly(self):
        from anton.authz.broker import RevokedState
        cap = self._lease_and_cap(exec_id="exec-kill")
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")
        self.broker.fetch(cap, "conn-a", purpose="pre")  # works pre-revocation

        self.broker.set_kill_switch("principal:" + self.owner["id"], True)

        status = self.broker.check_kill_switch("exec-kill",
                                               principal_id=self.owner["id"])
        self.assertTrue(status["revoked"])
        self.assertEqual(status["reason"], "revoked")
        with self.assertRaises(RevokedState):
            self.broker.fetch(cap, "conn-a", purpose="post")


class TestCred05Availability(BrokerTestBase):
    def test_sigkilled_broker_reports_degraded_not_silent_retry(self):
        db = os.path.join(self.env.data_dir, "authz", "broker.db")
        keys = os.path.join(self.env.data_dir, "authz", "keys")
        sock = os.path.join(self.env.data_dir, "authz", "sub.sock")
        proc = subprocess.Popen(
            [sys.executable, "-m", "anton.authz.broker", "serve",
             "--db", db, "--keys", keys, "--sock", sock,
             "--uid", str(os.getuid())],
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            from anton.authz.broker import BrokerClient
            deadline = time.time() + 10
            while not os.path.exists(sock) and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(os.path.exists(sock), "subprocess broker did not start")
            client = BrokerClient(sock)
            pong = client.ping()
            self.assertTrue(pong.get("ok"))

            proc.kill()
            proc.wait(timeout=10)
            with self.assertRaises(Exception) as ctx:
                client.ping()
            self.assertIn("unavailable", str(ctx.exception).lower())
        finally:
            if proc.poll() is None:
                proc.kill()


class TestCred06TimeAuthority(BrokerTestBase):
    def test_worker_clock_jump_does_not_change_validity_alarm_fires(self):
        from anton.authz.broker import BrokerClient
        cap = self._lease_and_cap(ttl_s=300)
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")

        for offset in (-1800, +1800):
            client = BrokerClient(self.broker.socket_path,
                                  time_source=lambda off=offset: time.time() + off)
            value = client.fetch(cap, "conn-a", purpose="skew-test")
            self.assertEqual(value, "v")

        alarms = raw_sqlite(self.env.authz_db,
                            "SELECT seq FROM audit_chain WHERE event_type='clock_skew_alarm'")
        self.assertGreaterEqual(len(alarms), 2)


if __name__ == "__main__":
    unittest.main()
