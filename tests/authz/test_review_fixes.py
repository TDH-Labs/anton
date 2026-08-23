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


# =========================================================================
# Round 2 (review run 2, docs/AUTHZ-CONSENSUS-REVIEW-FINAL.md)
# =========================================================================

class R2A1StubRouteRemoved(unittest.TestCase):
    """MAJOR R2A-1: the {"todo": True} stub shadowed the real egress handler."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_channel_creation_really_creates(self):
        h = self._owner_headers()
        r = self.env.client.post("/api/authz/egress/channels", headers=h, json={
            "channel_id": "sms-x", "kind": "agentphone_sms",
            "address": "+15550001111", "clearance": "INTERNAL"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("todo", r.json())
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT id FROM egress_channels WHERE id='sms-x'")
        self.assertEqual(len(rows), 1)
        audit_rows = raw_sqlite(self.env.authz_db,
                                "SELECT seq FROM audit_chain "
                                "WHERE event_type='egress_channel_created'")
        self.assertTrue(audit_rows)

    def _owner_headers(self):
        store = self.store
        owner = store.get_user_by_username("owner")
        dev = store.create_device(owner["id"], "t")
        return {"Authorization": "Bearer " + store.create_session(owner["id"], dev)}


class R2A2ClockStaircase(unittest.TestCase):
    """MAJOR R2A-2: sub-threshold backward steps cannot extend TTLs."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_staircase_regression_cannot_extend_epoch(self):
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id="es", connection_ids=["conn-a"], ttl_s=5)
        cap = self.broker.mint_capability_token(lease, ["conn-a"])

        from anton.authz import broker as broker_mod
        real_time = broker_mod.time

        class FakeTime:
            offset = 0.0

            @staticmethod
            def time():
                return time.time() + FakeTime.offset

            @staticmethod
            def monotonic():
                return time.monotonic()

        with mock.patch.object(broker_mod, "time", FakeTime):
            # three -290s steps, all under the 300s threshold
            for _ in range(3):
                FakeTime.offset -= 290.0
                self.broker.epoch_now()
            # epoch_now must never have regressed: expiry still enforced
            time.sleep(5.1)
            from anton.authz.broker import TokenExpired
            with self.assertRaises(TokenExpired):
                self.broker.fetch(cap, "conn-a", purpose="after-staircase")


class R2A3FabricatedGrantParty(unittest.TestCase):
    """MAJOR R2A-3: unknown party ids abort instead of passing NULL checks."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_fabricated_granter_rejected_by_trigger(self):
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO connection_grants(granter_id, grantee_id,"
                    " connection_id, scope, oauth_scopes_json, policy_version,"
                    " active, created) VALUES(?,?,?,?,?,?,1,'now')",
                    ("fabricated-nonexistent-id", self.owner_p.user_id,
                     "c9", "full", "[]", "v1"))
        finally:
            conn.close()


class R2A4MigrationGateComplete(unittest.TestCase):
    """MAJOR R2A-4: dropping ux_decision_once or any critical trigger fails."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_dropping_unique_index_fails_migration_gate(self):
        from anton.authz.boot import MigrationIntegrityError, run_migration
        from anton.authz.principals import MigrationPrincipal
        with self.assertRaises(MigrationIntegrityError):
            run_migration(
                self.store, self.audit,
                principal=MigrationPrincipal(migration_name="hostile-2"),
                name="hostile-2",
                sql="DROP INDEX IF EXISTS ux_decision_once")

    def test_baseline_not_laundered_after_failed_migration(self):
        from anton.authz.boot import MigrationIntegrityError, run_migration
        from anton.authz.principals import MigrationPrincipal
        before = self.store.kv_get("schema_hash")
        with self.assertRaises(MigrationIntegrityError):
            run_migration(
                self.store, self.audit,
                principal=MigrationPrincipal(migration_name="hostile-3"),
                name="hostile-3", sql="DROP INDEX IF EXISTS ux_decision_once")
        self.assertEqual(before, self.store.kv_get("schema_hash"))


class R2A5WebSocketDenied(unittest.TestCase):
    """MAJOR R2A-5: websocket scopes are fail-closed rejected."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_ws_connection_closed_without_data(self):
        from starlette.websockets import WebSocketDisconnect
        @self.env.app.websocket("/api/ws/rogue")
        async def rogue(ws):  # pragma: no cover — must never run
            await ws.send_text("leak")

        with self.assertRaises(Exception):
            with self.env.client.websocket_connect("/api/ws/rogue") as ws:
                ws.receive_text()

    def test_auditor_flags_any_websocket_route_even_guarded(self):
        from anton.authz.guards import audit_routes_behavioral

        @self.env.app.websocket("/api/ws/another")
        async def another(ws):  # pragma: no cover
            await ws.accept()

        findings = audit_routes_behavioral(self.env.app)
        self.assertTrue(any("websocket" in f for f in findings))


class R2A6SilentBreakGlassRefused(unittest.TestCase):
    """MINOR R2A-6: elevation requires at least one delivered channel."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_all_channels_down_refuses_elevation(self):
        from anton.authz.breakglass import (BreakGlassDeliveryFailed,
                                            elevation_active,
                                            request_breakglass)
        with self.assertRaises(BreakGlassDeliveryFailed):
            request_breakglass(self.store, self.audit, principal=self.owner_p,
                               reason="silent attempt", duration_min=10,
                               channels=[lambda m: False])
        self.assertFalse(elevation_active(self.store, self.owner_p.user_id))


class O3DisabledUserSessionsAndBrokerErrors(unittest.TestCase):
    """OBSERVATION O-3 hardening."""

    def test_disabled_user_session_invalid(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        u = store.create_user("temp1", "Role-Pass-1!")
        dev = store.create_device(u["id"], "d")
        tok = store.create_session(u["id"], dev)
        self.assertIsNotNone(store.resolve_session(tok))
        with store.lock:
            store.conn.execute("UPDATE users SET disabled=1 WHERE id=?",
                               (u["id"],))
            store.conn.commit()
        self.assertIsNone(store.resolve_session(tok))

    def test_malformed_broker_response_raises_degraded(self):
        from anton.authz import broker as broker_mod
        client = broker_mod.BrokerClient("/tmp/nonexistent-sock-does-not-exist")
        with self.assertRaises(broker_mod.BrokerDegraded):
            client.ping()
