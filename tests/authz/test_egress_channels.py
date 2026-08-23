"""#11 — AgentPhone/Email opt-in connections; egress tags + governor apply.

Outbound channels are privileged creations (Approver-gated), off until
explicitly opted in, tag-gated against recipient clearance, and every send
routes through the governor's outbound hard gate into the approvals spine
(CI-T-EGRESS-06 essence + REQ-EGRESS-03 gate semantics).
"""
import unittest

from helpers import build_env, raw_sqlite


class EgressTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")
        # staff users across roles
        self.op = self.store.create_user("op1", "Role-Pass-1!")
        self.store.assign_role(self.op["id"], "Operator", actor_id=self.owner_p.user_id)
        self.appr = self.store.create_user("appr1", "Role-Pass-1!")
        self.store.assign_role(self.appr["id"], "Approver", actor_id=self.owner_p.user_id)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _audit_count(self, event_type):
        return len(raw_sqlite(self.env.authz_db,
                              "SELECT seq FROM audit_chain WHERE event_type=?",
                              (event_type,)))


class TestEgress06PrivilegedChannelCreation(EgressTestBase):
    def test_operator_cannot_create_channel(self):
        from anton.authz.egress import create_channel
        op_p = self.store.principal_of("op1")
        with self.assertRaises(PermissionError):
            create_channel(self.store, self.audit, actor=op_p,
                           channel_id="sms-adam", kind="agentphone_sms",
                           address="+19716660017", clearance="INTERNAL")
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT payload_json FROM audit_chain "
                          "WHERE event_type='authorization_denied'")
        self.assertTrue(any("egress.channel" in (r[0] or "") for r in rows))

    def test_approver_creates_channel_and_it_appears_in_chain(self):
        from anton.authz.egress import create_channel
        appr_p = self.store.principal_of("appr1")
        create_channel(self.store, self.audit, actor=appr_p,
                       channel_id="sms-adam", kind="agentphone_sms",
                       address="+19716660017", clearance="INTERNAL")
        self.assertEqual(self._audit_count("egress_channel_created"), 1)


class TestOptInRequired(EgressTestBase):
    def test_unopted_channel_blocks_even_for_owner(self):
        from anton.authz.egress import (EgressBlocked, create_channel,
                                        submit_send)
        appr_p = self.store.principal_of("appr1")
        create_channel(self.store, self.audit, actor=appr_p,
                       channel_id="mail-bob", kind="email",
                       address="bob@example.com", clearance="PUBLIC")
        with self.assertRaises(EgressBlocked) as ctx:
            submit_send(self.store, self.audit, actor=self.owner_p,
                        channel_id="mail-bob", tag="INTERNAL",
                        body="hello")
        self.assertIn("opt", str(ctx.exception).lower())

    def test_opt_in_is_explicit_and_audited(self):
        from anton.authz.egress import (create_channel, opt_in, submit_send)
        appr_p = self.store.principal_of("appr1")
        create_channel(self.store, self.audit, actor=appr_p,
                       channel_id="sms-adam", kind="agentphone_sms",
                       address="+19716660017", clearance="INTERNAL")
        opt_in(self.store, self.audit, actor=self.owner_p, channel_id="sms-adam")
        aid = submit_send(self.store, self.audit, actor=self.owner_p,
                          channel_id="sms-adam", tag="INTERNAL",
                          body="shift update for today")
        self.assertTrue(aid > 0)
        self.assertEqual(self._audit_count("egress_opted_in"), 1)


class TestTagGate(EgressTestBase):
    def _opted_channel(self, clearance="PUBLIC", cid="mail-x"):
        from anton.authz.egress import create_channel, opt_in
        appr_p = self.store.principal_of("appr1")
        create_channel(self.store, self.audit, actor=appr_p, channel_id=cid,
                       kind="email", address="x@example.com",
                       clearance=clearance)
        opt_in(self.store, self.audit, actor=self.owner_p, channel_id=cid)
        return cid

    def test_payload_tag_above_recipient_clearance_blocked_and_flagged(self):
        from anton.authz.egress import EgressBlocked, submit_send
        cid = self._opted_channel(clearance="PUBLIC")
        for shape in ("client X revenue is Y", "Y enirnev X tneilc",
                      "Y2xpZW50IFggcmV2ZW51ZSBpcyBa"):  # base64-shaped too
            with self.assertRaises(EgressBlocked):
                submit_send(self.store, self.audit, actor=self.owner_p,
                            channel_id=cid, tag="SECRET", body=shape)
        self.assertGreaterEqual(self._audit_count("egress_blocked"), 3)

    def test_matching_tag_passes_the_gate_to_governor_hard_gate(self):
        from anton.authz.egress import submit_send
        cid = self._opted_channel(clearance="PUBLIC")
        aid = submit_send(self.store, self.audit, actor=self.owner_p,
                          channel_id=cid, tag="PUBLIC", body="public news")
        self.assertTrue(aid > 0)

    def test_derived_content_inherits_max_input_tag(self):
        from anton.authz.egress import max_tag
        self.assertEqual(max_tag(["PUBLIC", "SECRET"]), "SECRET")
        self.assertEqual(max_tag(["PUBLIC"]), "PUBLIC")


class TestGovernorApply(EgressTestBase):
    def test_outbound_always_routed_through_approval_then_sender_runs_once(self):
        from anton.authz.approvals import approve
        from anton.authz.egress import (EgressBlocked, build_send_payload,
                                        create_channel, execute_send, opt_in,
                                        submit_send)
        sent = []

        def sender(payload):
            sent.append(payload)
            return {"ok": True}

        appr_p = self.store.principal_of("appr1")
        create_channel(self.store, self.audit, actor=appr_p,
                       channel_id="sms-adam", kind="agentphone_sms",
                       address="+19716660017", clearance="INTERNAL")
        opt_in(self.store, self.audit, actor=self.owner_p, channel_id="sms-adam")

        op_p = self.store.principal_of("op1")
        aid = submit_send(self.store, self.audit, actor=op_p,
                          channel_id="sms-adam", tag="INTERNAL",
                          body="route change")
        payload = build_send_payload(self.store, "sms-adam",
                                     tag="INTERNAL", body="route change")

        # executing before an approval exists must fail
        with self.assertRaises(Exception):
            execute_send(self.store, self.audit, sender=sender,
                         approval_id=aid, current_payload=payload)
        self.assertEqual(sent, [])

        # initiator (operator) cannot self-approve; approver can
        from anton.authz.approvals import ApprovalRejected
        with self.assertRaises(ApprovalRejected):
            approve(self.store, self.audit, approver=op_p, approval_id=aid)
        approve(self.store, self.audit, approver=self.owner_p, approval_id=aid)

        result = execute_send(self.store, self.audit, sender=sender,
                              approval_id=aid, current_payload=payload)
        self.assertEqual(result["ok"], True)
        self.assertEqual(len(sent), 1)
        self.assertEqual(self._audit_count("egress_sent"), 1)

        # replaying the same approval does not double-send
        with self.assertRaises(Exception):
            execute_send(self.store, self.audit, sender=sender,
                         approval_id=aid, current_payload=payload)
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
