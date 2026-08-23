"""CI-T-DATA-01..03 — §2 dual-layer enforcement (spec v1.1, FROZEN)."""
import unittest

from helpers import build_env


class TestData01DualLayer(unittest.TestCase):
    """CI-T-DATA-01: fail-closed route audit in CI; repo lint for principal
    params; principal-required data functions raise without one."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_synthetic_unguarded_app_is_flagged_by_route_auditor(self):
        from fastapi import FastAPI
        from anton.authz.guards import audit_routes_behavioral

        rogue = FastAPI()

        @rogue.get("/rogue-data")
        def rogue_data():
            return {"leak": True}

        findings = audit_routes_behavioral(rogue)
        self.assertTrue(any("rogue-data" in f for f in findings),
                        "auditor must flag an unguarded route")

    def test_guarded_app_passes_route_auditor_and_rogue_post_startup_route_is_still_401(self):
        from fastapi import FastAPI
        from anton.authz.guards import audit_routes_behavioral
        findings = audit_routes_behavioral(self.env.app)
        self.assertEqual(findings, [], f"unguarded routes: {findings}")

        # a route registered post-startup with no guard still cannot serve
        # data unauthenticated (middleware is fail-closed, not startup-only)
        @self.env.app.get("/api/authz/late-route")
        def late():
            return {"secret": True}

        r = self.env.client.get("/api/authz/late-route")
        self.assertIn(r.status_code, (401, 403))

    def test_repo_lint_flags_io_function_without_principal_param(self):
        import os
        import tempfile
        from anton.authz.guards import lint_repo_file
        bad = '''
def leak_all(conn):
    return conn.execute("SELECT * FROM secrets").fetchall()

def fine(conn, principal):
    return conn.execute("SELECT 1").fetchall()

def not_sql(conn, helper):  # no I/O call -> not flagged
    return helper(conn)
'''
        fd, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(fd, "w") as f:
            f.write(bad)
        try:
            violations = lint_repo_file(path)
            self.assertEqual(violations, ["leak_all"])
        finally:
            os.unlink(path)

    def test_get_connection_credential_without_principal_raises(self):
        from anton.authz.datalayer import get_connection_credential
        from anton.authz.store import open_store
        store = open_store(self.env.authz_db)
        with self.assertRaises(TypeError):
            get_connection_credential(store, connection_id="conn-a")  # noqa


class TestData02ExecutorRecheck(unittest.TestCase):
    """CI-T-DATA-02: grant revoked between job start and tool call; executor
    refuses and emits authorization-denied audit row."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        from anton.authz.store import open_store
        self.store = open_store(self.env.authz_db)
        self.broker = self.env.app.state.authz_broker
        owner = self.store.get_user_by_username("owner")
        op = self.store.create_user("operator1", "Role-Pass-1!")
        self.store.assign_role(op["id"], "Operator", actor_id=owner["id"])
        self.operator = self.store.get_user_by_username("operator1")
        self.operator_p = self.store.principal_of("operator1")
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_revoked_grant_blocks_tool_call_mid_job(self):
        from anton.authz.grants import create_grant, revoke_grant
        from anton.authz.audit import AuditLog
        audit = AuditLog(self.store)

        grant_id = create_grant(
            self.store, audit,
            granter=self.store.principal_of("owner"),
            grantee_user_id=self.operator["id"],
            connection_id="conn-a", scope="use", oauth_scopes=["calendar.read"])

        # job starts: lease issued while the grant exists
        lease = self.broker.issue_execution_lease(
            self.store.principal_of("operator1"), execution_id="exec-42",
            connection_ids=["conn-a"], ttl_s=300)

        # grant revoked between job start and the tool call
        revoke_grant(self.store, audit,
                     actor=self.store.principal_of("owner"), grant_id=grant_id)

        # executor-side re-check before the tool call must refuse
        from anton.authz.broker import BrokerDenied
        with self.assertRaises(BrokerDenied):
            cap = self.broker.mint_capability_token(lease, ["conn-a"])
            self.broker.fetch(cap, "conn-a", purpose="tool-call")

        rows = self._audit_rows("authorization_denied")
        self.assertTrue(any("conn-a" in (r[0] or "") for r in rows),
                        "expected authorization-denied audit row naming conn-a")

    def _audit_rows(self, event_type):
        from helpers import raw_sqlite
        return raw_sqlite(self.env.authz_db,
                          "SELECT payload_json FROM audit_chain "
                          "WHERE event_type=?", (event_type,))


class TestData03NoGodPrincipal(unittest.TestCase):
    """CI-T-DATA-03: SystemPrincipal only within allowlisted job registry."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        from anton.authz.store import open_store
        from anton.authz.audit import AuditLog
        self.store = open_store(self.env.authz_db)
        self.audit = AuditLog(self.store)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_system_action_outside_registry_raises_alarm(self):
        from anton.authz.datalayer import JobRegistryAlarm, run_scheduled_job
        from anton.authz.principals import SystemPrincipal
        with self.assertRaises(JobRegistryAlarm):
            run_scheduled_job(self.store, self.audit,
                             SystemPrincipal(job_id="unknown-job"))

    def test_registered_system_job_allowed_and_loudly_logged(self):
        from anton.authz.datalayer import run_scheduled_job
        from anton.authz.principals import SystemPrincipal
        run_scheduled_job(self.store, self.audit, SystemPrincipal(job_id="e2e-canary"))
        from helpers import raw_sqlite
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT event_type FROM audit_chain WHERE event_type='system_action'")
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
