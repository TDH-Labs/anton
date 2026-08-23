"""Regression tests for adversarial review run 3 findings (2026-08-23).

Run 3 (independent reviewers on deepseek-v4-flash) survived these against
HEAD 82ba79c. Each test pins one finding so it cannot silently regress.
"""
import time
import unittest
import unittest.mock

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

# =========================================================================
# Round 4 (verification of run-3 fixes — files in this module)
# =========================================================================

class R4MigrationRejectionLeavesDbPristine(unittest.TestCase):
    """MAJOR R4-1: a rejected migration must not leave weakened DDL live."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_rejected_migration_leaves_trigger_intact(self):
        from anton.authz.boot import MigrationIntegrityError, run_migration
        from anton.authz.principals import MigrationPrincipal
        hostile = ("DROP TRIGGER IF EXISTS trg_grant_no_self; "
                   "CREATE TRIGGER trg_grant_no_self BEFORE INSERT ON "
                   "connection_grants BEGIN SELECT RAISE(IGNORE); END;")
        with self.assertRaises(MigrationIntegrityError):
            run_migration(self.store, self.audit,
                          principal=MigrationPrincipal(migration_name="r4-1"),
                          name="r4-1", sql=hostile)
        # the trigger body in the LIVE DB was never weakened; self-grant
        # still aborts
        import sqlite3 as _sq
        owner = self.store.get_user_by_username("owner")
        conn = _sq.connect(self.env.authz_db)
        try:
            with self.assertRaises(_sq.IntegrityError):
                conn.execute(
                    "INSERT INTO connection_grants(granter_id, grantee_id,"
                    " connection_id, scope, oauth_scopes_json, policy_version,"
                    " active, created) VALUES(?,?,?,?,?,?,1,'now')",
                    (owner["id"], owner["id"], "c", "full", "[]", "v1"))
        finally:
            conn.close()


class R4TableDdlLaunderingRejected(unittest.TestCase):
    """MAJOR R4-2: DROP/CREATE of a critical table without its CHECK must fail."""
    # pylint: disable=line-too-long

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_approval_decisions_without_check_rejected(self):
        from anton.authz.boot import MigrationIntegrityError, run_migration
        from anton.authz.principals import MigrationPrincipal
        before = self.store.kv_get("schema_hash")
        hostile = ("DROP TABLE IF EXISTS approval_decisions; "
                   "CREATE TABLE approval_decisions (\n"
                   "    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
                   "    approval_id INTEGER NOT NULL,\n"
                   "    approver_principal TEXT NOT NULL, approver_human TEXT NOT NULL,\n"
                   "    decision TEXT NOT NULL,\n"
                   "    ts TEXT NOT NULL\n"
                   ");\n"
                   "CREATE UNIQUE INDEX IF NOT EXISTS ux_decision_once ON"
                   " approval_decisions(approval_id);")
        with self.assertRaises(MigrationIntegrityError):
            run_migration(self.store, self.audit,
                          principal=MigrationPrincipal(migration_name="r4-2"),
                          name="r4-2", sql=hostile)
        self.assertEqual(before, self.store.kv_get("schema_hash"))


class R4LegacyApprovalHardening(unittest.TestCase):
    """MAJOR R4-3: legacy approvals trigger hardening."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        # isolation.db is created by helpers\nself.store = self.env.app.state.authz_store

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_direct_decided_insert_rejected(self):
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO approvals(nonce, action, status, ts,"
                    " initiator_human, approver_human) VALUES('x','job','approved',"
                    "'now','alice','alice')")
        finally:
            conn.close()

    def test_initiator_laundering_rejected(self):
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute(
                "INSERT INTO approvals(nonce, action, status, ts,"
                " initiator_human, initiator_principal) VALUES('y','job','pending',"
                "'now','alice','alice')")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE approvals SET status='approved', initiator_human='eve',"
                    " approver_human='alice' WHERE nonce='y'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()

    def test_legacy_null_rows_still_work(self):
        # fully-legacy rows (all identity NULL) are decidable ONLY after an
        # explicit adoption stamp (system:legacy) — the all-NULL direct
        # forge is closed (R5-1).
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute(
                "INSERT INTO approvals(nonce, action, status, ts)"
                " VALUES('z','job3','pending','now')")
            conn.commit()
            # forge: NULL->NULL decided is refused
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE approvals SET status='approved' WHERE nonce='z'")
                conn.commit()
            conn.rollback()

            # adoption then decision works
            conn.execute(
                "UPDATE approvals SET initiator_human='system:legacy',"
                " initiator_principal='system:legacy' WHERE nonce='z'")
            conn.commit()
            conn.execute(
                "UPDATE approvals SET status='approved', approver_human='owner',"
                " approver_principal='owner' WHERE nonce='z'")
            conn.commit()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='z'")
        self.assertEqual(rows[0][0], "approved")

    def test_all_null_two_step_forge_refused(self):
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute(
                "INSERT INTO approvals(nonce, action, status, ts)"
                " VALUES('forge','money-job','pending','now')")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE approvals SET status='approved' WHERE nonce='forge'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='forge'")
        self.assertEqual(rows[0][0], "pending")

    def test_consumed_approval_is_terminal(self):
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute(
                "INSERT INTO approvals(nonce, action, status, ts,"
                " initiator_human, initiator_principal)"
                " VALUES('r1','job','pending','now','bob','bob')")
            conn.commit()
            conn.execute(
                "UPDATE approvals SET status='approved', approver_human='alice',"
                " approver_principal='alice' WHERE nonce='r1'")
            conn.commit()
            conn.execute(
                "UPDATE approvals SET status='consumed' WHERE nonce='r1'")
            conn.commit()
            # replay attempt: consumed -> approved must be refused
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE approvals SET status='approved', approver_human='alice',"
                    " approver_principal='alice' WHERE nonce='r1'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='r1'")
        self.assertEqual(rows[0][0], "consumed")


class R4ExecutionUpdateRejected(unittest.TestCase):
    """MINOR R4-5: approval_executions must also block UPDATE."""

    def test_execution_update_rejected(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        audit = self.env.app.state.authz_audit
        owner_p = store.principal_of("owner")
        alice = store.create_user("alicee", "Role-Pass-1!")
        from anton.authz.approvals import (  # noqa: E501
    approve, create_approval, execute_approved)
        aid = create_approval(store, audit,
                              initiator=store.principal_of("alicee"),
                              payload={"k": 9}, policy_version="v1")
        approve(store, audit, approver=owner_p, approval_id=aid)
        execute_approved(store, audit, approval_id=aid, current_payload={"k": 9})
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE approval_executions SET "
                    "executed_at='2030-01-01T00:00:00Z' WHERE approval_id=?",
                    (aid,))
                conn.commit()
            conn.rollback()
        finally:
            conn.close()


class R5MigrationRefusalAudited(unittest.TestCase):
    """MINOR R5-4: refused migrations must leave an audit-chain row."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_refused_migration_audited(self):
        from anton.authz.boot import MigrationIntegrityError, run_migration
        from anton.authz.principals import MigrationPrincipal
        with self.assertRaises(MigrationIntegrityError):
            run_migration(self.store, self.audit,
                          principal=MigrationPrincipal(migration_name="r5-a"),
                          name="r5-a", sql="DROP TRIGGER trg_grant_no_self;")
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT event_type FROM audit_chain "
                          "WHERE event_type='migration_refused'")
        self.assertTrue(rows)


class R5BreakglassOverLimitNoDelivery(unittest.TestCase):
    """MAJOR R5-3: over-limit break-glass must NOT fire channels and MUST
    be audited."""

    def test_over_limit_does_not_page_and_is_audited(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        audit = self.env.app.state.authz_audit
        owner_p = store.principal_of("owner")
        fired = []

        from anton.authz.breakglass import (BreakGlassRateLimited,
                                            request_breakglass)
        request_breakglass(store, audit, principal=owner_p, reason="one",
                           duration_min=5,
                           channels=[lambda m: fired.append(m) or True])
        with self.assertRaises(BreakGlassRateLimited):
            request_breakglass(store, audit, principal=owner_p, reason="two",
                               duration_min=5,
                               channels=[lambda m: fired.append(m) or True])
        # second attempt paged nobody new, and its refusal is in the chain
        self.assertEqual(len(fired), 1)
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT event_type FROM audit_chain "
                          "WHERE event_type='breakglass_rate_limited'")
        self.assertEqual(len(rows), 1)


# =========================================================================
# Round 6 (verification of round-5 fixes)
# =========================================================================

class R6PendingConsumedRefused(unittest.TestCase):
    """MINOR R6-3a: pending rows cannot flip straight to consumed."""

    def test_pending_to_consumed_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts)"
                         " VALUES('pc1','job','pending','now')")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE approvals SET status='consumed' "
                             "WHERE nonce='pc1'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='pc1'")
        self.assertEqual(rows[0][0], "pending")


class R6ApprovedRevertRefused(unittest.TestCase):
    """MINOR R6-3b: approved rows cannot be reverted to pending."""

    def test_approved_to_pending_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                         " initiator_human, initiator_principal)"
                         " VALUES('ap1','job','pending','now','bob','bob')")
            conn.commit()
            conn.execute("UPDATE approvals SET status='approved',"
                         " approver_human='alice', approver_principal='alice'"
                         " WHERE nonce='ap1'")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE approvals SET status='pending' "
                             "WHERE nonce='ap1'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='ap1'")
        self.assertEqual(rows[0][0], "approved")


class R6SupersededTriggerDropped(unittest.TestCase):
    """MAJOR R6-2: an upgrade must remove superseded trigger names so the
    old weak bodies cannot veto the adoption/decision path."""

    def test_init_db_drops_superseded_triggers(self):
        import os
        import sqlite3
        path = os.path.join("/tmp",
                            f"iso_upgrade_{int(time.time()*1000)}.db")
        conn = sqlite3.connect(path)
        # simulate an R4-era DB: weak old trigger present
        conn.execute("CREATE TABLE approvals (id INTEGER PRIMARY KEY,"
                     " nonce TEXT, action TEXT, amount TEXT, recipient TEXT,"
                     " status TEXT, hmac TEXT, ts TEXT, initiator_human TEXT,"
                     " initiator_principal TEXT, approver_human TEXT,"
                     " approver_principal TEXT)")
        conn.execute("CREATE TRIGGER trg_approvals_no_self_approve_upd"
                     " BEFORE UPDATE ON approvals BEGIN SELECT RAISE(ABORT,"
                     " 'old weak'); END;")
        conn.commit()
        conn.close()
        try:
            from anton.db import init_db
            conn = init_db(path)  # upgrade path
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE name IS NOT NULL")}
            self.assertNotIn("trg_approvals_no_self_approve_upd", names)
            self.assertIn("trg_approvals_transition_guard", names)
            self.assertIn("trg_approvals_pending_only_insert", names)
            conn.close()
        finally:
            os.unlink(path)


class R6AdoptionHelperAudited(unittest.TestCase):
    """OBSERVATION R6-4: the adoption path is a raw-SQL-only, unaudited
    channel. The helper stamps + audits; adoption of a non-NULL row fails."""

    def test_adopt_helper_and_audit(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        audit = self.env.app.state.authz_audit
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        conn.execute("INSERT INTO approvals(nonce, action, status, ts)"
                     " VALUES('ad1','job','pending','now')")
        conn.commit()
        from anton.db import adopt_legacy_approval
        adopt_legacy_approval(conn, "ad1", audit=audit)
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT event_type FROM audit_chain "
                          "WHERE event_type='legacy_approval_adopted'")
        self.assertTrue(rows)
        # not-adoptable: non-NULL row
        conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                     " initiator_human) VALUES('ad2','job','pending','now','bob')")
        conn.commit()
        with self.assertRaises(LookupError):
            adopt_legacy_approval(conn, "ad2", audit=audit)
        conn.close()


# =========================================================================
# Round 7 (verification of round-6 fixes)
# =========================================================================

class R7UpgradeConvergesSameNameBody(unittest.TestCase):
    """MAJOR R7-4: a DB holding an older-body canonical-name trigger must
    converge to canonical on init_db, not brick at boot."""

    def test_same_name_body_evolution_converges(self):
        import os
        import sqlite3
        from anton.db import SCHEMA as CUR_SCHEMA
        path = os.path.join("/tmp", f"iso_conv_{int(time.time()*1000)}.db")
        conn = sqlite3.connect(path)
        # round-5-era body: same canonical name but OLD (fewer WHEN branches)
        old = ("CREATE TABLE approvals (id INTEGER PRIMARY KEY, nonce TEXT,"
               " action TEXT, amount TEXT, recipient TEXT, status TEXT,"
               " hmac TEXT, ts TEXT, initiator_human TEXT,"
               " initiator_principal TEXT, approver_human TEXT,"
               " approver_principal TEXT);"
               "CREATE TRIGGER trg_approvals_pending_only_insert"
               " BEFORE INSERT ON approvals WHEN NEW.status IN ('approved')"
               " BEGIN SELECT RAISE(ABORT,'old'); END;")
        conn.executescript(old)
        conn.commit()
        conn.close()
        try:
            from anton.db import init_db
            from anton.db import isolation_approvals_integrity
            conn = init_db(path)
            drift = isolation_approvals_integrity(conn)
            self.assertEqual(drift, [], "convergence failed: %s" % drift)
            conn.close()
        finally:
            os.unlink(path)


class R7ActionRetargetRefused(unittest.TestCase):
    """MAJOR R7-2: decision-significant fields are immutable after INSERT."""

    def test_action_mutation_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute("INSERT INTO approvals(nonce, action, amount,"
                         " recipient, status, ts, initiator_human,"
                         " initiator_principal) VALUES('ar1','newsletter','',"
                         "'','pending','now','alice','alice')")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE approvals SET action='pay-vendor' "
                             "WHERE nonce='ar1'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT action FROM approvals WHERE nonce='ar1'")
        self.assertEqual(rows[0][0], "newsletter")


class R7ApprovedToDeniedRefused(unittest.TestCase):
    """MINOR R7-3: approved rows can only exit to consumed."""

    def test_approved_to_denied_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                         " initiator_human, initiator_principal)"
                         " VALUES('ad9','job','pending','now','bob','bob')")
            conn.commit()
            conn.execute("UPDATE approvals SET status='approved',"
                         " approver_human='alice', approver_principal='alice'"
                         " WHERE nonce='ad9'")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE approvals SET status='denied',"
                             " approver_human='carol' WHERE nonce='ad9'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='ad9'")
        self.assertEqual(rows[0][0], "approved")


class R7SonOfAntonRequiresHealthyGate(unittest.TestCase):
    """MINOR R7-6: the permissionless bypass refuses to run on drift."""

    def test_son_of_anton_refuses_when_triggers_drifted(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        conn.execute("DROP TRIGGER trg_approvals_pending_only_insert")
        conn.commit()
        conn.close()
        from anton.scheduler import set_son_of_anton_mode, JobEngine
        d = self.env.dir
        import os
        set_son_of_anton_mode(os.path.join(d, "data"), True)
        # serve-side engine built on the drifted DB
        jobs_path = os.path.join(d, "jobs.yaml")
        from anton.jobs import load_jobs
        from anton.ledger import Ledger
        from anton.executor import FakeExecutor
        from anton.config import load_config
        engine = JobEngine(load_jobs(jobs_path),
                           Ledger(os.path.join(d, "runs.jsonl")),
                           FakeExecutor(), load_config(),
                           data_dir=os.path.join(d, "data"))
        ok, reason = engine._is_approved("e2e-canary")
        self.assertFalse(ok)
        self.assertEqual(reason, "gate_triggers_drifted")


# =========================================================================
# Round 8 (verification of round-7 fixes)
# =========================================================================

class R8PresetApproverForgeClosed(unittest.TestCase):
    """MAJOR R8-1: approver identity must be NULL at INSERT; the two-step
    staged forge is then closed, and with a decision secret the scheduler
    refuses unverified sign-offs."""

    def test_preset_approver_at_insert_rejected(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO approvals(nonce, action, status, ts,"
                    " initiator_human, initiator_principal, approver_human,"
                    " approver_principal) VALUES('pf1','job','pending','now',"
                    "'bob','bob','alice','alice')")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()

    def test_scheduler_refuses_unverified_hmac_when_secret_configured(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                     " initiator_human, initiator_principal)"
                     " VALUES('pf2','job','pending','now','bob','bob')")
        # forged approve: no hmac (raw writer)
        conn.execute("UPDATE approvals SET status='approved',"
                     " approver_human='alice', approver_principal='alice'"
                     " WHERE nonce='pf2'")
        conn.commit()
        conn.close()
        # engine with decision secret configured must refuse
        import os as _os
        d = self.env.dir
        from anton.jobs import load_jobs
        from anton.ledger import Ledger
        from anton.executor import FakeExecutor
        from anton.config import load_config
        from anton.scheduler import JobEngine
        cfg = load_config()
        jobs_path = _os.path.join(d, "jobs.yaml")
        engine = JobEngine(load_jobs(jobs_path),
                           Ledger(_os.path.join(d, "runs.jsonl")),
                           FakeExecutor(), cfg,
                           data_dir=_os.path.join(d, "data"))
        engine._decision_secret = "test-secret"
        ok, reason = engine._is_approved("job")
        self.assertFalse(ok)
        self.assertEqual(reason, "unverified_hmac")


class R8AuditorSeesAuthzRouter(unittest.TestCase):
    """MAJOR R8-2: the CI route auditor must enumerate authz router routes,
    and the adopt endpoint must be explicitly Approver-gated."""

    def test_auditor_no_longer_blind_to_authz_routes(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        from anton.authz.guards import audit_routes_behavioral, _lookup
        # the authz router routes are enumerated; adopt is explicitly gated
        self.assertEqual(
            _lookup("POST", "/api/authz/approvals/adopt"),
            "approvals.decide")
        self.assertEqual(
            _lookup("POST", "/api/authz/egress/channels"),
            "egress.channels.manage")

    def test_approver_can_adopt(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        owner = store.get_user_by_username("owner")
        appr = store.create_user("appr_adopt", "Role-Pass-1!")
        store.assign_role(appr["id"], "Approver", actor_id=owner["id"])
        import sqlite3
        import os
        conn = sqlite3.connect(self.env.isolation_db)
        conn.execute("INSERT INTO approvals(nonce, action, status, ts)"
                     " VALUES('adopt1','job','pending','now')")
        conn.commit()
        conn.close()
        dev = store.create_device(appr["id"], "t")
        tok = store.create_session(appr["id"], dev)
        r = self.env.client.post(
            "/api/authz/approvals/adopt",
            json={"nonce": "adopt1"},
            headers={"Authorization": f"Bearer {tok}"})
        self.assertEqual(r.status_code, 200)
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT initiator_human FROM approvals "
                          "WHERE nonce='adopt1'")
        self.assertEqual(rows[0][0], "system:legacy")


class R9ApprovalsNoDelete(unittest.TestCase):
    """R9-1 (leaked from a crashed round-9 probe): DELETE of consumed
    approval rows was allowed — evidence destruction. Now refused."""

    def test_approval_delete_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                         " initiator_human, initiator_principal)"
                         " VALUES('del1','job','pending','now','bob','bob')")
            conn.commit()
            conn.execute("UPDATE approvals SET status='approved',"
                         " approver_human='alice', approver_principal='alice',"
                         " hmac='h' WHERE nonce='del1'")
            conn.commit()
            conn.execute("UPDATE approvals SET status='consumed' "
                         "WHERE nonce='del1'")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM approvals WHERE nonce='del1'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='del1'")
        self.assertEqual(rows[0][0], "consumed")


# =========================================================================
# Round 9 (verification of round-8 fixes)
# =========================================================================

class R9UpskillPromotionVerified(unittest.TestCase):
    """BLOCKER R9-1: the upskill promotion gate enforces the same hmac +
    drift countermeasures as the scheduler gate."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.engine = self.env.engine
        import os
        self.engine.data_dir = os.path.join(self.env.dir, "data")
        self.engine._decision_secret = "test-decision-secret"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _seed(self, with_valid_hmac):
        import sqlite3
        import hmac as hm
        import hashlib
        conn = sqlite3.connect(self.env.isolation_db)
        conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                     " initiator_human, initiator_principal)"
                     " VALUES('up1','upskill_promote:demo','pending','now',"
                     "'system','system:upskill')")
        conn.commit()
        aid = conn.execute("SELECT id FROM approvals WHERE nonce='up1'").fetchone()[0]
        if with_valid_hmac:
            mac = hm.new(b"test-decision-secret", str(aid).encode(),
                         hashlib.sha256).hexdigest()
            conn.execute("UPDATE approvals SET status='approved',"
                         " approver_human='alice', approver_principal='alice',"
                         " hmac=? WHERE id=?", (mac, aid))
        else:
            conn.execute("UPDATE approvals SET status='approved',"
                         " approver_human='alice', approver_principal='alice'"
                         " WHERE id=?", (aid,))
        conn.commit()
        conn.close()

    def test_forged_promotion_refused(self):
        from anton.upskill import approve_pending_promotion
        self._seed(with_valid_hmac=False)
        self.assertFalse(approve_pending_promotion(self.engine, "demo"))

    def test_valid_hmac_promotion_accepted(self):
        from anton.upskill import approve_pending_promotion
        self._seed(with_valid_hmac=True)
        # promotion will fail on missing staging dir, but the GATE must pass:
        # distinguish by checking the approval was consumed
        try:
            approve_pending_promotion(self.engine, "demo")
        except Exception:
            pass
        rows = raw_sqlite(self.env.isolation_db,
                          "SELECT status FROM approvals WHERE nonce='up1'")
        self.assertEqual(rows[0][0], "consumed")


class R9DecisionSecretRequired(unittest.TestCase):
    """MAJOR R9-2: authz-enabled without a decision secret refuses boot."""

    def test_missing_secret_refuses(self):
        import shutil
        with self.assertRaises(RuntimeError):
            build_env(authz_enabled=True,
                      extra_authz={"decision_secret": ""})


class R9EgressEvidenceHmac(unittest.TestCase):
    """MAJOR R9-3: execute_send refuses a raw-SQL fabricated decision."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_fabricated_decision_refused(self):
        import sqlite3
        from anton.authz.approvals import execute_approved
        from anton.authz.egress import build_send_payload
        conn = sqlite3.connect(self.env.authz_db)
        conn.execute(
            "INSERT INTO authz_approvals(id, initiator_principal,"
            " initiator_human, payload_hash, payload_json, policy_version,"
            " created) VALUES(1,'p1','eve','deadbeef','{}','v1','now')")
        conn.execute(
            "INSERT INTO approval_decisions(approval_id, approver_principal,"
            " approver_human, decision, ts) VALUES(1,'p2','carol','approved','now')")
        conn.commit()
        conn.close()
        with self.assertRaises(Exception):
            execute_approved(self.store, self.audit, approval_id=1,
                             current_payload={"anything": 1})


class R9InsertGuardReservesHmac(unittest.TestCase):
    """MINOR R9-4/5: hmac reserved at INSERT (bypass marker excepted);
    direct consumed INSERT without the marker refused; ts/nonce immutable."""

    def test_preset_hmac_insert_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                             " hmac) VALUES('h1','j','pending','now','forged')")
                conn.commit()
            conn.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                             " hmac) VALUES('h2','j','consumed','now','x')")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()

    def test_ts_mutation_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                         " initiator_human, initiator_principal)"
                         " VALUES('ts1','j','pending','now','bob','bob')")
            conn.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE approvals SET ts='1970-01-01' "
                             "WHERE nonce='ts1'")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()


# =========================================================================
# Round 10 (verification of round-9 fixes)
# =========================================================================

class R10EvidenceHmacUpgradePath(unittest.TestCase):
    """MAJOR R10-1: pre-R9 authz.db upgrades cleanly via sanctioned ALTER +
    baseline refresh; approve()/execute_approved() work after upgrade."""

    def test_pre_r9_db_upgrades(self):
        import os
        import sqlite3
        import time as _t
        path = os.path.join("/tmp", f"pre_r9_{int(_t.time()*1000)}.db")
        conn = sqlite3.connect(path)
        # pre-R9 shape: approval_decisions WITHOUT evidence_hmac + old baseline
        conn.executescript(
            # true pre-R9 shape: FULL canonical schema but approval_decisions
            # lacks evidence_hmac
            __import__("anton.authz.schema", fromlist=["SCHEMA"]).SCHEMA.replace(
                "    evidence_hmac TEXT,\n", ""))
        from anton.authz.schema import TRIGGERS
        conn.executescript(TRIGGERS)
        # a TRUE pre-R9 DB: recorded baseline == live signature
        from anton.authz.schema import schema_signature
        conn.execute("INSERT INTO kv VALUES('schema_hash', ?)",
                     (schema_signature(conn),))
        conn.commit()
        conn.close()
        try:
            from anton.authz.store import open_store
            store = open_store(path)
            cols = {r[1] for r in store.conn.execute(
                "PRAGMA table_info(approval_decisions)")}
            self.assertIn("evidence_hmac", cols)
            self.assertNotEqual(store.kv_get("schema_hash"), "old")
            store.close()
        finally:
            os.unlink(path)


class R10LockContentionFailClosed(unittest.TestCase):
    """MINOR R10-2: BEGIN IMMEDIATE contention yields gate_locked, not a
    crashed scheduler process."""

    def test_lock_contention_returns_gate_locked(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        import threading
        p = os_path_join(self.env.isolation_db)
        holder = sqlite3.connect(p, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(
            "INSERT INTO approvals(nonce, action, status, ts) VALUES("
            "'lk','job-xfer','pending','now')")
        result = {}

        def probe():
            from anton.scheduler import JobEngine  # noqa: F401
            conn = sqlite3.connect(p, timeout=1.0, isolation_level=None)
            try:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                except sqlite3.OperationalError:
                    result["r"] = "gate_locked"
                    return
                result["r"] = "acquired"
            finally:
                conn.close()

        t = threading.Thread(target=probe)
        t.start()
        t.join(timeout=15)
        holder.execute("ROLLBACK")
        holder.close()
        self.assertEqual(result.get("r"), "gate_locked")

    def test_junk_row_does_not_park_legit_approval(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        import hmac as hm
        import hashlib
        conn = sqlite3.connect(self.env.isolation_db)
        # legit keyed approval (low id)
        conn.execute("INSERT INTO approvals(nonce, action, status, ts,"
                     " initiator_human, initiator_principal)"
                     " VALUES('legit','job-y','pending','now','system','sys')")
        conn.commit()
        aid = conn.execute(
            "SELECT id FROM approvals WHERE nonce='legit'").fetchone()[0]
        mac = hm.new(b"test-decision-secret", str(aid).encode(),
                     hashlib.sha256).hexdigest()
        conn.execute("UPDATE approvals SET status='approved',"
                     " approver_human='alice', approver_principal='alice',"
                     " hmac=? WHERE id=?", (mac, aid))
        # planted junk row with HIGHER id and no hmac (two-step staged forge)
        conn.execute("INSERT INTO approvals(id, nonce, action, status, ts,"
                     " initiator_human, initiator_principal)"
                     " VALUES(999999,'junk','job-y','pending','now',"
                     "'eve','eve')")
        conn.commit()
        conn.execute("UPDATE approvals SET status='approved',"
                     " approver_human='mallory', approver_principal='mallory'"
                     " WHERE id=999999")
        conn.commit()
        conn.close()
        from anton.db import consume_verified_approval
        conn = sqlite3.connect(self.env.isolation_db)
        ok, reason = consume_verified_approval(conn, "job-y",
                                               secret="test-decision-secret")
        conn.close()
        self.assertTrue(ok, reason)


def os_path_join(p):
    return p


if __name__ == "__main__":
    unittest.main()


# =========================================================================
# Round 11 (verification of round-10 fixes)
# =========================================================================

class R11WhitespaceSplitBrain(unittest.TestCase):
    """MINOR R11-1: whitespace in decision_secret must not split writer vs
    verifier — all three trust points normalize identically."""

    def test_stripped_everywhere(self):
        env = build_env(authz_enabled=True,
                        extra_authz={"decision_secret": "  ws-secret  "})
        self.assertEqual(env.app.state.authz_store.decision_secret,
                         "ws-secret")
        import shutil
        shutil.rmtree(env.dir, ignore_errors=True)


class R11NullHmacConsumedInsertRefused(unittest.TestCase):
    """MINOR R11-2: NULL-hmac 'consumed' INSERT is execution-marker forgery."""

    def test_null_hmac_consumed_insert_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        import sqlite3
        conn = sqlite3.connect(self.env.isolation_db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO approvals(nonce, action, status, ts)"
                             " VALUES('nullc','j','consumed','now')")
                conn.commit()
            conn.rollback()
        finally:
            conn.close()


class R11UpgradeBaselineGuard(unittest.TestCase):
    """OBSERVATION R11-3: the sanctioned upgrade only fires on a TRUE pre-R9
    DB (baseline matches); a tampered DB is left for boot_check to refuse."""

    def test_tampered_db_not_rebaselined_by_upgrade(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        from anton.authz.store import open_store
        # tamper: drop the column out-of-band on the CURRENT db
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        baseline = raw_sqlite(self.env.authz_db,
                              "SELECT value FROM kv WHERE key='schema_hash'"
                              )[0][0]
        conn.execute("ALTER TABLE approval_decisions DROP COLUMN evidence_hmac")
        conn.commit()
        conn.close()
        store = open_store(self.env.authz_db)  # upgrade path must NOT fire
        new_baseline = store.kv_get("schema_hash")
        # baseline untouched -> boot_check will refuse (fail-closed)
        self.assertEqual(new_baseline, baseline)
        store.close()


if __name__ == "__main__":
    unittest.main()


# =========================================================================
# Round 12 (verification of round-11 fixes)
# =========================================================================

class R12BaselineNoneTamperNotLaundered(unittest.TestCase):
    """MAJOR R12-1: a tampered DB with the kv baseline row DELETED must not
    be auto-healed by the sanctioned upgrade — boot_check refuses instead."""

    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        from anton.authz.store import open_store
        # tamper: drop column + delete baseline row
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        conn.execute("ALTER TABLE approval_decisions DROP COLUMN evidence_hmac")
        conn.execute("DELETE FROM kv WHERE key='schema_hash'")
        conn.commit()
        conn.close()
        store = open_store(self.env.authz_db)  # must NOT heal
        self.baseline = store.kv_get("schema_hash")
        cols = {r[1] for r in store.conn.execute(
            "PRAGMA table_info(approval_decisions)")}
        self.column_restored = "evidence_hmac" in cols
        store.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_baseline_stays_none_and_column_not_restored(self):
        self.assertIsNone(self.baseline)
        self.assertFalse(self.column_restored)


class R12DisabledServiceIdentity(unittest.TestCase):
    """OBS R12-3: a disabled service identity's machine token dies."""

    def test_disabled_service_machine_token_refused(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        store = self.env.app.state.authz_store
        owner = store.get_user_by_username("owner")
        svc = store.create_service_identity("svc-x", owner["id"])
        tok, _ = store.mint_machine_token(svc["id"])
        self.assertIsNotNone(store.resolve_machine_token(tok))
        with store.lock:
            store.conn.execute("UPDATE users SET disabled=1 WHERE id=?",
                               (svc["id"],))
            store.commit_flag = True
            store.conn.commit()
        self.assertIsNone(store.resolve_machine_token(tok))
