"""Regression tests for adversarial review run 3 findings (2026-08-23).

Run 3 (independent reviewers on deepseek-v4-flash) survived these against
HEAD 82ba79c. Each test pins one finding so it cannot silently regress.
"""
import time
import unittest

from helpers import build_env, raw_sqlite


class R3A1LegacyApprovalSelfDeal(unittest.TestCase):
    """MAJOR R3A-1: Approver must not self-approve legacy money/outbound
    approvals — approver != initiator must hold on the scheduler's gate."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        owner = self.store.get_user_by_username("owner")
        appr = self.store.create_user("approver01", "Role-Pass-1!")
        self.store.assign_role(appr["id"], "Approver", actor_id=owner["id"])
        self.h = self._session_headers(appr)

    def _session_headers(self, user):
        store = self.store
        dev = store.create_device(user["id"], "t")
        return {"Authorization": "Bearer " + store.create_session(user["id"], dev)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_approver_cannot_approve_own_legacy_approval(self):
        r = self.env.client.post("/api/approvals", json={
            "action": "wire", "amount": "50000.00", "recipient": "x"}, headers=self.h)
        self.assertEqual(r.status_code, 200)
        aid = r.json()["id"]
        # same human deciding their own approval is rejected at the DB layer
        r = self.env.client.post(f"/api/approvals/{aid}/resolve",
                                 json={"decision": "approve"}, headers=self.h)
        self.assertIn(r.status_code, (400, 403, 409))
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE id=?", (aid,))
        self.assertEqual(rows[0][0], "pending")

    def test_owner_can_still_approve_other_peoples_request(self):
        from anton.authz.store import open_store
        store = open_store(self.env.authz_db)
        owner = store.get_user_by_username("owner")
        r = self.env.client.post("/api/approvals", json={
            "action": "wire", "amount": "100.00", "recipient": "y"}, headers=self.h)
        aid = r.json()["id"]
        oh = self._session_headers(owner)
        r = self.env.client.post(f"/api/approvals/{aid}/resolve",
                                 json={"decision": "approve"}, headers=oh)
        self.assertEqual(r.status_code, 200)


class R3A2LeaseMintPeerUid(unittest.TestCase):
    """MAJOR R3A-2: lease/mint socket ops must be peer-uid attested too."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker
        self.broker.register_secret("conn-a", "v", connection_id="conn-a")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_lease_and_mint_denied_for_unresolvable_peer(self):
        from anton.authz import broker as broker_mod
        from anton.authz.broker import BrokerClient, BrokerDenied
        owner = self.store.get_user_by_username("owner")
        dev = self.store.create_device(owner["id"], "t")
        session_token = self.store.create_session(owner["id"], dev)
        client = BrokerClient(self.broker.socket_path)
        with unittest.mock.patch.object(broker_mod, "_peer_uid", return_value=None):
            with self.assertRaises(BrokerDenied):
                client.issue_lease(session_token, "exec-x", ["conn-a"], ttl_s=60)
        cap = self._cap()
        with unittest.mock.patch.object(broker_mod, "_peer_uid", return_value=99999):
            with self.assertRaises(BrokerDenied):
                client.mint("bogus-lease", ["conn-a"])
        # fetch still fails closed
        with unittest.mock.patch.object(broker_mod, "_peer_uid", return_value=None):
            with self.assertRaises(BrokerDenied):
                client.fetch(cap, "conn-a", purpose="t")

    def _cap(self):
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id="e1", connection_ids=["conn-a"], ttl_s=60)
        return self.broker.mint_capability_token(lease, ["conn-a"])


class R3A3MigrationBodyWeakening(unittest.TestCase):
    """MAJOR R3A-3: same-name trigger body weakening must fail the gate."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_weakened_trigger_body_rejected_and_baseline_pristine(self):
        from anton.authz.boot import MigrationIntegrityError, run_migration
        from anton.authz.principals import MigrationPrincipal
        before = self.store.kv_get("schema_hash")
        hostile = ("DROP TRIGGER IF EXISTS trg_grant_no_self; "
                   "CREATE TRIGGER trg_grant_no_self BEFORE INSERT ON "
                   "connection_grants BEGIN SELECT RAISE(IGNORE); END;")
        with self.assertRaises(MigrationIntegrityError):
            run_migration(self.store, self.audit,
                          principal=MigrationPrincipal(migration_name="weak-1"),
                          name="weak-1", sql=hostile)
        self.assertEqual(before, self.store.kv_get("schema_hash"))
        # the weakened trigger must not be trusted: self-grant still rejected
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        with self.assertRaises(Exception):
            conn.execute("INSERT INTO role_assignments(user_id, role,"
                         " actor_id, ts) VALUES('u','Admin','u','now')")


class R3A4DecisionRowsAppendOnly(unittest.TestCase):
    """MAJOR R3A-4: approval_decisions / approval_executions must be
    append-only at the schema level — no UPDATE/DELETE forgery."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _approval(self):
        from anton.authz.approvals import create_approval
        alice = self.store.create_user("alice1", "Role-Pass-1!")
        return create_approval(self.store, self.audit,
                               initiator=self.store.principal_of("alice1"),
                               payload={"k": 1}, policy_version="v1")

    def test_decision_row_update_rejected(self):
        from anton.authz.approvals import approve
        aid = self._approval()
        approve(self.store, self.audit, approver=self.owner_p, approval_id=aid)
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE approval_decisions SET decision='rejected' "
                         "WHERE approval_id=?", (aid,))
            conn.commit()
        conn.rollback()

    def test_decision_row_delete_rejected(self):
        from anton.authz.approvals import approve
        aid = self._approval()
        approve(self.store, self.audit, approver=self.owner_p, approval_id=aid)
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM approval_decisions WHERE approval_id=?",
                         (aid,))
            conn.commit()
        conn.rollback()

    def test_execution_row_delete_rejected(self):
        from anton.authz.approvals import (approve, create_approval,
                                           execute_approved)
        from helpers import raw_sqlite
        alice = self.store.create_user("alice2", "Role-Pass-1!")
        aid = create_approval(self.store, self.audit,
                              initiator=self.store.principal_of("alice2"),
                              payload={"k": 2}, policy_version="v1")
        approve(self.store, self.audit, approver=self.owner_p, approval_id=aid)
        execute_approved(self.store, self.audit, approval_id=aid,
                         current_payload={"k": 2})
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM approval_executions WHERE approval_id=?",
                         (aid,))
            conn.commit()


class R3B1LoginAudited(unittest.TestCase):
    """MINOR R3B-1: logins must be recorded in the tamper-evident chain."""

    def test_login_events_in_chain(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        ok = self.env.client.post("/api/auth/login",
                                  json={"username": "owner",
                                        "password": "Owner-Pass-1!"})
        self.assertEqual(ok.status_code, 200)
        bad = self.env.client.post("/api/auth/login",
                                   json={"username": "owner", "password": "x"})
        self.assertIn(bad.status_code, (401, 429))
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT event_type FROM audit_chain "
                          "WHERE event_type LIKE 'login%'")
        types = [r[0] for r in rows]
        self.assertIn("login", types)


class R3B4BreakglassRateLimitAtomic(unittest.TestCase):
    """MINOR R3B-4: rate-limit check must be inside the write critical
    section (concurrent requests cannot double-elevate)."""

    def test_concurrent_breakglass_respects_limit(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        audit = self.env.app.state.authz_audit
        owner_p = store.principal_of("owner")
        import threading
        results = []
        errors = []

        def attempt():
            from anton.authz.breakglass import request_breakglass
            try:
                results.append(request_breakglass(
                    store, audit, principal=owner_p, reason="burst",
                    duration_min=5, channels=[lambda m: True],
                    rate_limit=(1, 3600)))
            except Exception as e:
                errors.append(e)

        ts = [threading.Thread(target=attempt) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(errors), 2)  # exactly one elevated, two rate-limited
        self.assertEqual(len(results), 1)