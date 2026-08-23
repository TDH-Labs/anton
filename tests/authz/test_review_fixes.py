"""Regression tests for adversarial-review findings (run 1, 2026-08-22).

Each test pins a BLOCKER/MAJOR finding from the first implementation-phase
adversarial review so it can never silently regress.
"""
import time
import unittest
from unittest import mock

from helpers import build_env, raw_sqlite


class FixPeerUidFailOpen(unittest.TestCase):
    """BLOCKER: peer_uid=None must be denied, not skipped."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_unresolvable_peer_uid_denied_over_socket(self):
        from anton.authz import broker as broker_mod
        from anton.authz.broker import BrokerClient, BrokerDenied

        cap = self._cap()
        client = BrokerClient(self.broker.socket_path)
        with mock.patch.object(broker_mod, "_peer_uid", return_value=None):
            with self.assertRaises(BrokerDenied):
                client.fetch(cap, "conn-a", purpose="t")

    def _cap(self):
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id="e1", connection_ids=["conn-a"], ttl_s=60)
        return self.broker.mint_capability_token(lease, ["conn-a"])


class FixDefaultDenyMutations(unittest.TestCase):
    """BLOCKER: unmapped mutating routes must fail closed."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        owner = self.store.get_user_by_username("owner")
        viewer = self.store.create_user("view1", "Role-Pass-1!")
        self.store.assign_role(viewer["id"], "Viewer", actor_id=owner["id"])
        h = {"Authorization": "Bearer " + self._session(viewer)}
        r = self.env.client.post("/api/authz/totally-unmapped", json={},
                                 headers=h)
        self.assertEqual(r.status_code, 403)
        # admin passes the capability gate and gets a routing 404 instead
        ah = {"Authorization": "Bearer " + self._session(
            self.store.get_user_by_username("owner"))}
        r = self.env.client.post("/api/authz/totally-unmapped", json={}, headers=ah)
        self.assertEqual(r.status_code, 404)

    def _session(self, user):
        store = self.env.app.state.authz_store
        dev = store.create_device(user["id"], "t")
        return store.create_session(user["id"], dev)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)


class FixServiceIdentitySelfGrant(unittest.TestCase):
    """BLOCKER: U granting U's own service identity is a self-grant."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_grant_to_own_service_account_rejected(self):
        from anton.authz.grants import SelfGrantError, create_grant
        svc = self.store.create_service_identity("bot", self.owner_p.user_id)
        with self.assertRaises(SelfGrantError):
            create_grant(self.store, self.audit, granter=self.owner_p,
                         grantee_user_id=svc["id"], connection_id="c1",
                         scope="use", oauth_scopes=[])


class FixSocketLeaseFlow(unittest.TestCase):
    """BLOCKER: lease/mint must be reachable over the socket so the app
    process never needs master-key material to assemble executions."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker
        self.broker.register_secret("conn-a", "socket-value",
                                    connection_id="conn-a")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_lease_mint_fetch_all_over_socket(self):
        from anton.authz.broker import BrokerClient
        token = self._owner_session_token()
        client = BrokerClient(self.broker.socket_path)
        lease = client.issue_lease(token, "exec-sock", ["conn-a"], ttl_s=60)
        cap = client.mint(lease, ["conn-a"])
        self.assertEqual(client.fetch(cap, "conn-a", purpose="t"),
                         "socket-value")

    def _owner_session_token(self):
        store = self.store
        owner = store.get_user_by_username("owner")
        dev = store.create_device(owner["id"], "assembler")
        return store.create_session(owner["id"], dev)


class FixAuditHashCoversIdentities(unittest.TestCase):
    """BLOCKER: rewriting sponsor/workspace columns must break the chain."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_identity_column_edit_is_tamper_evident(self):
        from anton.authz.audit import ChainTampered
        self.audit.append("m", actor=self.store.principal_of("owner"),
                          payload={}, workspace="default")
        ok, _ = self.audit.verify()
        self.assertTrue(ok)
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        conn.execute("DROP TRIGGER trg_audit_append_only")
        conn.execute("UPDATE audit_chain SET sponsor_user='someone-else' "
                     "WHERE seq=(SELECT MAX(seq) FROM audit_chain)")
        conn.commit()
        conn.close()
        with self.assertRaises(ChainTampered):
            self.audit.verify()


class FixHostClockBackwardJump(unittest.TestCase):
    """MAJOR: backward jump on the broker host cannot extend windows."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_backward_jump_does_not_extend_ttl_and_alarms(self):
        from anton.authz import broker as broker_mod

        real_time = broker_mod.time

        class FakeTime:
            offset = 0.0
            mono0 = time.monotonic()

            @staticmethod
            def time():
                return time.time() + FakeTime.offset

            @staticmethod
            def monotonic():
                return time.monotonic()

        cap = self._cap(ttl_s=2)
        with mock.patch.object(broker_mod, "time", FakeTime):
            # jump host clock backwards 30 minutes
            FakeTime.offset = -1800.0
            time.sleep(2.1)
            from anton.authz.broker import TokenExpired
            with self.assertRaises(TokenExpired):
                self.broker.fetch(cap, "conn-a", purpose="after-jump")

        alarms = raw_sqlite(self.env.authz_db,
                            "SELECT seq FROM audit_chain "
                            "WHERE event_type='clock_skew_alarm'")
        self.assertTrue(alarms, "backward jump must raise an alarm")

    def _cap(self, ttl_s):
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id="ej", connection_ids=["conn-a"],
            ttl_s=ttl_s)
        return self.broker.mint_capability_token(lease, ["conn-a"])


class FixDoubleDecisionRace(unittest.TestCase):
    """MAJOR: two decisions on one approval are schema-impossible."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")
        self.alice_p = self.store.principal_of(
            "alice") if False else None
        alice = self.store.create_user("alice", "Role-Pass-1!")
        self.alice_p = self.store.principal_of("alice")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_unique_index_blocks_second_decision(self):
        from anton.authz.approvals import (ApprovalRejected, approve,
                                           create_approval)
        aid = create_approval(self.store, self.audit, initiator=self.alice_p,
                              payload={"x": 1}, policy_version="v1")
        approve(self.store, self.audit, approver=self.owner_p, approval_id=aid)
        # even a DIFFERENT second approver is rejected: decision is one-shot
        other = self.store.create_user("appr9", "Role-Pass-1!")
        self.store.assign_role(other["id"], "Approver",
                               actor_id=self.owner_p.user_id)
        with self.assertRaises(ApprovalRejected):
            approve(self.store, self.audit,
                    approver=self.store.principal_of("appr9"),
                    approval_id=aid)


class FixRotationFailureSurfaced(unittest.TestCase):
    """MAJOR: rotation failure on revoke must be audited + alerted."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_broken_rotator_is_audited_and_alerted(self):
        from anton.authz.grants import create_grant, revoke_grant

        def broken(conn):
            raise RuntimeError("provider down")

        self.store.token_rotator = broken
        appr = self.store.create_user("appr3", "Role-Pass-1!")
        self.store.assign_role(appr["id"], "Approver",
                               actor_id=self.owner_p.user_id)
        gid = create_grant(self.store, self.audit, granter=self.owner_p,
                           grantee_user_id=appr["id"], connection_id="cx",
                           scope="use", oauth_scopes=[])
        revoke_grant(self.store, self.audit, actor=self.owner_p, grant_id=gid)

        rows = raw_sqlite(self.env.authz_db,
                          "SELECT seq FROM audit_chain "
                          "WHERE event_type='grant_rotation_failed'")
        self.assertTrue(rows)
        alerts = raw_sqlite(self.env.authz_db,
                            "SELECT kind FROM authz_alerts "
                            "WHERE kind='grant_rotation_failed'")
        self.assertTrue(alerts)


class FixAuditorNotVacuous(unittest.TestCase):
    """MAJOR: auditor flags fallback-reliant mutations even when guarded."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_unmapped_mutating_route_flagged_on_guarded_app(self):
        from anton.authz.guards import audit_routes_behavioral

        @self.env.app.post("/api/unmapped-mutator")
        def unmapped():  # pragma: no cover
            return {}

        findings = audit_routes_behavioral(self.env.app)
        self.assertTrue(any("/api/unmapped-mutator" in f for f in findings))


if __name__ == "__main__":
    unittest.main()


class MachineTokenExpiry(unittest.TestCase):
    """MINOR fix: machine tokens support bounded lifetimes."""

    def test_expired_machine_token_rejected(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        owner = store.get_user_by_username("owner")
        svc = store.create_service_identity("svc-exp", owner["id"])
        tok, _ = store.mint_machine_token(svc["id"], ttl_hours=-0.01)
        self.assertIsNone(store.resolve_machine_token(tok))
        tok2, _ = store.mint_machine_token(svc["id"])  # no expiry
        self.assertIsNotNone(store.resolve_machine_token(tok2))
