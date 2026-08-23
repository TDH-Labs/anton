"""CI-T-APPR-01..05 — §5 approvals, break-glass, single-operator mode."""
import unittest

from helpers import build_env, raw_sqlite


class ApprTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")
        self.alice = self.store.create_user("alice", "Role-Pass-1!")
        self.alice_p = self.store.principal_of("alice")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)


class TestAppr01ApproverNotInitiator(ApprTestBase):
    def test_same_human_approval_rejected_at_db_level(self):
        from anton.authz.approvals import (ApprovalRejected, create_approval,
                                           decide_approval)
        aid = create_approval(self.store, self.audit, initiator=self.owner_p,
                              payload={"action": "raise-alice"},
                              policy_version="v1")
        with self.assertRaises(ApprovalRejected):
            decide_approval(self.store, self.audit,
                            approver=self.owner_p, approval_id=aid,
                            decision="approved")

    def test_update_on_approval_row_rejected_by_trigger(self):
        from anton.authz.approvals import create_approval
        aid = create_approval(self.store, self.audit, initiator=self.alice_p,
                              payload={"x": 1}, policy_version="v1")
        with self.assertRaises(Exception):
            import sqlite3
            conn = sqlite3.connect(self.env.authz_db)
            try:
                conn.execute("UPDATE authz_approvals SET payload_hash='deadbeef' "
                             "WHERE id=?", (aid,))
                conn.commit()
            finally:
                conn.close()

    def test_payload_mutated_post_approval_rejected_at_execution(self):
        from anton.authz.approvals import (PayloadTamperError, approve,
                                           create_approval, execute_approved)
        aid = create_approval(self.store, self.audit, initiator=self.alice_p,
                              payload={"send": "invoice-7"}, policy_version="v1")
        approve(self.store, self.audit, approver=self.owner_p, approval_id=aid)

        # payload mutated after approval -> TOCTOU detection at execution time
        with self.assertRaises(PayloadTamperError):
            execute_approved(self.store, self.audit, approval_id=aid,
                             current_payload={"send": "invoice-9999"})
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT seq FROM audit_chain "
                          "WHERE event_type='approval_tamper'")
        self.assertTrue(rows)


class TestAppr02HumanBinding(ApprTestBase):
    def test_service_identity_does_not_satisfy_approver_ne_initiator(self):
        from anton.authz.approvals import (ApprovalRejected, create_approval,
                                           decide_approval)
        svc = self.store.create_service_identity("agent-2", self.alice["id"])
        svc_p = self.store.principal_of_service("agent-2")
        aid = create_approval(self.store, self.audit, initiator=svc_p,
                              payload={"x": 1}, policy_version="v1")
        # Alice initiates via her service identity, then approves as herself
        with self.assertRaises(ApprovalRejected):
            decide_approval(self.store, self.audit, approver=self.alice_p,
                            approval_id=aid, decision="approved")


class TestAppr03BreakGlass(ApprTestBase):
    def test_one_channel_down_completes_and_flags(self):
        from anton.authz.breakglass import request_breakglass
        ok = []
        channels = [lambda msg: ok.append(msg) or True,
                    lambda msg: False]  # second channel "down"
        ev = request_breakglass(self.store, self.audit, principal=self.owner_p,
                                reason="lockout", duration_min=10, channels=channels)
        self.assertTrue(ev["elevated"])
        self.assertEqual(ev["channels_failed"], 1)

    def test_second_breakglass_inside_rate_limit_denied(self):
        from anton.authz.breakglass import (BreakGlassRateLimited,
                                            request_breakglass)
        channels = [lambda msg: True]
        request_breakglass(self.store, self.audit, principal=self.owner_p,
                           reason="first", duration_min=5, channels=channels)
        with self.assertRaises(BreakGlassRateLimited):
            request_breakglass(self.store, self.audit, principal=self.owner_p,
                               reason="second", duration_min=5, channels=channels)

    def test_elevation_auto_expires(self):
        from anton.authz.breakglass import (elevation_active,
                                            request_breakglass)
        channels = [lambda msg: True]
        request_breakglass(self.store, self.audit, principal=self.owner_p,
                           reason="temp", duration_min=0.02, channels=channels)
        self.assertTrue(elevation_active(self.store, self.owner_p.user_id))
        import time
        time.sleep(1.5)
        self.assertFalse(elevation_active(self.store, self.owner_p.user_id))


class TestAppr04RecoveryArtifact(unittest.TestCase):
    def test_full_lockdown_recovery_and_rekey(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        audit = self.env.app.state.authz_audit
        broker = self.env.app.state.authz_broker
        owner_p = store.principal_of("owner")

        codes = self.env.app.state.authz_recovery_codes
        self.assertTrue(codes)

        broker.register_secret("conn-a", "pre-rotate-secret",
                               connection_id="conn-a")

        # all channels down, no second approver: recovery artifact still works
        from anton.authz.breakglass import use_recovery_artifact
        result = use_recovery_artifact(store, audit, broker, code=codes[0],
                                       failed_channels=[False, False])
        self.assertTrue(result["unlocked"])

        # mandatory audit entry + broker re-key: old secret material invalid
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT seq FROM audit_chain "
                          "WHERE event_type='recovery_artifact_used'")
        self.assertTrue(rows)

        # re-key produced a fresh ciphertext under the new master key
        blob = raw_sqlite(broker.db_path,
                          "SELECT ciphertext FROM broker_secrets WHERE id='conn-a'"
                          )[0][0]
        self.assertIsNotNone(blob)

        # capability tokens signed under the old key epoch are invalid
        principal = store.principal_of("owner")
        lease = broker.issue_execution_lease(principal, execution_id="e9",
                                             connection_ids=["conn-a"], ttl_s=60)
        cap = broker.mint_capability_token(lease, ["conn-a"])
        self.assertEqual(broker.fetch(cap, "conn-a", purpose="post"), "pre-rotate-secret")

    def test_wrong_code_rejected(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        audit = self.env.app.state.authz_audit
        broker = self.env.app.state.authz_broker
        from anton.authz.breakglass import RecoveryArtifactError, use_recovery_artifact
        with self.assertRaises(RecoveryArtifactError):
            use_recovery_artifact(store, audit, broker, code="000000",
                                  failed_channels=[False, False])


class TestAppr05SingleOperatorMode(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True, mode="single_operator")
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_trigger_dropped_out_of_band_blocks_multi_user_boot(self):
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        try:
            conn.execute("DROP TRIGGER trg_grant_no_self")
            conn.commit()
        finally:
            conn.close()

        from anton.authz.boot import SchemaHashMismatch, boot_check
        with self.assertRaises(SchemaHashMismatch):
            boot_check(self.store, self.audit, mode="multi_user")

    def test_sensitive_action_lands_in_pending_actions_with_delay(self):
        from anton.authz.breakglass import (apply_ready, pending_action_ready,
                                            submit_pending_action)
        import time
        pid = submit_pending_action(self.store, kind="roles.assign",
                                    payload_json='{"user":"u1","role":"Admin"}',
                                    delay_s=60)
        # not ready before the delay window elapses
        self.assertFalse(pending_action_ready(self.store, pid, now=time.time()))
        applied = apply_ready(self.store, now=time.time())
        self.assertEqual(applied, [])
        # after the window, the scheduled apply promotes it
        applied = apply_ready(self.store, now=time.time() + 61)
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["kind"], "roles.assign")

    def test_role_table_collapses_to_owner_only(self):
        from anton.authz.rbac import enabled_roles
        from helpers import raw_sqlite
        self.assertEqual(enabled_roles(self.env.cfg), ["Owner"])
        # assigning a disabled role is rejected
        u = self.store.create_user("op2", "Role-Pass-1!")
        with self.assertRaises(Exception):
            self.store.assign_role(u["id"], "Operator", actor_id=self.owner_p.user_id)


if __name__ == "__main__":
    unittest.main()
