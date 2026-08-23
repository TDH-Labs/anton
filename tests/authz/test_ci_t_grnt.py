"""CI-T-GRNT-01..04 — §4 connection grants & self-grant prevention."""
import unittest

from helpers import build_env, raw_sqlite


class GrantTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner = self.store.get_user_by_username("owner")
        self.owner_p = self.store.principal_of("owner")
        self.alice = self.store.create_user("alice", "Role-Pass-1!")
        self.bob = self.store.create_user("bob", "Role-Pass-1!")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)


class TestGrnt01ScopeRecording(GrantTestBase):
    def test_full_grant_response_hides_refresh_token_and_revoke_rotates(self):
        from anton.authz.grants import create_grant, grant_response, revoke_grant

        rotated = {}
        self.store.token_rotator = lambda connection_id: rotated.update(
            {connection_id: "rotated-token"})

        grant_id = create_grant(
            self.store, self.audit, granter=self.owner_p,
            grantee_user_id=self.alice["id"], connection_id="conn-qbo",
            scope="full", oauth_scopes=["com.intuit.quickbooks.accounting"])

        resp = grant_response(self.store, grant_id)
        self.assertIn("scope", resp)
        blob = str(resp).lower()
        self.assertNotIn("refresh", blob)
        self.assertNotIn("token_secret", blob)

        revoke_grant(self.store, self.audit, actor=self.owner_p, grant_id=grant_id)
        self.assertEqual(rotated.get("conn-qbo"), "rotated-token")


class TestGrnt02SelfGrantSchemaEnforcement(GrantTestBase):
    def test_direct_sql_self_grant_rejected_by_trigger(self):
        with self.assertRaises(Exception):
            raw_sqlite  # noqa - keep linters quiet about unused
            import sqlite3
            conn = sqlite3.connect(self.env.authz_db)
            try:
                conn.execute(
                    "INSERT INTO connection_grants(granter_id, grantee_id, "
                    "connection_id, scope, oauth_scopes_json, policy_version, ts) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (self.alice["id"], self.alice["id"], "conn-x", "use", "[]",
                     "v1", "now"))
            finally:
                conn.close()

    def test_mutual_escalation_chain_rejected(self):
        from anton.authz.grants import create_grant, MutualEscalationError
        from anton.authz.audit import AuditLog
        audit = self.audit
        create_grant(self.store, audit, granter=self.owner_p,
                     grantee_user_id=self.alice["id"],
                     connection_id="c1", scope="use", oauth_scopes=[])
        # alice (now holding a grant) grants back to owner -> escalation chain
        with self.assertRaises(MutualEscalationError):
            create_grant(self.store, audit, granter=self.store.principal_of("alice"),
                         grantee_user_id=self.owner["id"],
                         connection_id="c2", scope="use", oauth_scopes=[])

    def test_ownership_transfer_self_directed_rejected(self):
        from anton.authz.grants import transfer_ownership, SelfGrantError
        with self.assertRaises(SelfGrantError):
            transfer_ownership(self.store, self.audit,
                               actor=self.owner_p, target_user_id=self.owner["id"],
                               connection_id="conn-z")


class TestGrnt03SoleAdminEscapeHatch(GrantTestBase):
    def test_sole_admin_self_elevation_requires_breakglass(self):
        from anton.authz.store import open_store
        s = self.env.app.state.authz_store
        # owner is sole admin; direct schema-level self role change must abort
        with self.assertRaises(Exception):
            import sqlite3
            conn = sqlite3.connect(self.env.authz_db)
            try:
                conn.execute(
                    "INSERT INTO role_assignments(user_id, role, actor_id, ts) "
                    "VALUES(?,?,?,?)", (self.owner["id"], "Admin",
                                        self.owner["id"], "now"))
                conn.commit()
            finally:
                conn.close()

    def test_breakglass_path_writes_audit_and_notifications(self):
        from anton.authz.breakglass import request_breakglass
        delivered = []
        channels = [lambda msg: delivered.append(("a", msg)) or True,
                    lambda msg: (_ for _ in ()).throw(RuntimeError("down"))]
        event = request_breakglass(
            self.store, self.audit, principal=self.owner_p,
            reason="sole-admin recovery", duration_min=15, channels=channels)
        self.assertTrue(event["elevated"])
        self.assertEqual(event["channels_failed"], 1)
        self.assertEqual(len(delivered), 1)
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT seq FROM audit_chain WHERE event_type='breakglass'")
        self.assertTrue(rows)
        # elevation active -> self role change now permitted at schema level
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        try:
            conn.execute(
                "INSERT INTO role_assignments(user_id, role, actor_id, ts) "
                "VALUES(?,?,?,?)", (self.owner["id"], "Admin", self.owner["id"], "now"))
            conn.commit()
        finally:
            conn.close()


class TestGrnt04ScopeHygiene(GrantTestBase):
    def test_unused_scope_report_and_release_gate(self):
        from anton.authz.grants import (ScopeHygieneError, create_grant,
                                        scope_diff_report)
        create_grant(self.store, self.audit, granter=self.owner_p,
                     grantee_user_id=self.alice["id"], connection_id="fixture-mail",
                     scope="full",
                     oauth_scopes=["mail.write", "drive.write", "contacts.write"])
        # code only uses calendar-read on this connector
        self.store.record_used_scopes("fixture-mail", ["calendar.read"])

        report = scope_diff_report(self.store)
        flagged = {v["connection_id"]: set(v["unused_scopes"])
                   for v in report if v["unused_scopes"]}
        self.assertIn("fixture-mail", flagged)
        self.assertEqual(flagged["fixture-mail"],
                         {"mail.write", "drive.write", "contacts.write"})
        with self.assertRaises(ScopeHygieneError):
            from anton.authz.grants import release_gate_check
            release_gate_check(report)


if __name__ == "__main__":
    unittest.main()
