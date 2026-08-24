"""Portal Connections — registration governance, session guardian,
and the sanctioned additive migration of the portals table.

House rules mirrored from test_egress_channels.py: privileged creations
are capability-gated (connections.connect), every lifecycle event is
WORM-audited, the guardian fails closed, and schema changes to authz.db
must carry an upgrade path that never heals an unverified state.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from helpers import build_env, raw_sqlite


class FakeDriver:
    """Stands in for PlaywrightDriver — same narrow shape browser_login's
    BrowserDriver abstraction takes."""

    def __init__(self, alive=True, fail=False):
        self.alive = alive
        self.fail = fail
        self.opened = None
        self.closed = False

    def open_persistent_context(self, profile_dir):
        if self.fail:
            raise RuntimeError("browser exploded")
        self.opened = profile_dir

    def goto(self, url):
        pass

    def fill(self, selector, value):
        return True

    def click(self, selector):
        return True

    def is_present(self, selector):
        return self.alive

    def close(self):
        self.closed = True


class PortalTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.owner_p = self.store.principal_of("owner")
        self.op = self.store.create_user("op1", "Role-Pass-1!")
        self.store.assign_role(self.op["id"], "Operator",
                               actor_id=self.owner_p.user_id)
        self.viewer = self.store.create_user("view1", "Role-Pass-1!")
        self.store.assign_role(self.viewer["id"], "Viewer",
                               actor_id=self.owner_p.user_id)
        self.install_dir = tempfile.mkdtemp(prefix="portal-install-")

    def tearDown(self):
        shutil.rmtree(self.env.dir, ignore_errors=True)
        shutil.rmtree(self.install_dir, ignore_errors=True)

    def _audit_count(self, event_type):
        return len(raw_sqlite(self.env.authz_db,
                              "SELECT seq FROM audit_chain WHERE event_type=?",
                              (event_type,)))


class TestRegistrationGovernance(PortalTestBase):
    def test_operator_cannot_register_portal(self):
        from anton.authz.portal import register_portal
        op_p = self.store.principal_of("op1")
        with self.assertRaises(PermissionError):
            register_portal(self.store, self.audit, actor=op_p,
                            name="procare", base_url="https://procare.example.com")
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT payload_json FROM audit_chain "
                          "WHERE event_type='authorization_denied'")
        self.assertTrue(any("connections.connect" in (r[0] or "") for r in rows))
        self.assertEqual(len(raw_sqlite(
            self.env.authz_db, "SELECT name FROM portals")), 0)

    def test_owner_registers_portal_and_it_is_audited(self):
        from anton.authz.portal import get_portal, register_portal
        row = register_portal(self.store, self.audit, actor=self.owner_p,
                              name="procare",
                              base_url="https://procare.example.com",
                              login_url="https://procare.example.com/login",
                              selectors={"success_selector": "#dashboard"},
                              cookie_domains=["procare.example.com"])
        self.assertEqual(row["name"], "procare")
        self.assertEqual(row["registered_by"], self.owner_p.user_id)
        self.assertEqual(row["active"], 1)
        self.assertEqual(json.loads(row["selectors_json"]),
                         {"success_selector": "#dashboard"})
        self.assertEqual(self._audit_count("portal_registered"), 1)
        # round-trips through the store
        again = get_portal(self.store, "procare")
        self.assertEqual(again["base_url"], "https://procare.example.com")

    def test_registration_validation_is_fail_closed(self):
        from anton.authz.portal import PortalError, register_portal
        bad_inputs = [
            dict(name="Bad Name!", base_url="https://x.example.com"),
            dict(name="ok-name", base_url="ftp://x.example.com"),
            dict(name="ok-name", base_url=""),
            dict(name="ok-name", base_url="https://x.example.com",
                 guardian_interval_s=30),
            dict(name="ok-name", base_url="https://x.example.com",
                 selectors=["not", "a", "mapping"]),
        ]
        for kwargs in bad_inputs:
            with self.assertRaises(PortalError):
                register_portal(self.store, self.audit, actor=self.owner_p,
                                **kwargs)
        # nothing was written by any rejected registration
        self.assertEqual(len(raw_sqlite(
            self.env.authz_db, "SELECT name FROM portals")), 0)

    def test_reregistration_updates_in_place_and_stays_single_row(self):
        from anton.authz.portal import list_portals, register_portal
        register_portal(self.store, self.audit, actor=self.owner_p,
                        name="gusto", base_url="https://gusto.example.com")
        register_portal(self.store, self.audit, actor=self.owner_p,
                        name="gusto", base_url="https://gusto2.example.com",
                        guardian_interval_s=1800)
        rows = list_portals(self.store)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["base_url"], "https://gusto2.example.com")
        self.assertEqual(rows[0]["guardian_interval_s"], 1800)


class TestDeregistration(PortalTestBase):
    def _register(self, name="watchmegrow"):
        from anton.authz.portal import register_portal
        return register_portal(self.store, self.audit, actor=self.owner_p,
                               name=name, base_url="https://wm.example.com")

    def test_deregister_is_capability_gated_and_audited(self):
        from anton.authz.portal import deregister_portal, get_portal
        self._register()
        op_p = self.store.principal_of("op1")
        with self.assertRaises(PermissionError):
            deregister_portal(self.store, self.audit, actor=op_p,
                              name="watchmegrow")
        deregister_portal(self.store, self.audit, actor=self.owner_p,
                          name="watchmegrow")
        row = get_portal(self.store, "watchmegrow")
        self.assertEqual(row["active"], 0)  # soft-deactivation, not deletion
        self.assertEqual(self._audit_count("portal_deregistered"), 1)

    def test_deregister_unknown_portal_is_keyerror(self):
        from anton.authz.portal import deregister_portal
        with self.assertRaises(KeyError):
            deregister_portal(self.store, self.audit, actor=self.owner_p,
                              name="nope")

    def test_inactive_portals_excluded_from_default_listing(self):
        from anton.authz.portal import (deregister_portal, list_portals,
                                        register_portal)
        register_portal(self.store, self.audit, actor=self.owner_p,
                        name="live-one", base_url="https://a.example.com")
        register_portal(self.store, self.audit, actor=self.owner_p,
                        name="dead-one", base_url="https://b.example.com")
        deregister_portal(self.store, self.audit, actor=self.owner_p,
                          name="dead-one")
        names = [p["name"] for p in list_portals(self.store)]
        self.assertEqual(names, ["live-one"])
        all_names = [p["name"] for p in
                     list_portals(self.store, active_only=False)]
        self.assertEqual(sorted(all_names), ["dead-one", "live-one"])


class TestSessionGuardian(PortalTestBase):
    def _register_with_selector(self, name="procare"):
        from anton.authz.portal import register_portal
        return register_portal(
            self.store, self.audit, actor=self.owner_p, name=name,
            base_url="https://procare.example.com",
            selectors={"success_selector": "#dashboard"})
        # returns the row; caller stores a credential separately if needed

    def test_health_check_fails_closed_without_credential(self):
        from anton.authz.portal import check_session_health
        row = self._register_with_selector()
        result = check_session_health(self.install_dir, row,
                                      driver=FakeDriver())
        self.assertFalse(result["healthy"])
        self.assertTrue(result["needs_reauth"])
        self.assertEqual(result["status"], "stale")

    def test_health_check_healthy_with_live_session(self):
        from anton import browser_vault
        from anton.authz.portal import check_session_health
        row = self._register_with_selector()
        browser_vault.store_credential(self.install_dir, row["name"],
                                       "alice", "hunter2")
        driver = FakeDriver(alive=True)
        result = check_session_health(self.install_dir, row, driver=driver)
        self.assertTrue(result["healthy"])
        self.assertFalse(result["needs_reauth"])
        # it used the persistent-profile session dir keyed by portal name
        self.assertIn(os.path.join("browser-sessions", "procare"),
                      driver.opened.replace("\\", "/"))

    def test_health_check_reports_error_without_demanding_reauth(self):
        from anton import browser_vault
        from anton.authz.portal import check_session_health
        row = self._register_with_selector()
        browser_vault.store_credential(self.install_dir, row["name"],
                                       "alice", "hunter2")
        result = check_session_health(self.install_dir, row,
                                      driver=FakeDriver(fail=True))
        self.assertFalse(result["healthy"])
        self.assertFalse(result["needs_reauth"])  # transient != expired
        self.assertEqual(result["status"], "error")

    def test_guardian_sweep_alerts_and_audits_on_expired_session(self):
        from anton import browser_vault
        from anton.authz.portal import run_guardian_sweep
        row = self._register_with_selector()
        browser_vault.store_credential(self.install_dir, row["name"],
                                       "alice", "hunter2")
        checked = run_guardian_sweep(self.store, self.audit, self.install_dir,
                                     driver_factory=lambda: FakeDriver(alive=False))
        self.assertEqual(len(checked), 1)
        self.assertFalse(checked[0]["healthy"])
        alerts = raw_sqlite(self.env.authz_db,
                            "SELECT kind FROM authz_alerts WHERE "
                            "kind='portal_reauth_needed'")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(self._audit_count("portal_session_stale"), 1)
        stored = raw_sqlite(self.env.authz_db,
                            "SELECT last_health_status FROM portals "
                            "WHERE name='procare'")
        self.assertEqual(stored[0][0], "stale")

    def test_guardian_sweep_respects_interval_and_active_set(self):
        from anton.authz.portal import (check_session_health,
                                        record_health_result,
                                        run_guardian_sweep)
        live = self._register_with_selector("live-one")
        record_health_result(self.store, self.audit, "live-one",
                             check_session_health(self.install_dir, live,
                                                  driver=FakeDriver()))
        # second sweep immediately after: interval not elapsed -> skipped
        checked = run_guardian_sweep(self.store, self.audit, self.install_dir,
                                     driver_factory=FakeDriver)
        self.assertEqual(checked, [])


class TestPortalHTTPSurface(PortalTestBase):
    def test_register_route_requires_connections_connect(self):
        owner_h = self.env.login("owner", "Owner-Pass-1!")
        viewer_h = self.env.login("view1", "Role-Pass-1!")
        body = {"name": "ProCare Portal", "base_url": "https://p.example.com"}
        r = self.env.client.post("/api/authz/portals", json=body,
                                 headers=viewer_h)
        self.assertEqual(r.status_code, 403)
        r = self.env.client.post("/api/authz/portals", json=body,
                                 headers=owner_h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "registered")
        self.assertEqual(r.json()["portal"]["name"], "procare-portal")

    def test_list_and_health_check_routes(self):
        owner_h = self.env.login("owner", "Owner-Pass-1!")
        self.env.client.post("/api/authz/portals", json={
            "name": "Gusto", "base_url": "https://g.example.com",
            "selectors": {"success_selector": "#payroll"}}, headers=owner_h)
        r = self.env.client.get("/api/authz/portals", headers=owner_h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([p["name"] for p in r.json()["portals"]], ["gusto"])

        from anton import browser_vault
        browser_vault.store_credential(self.install_dir, "gusto",
                                       "alice", "hunter2")
        r = self.env.client.post("/api/authz/portals/gusto/health-check",
                                 headers=owner_h)
        # no persistent session exists in this env's install dir -> fail
        # closed with a re-auth verdict, not a crash and not fake health
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["healthy"])

    def test_deregister_route(self):
        owner_h = self.env.login("owner", "Owner-Pass-1!")
        self.env.client.post("/api/authz/portals", json={
            "name": "wm", "base_url": "https://w.example.com"}, headers=owner_h)
        r = self.env.client.post("/api/authz/portals/wm/deregister",
                                 headers=owner_h)
        self.assertEqual(r.status_code, 200)
        r = self.env.client.get("/api/authz/portals", headers=owner_h)
        self.assertEqual(r.json()["portals"], [])
        r = self.env.client.post("/api/authz/portals/ghost/deregister",
                                 headers=owner_h)
        self.assertEqual(r.status_code, 404)

    def test_new_routes_keep_the_route_auditor_clean(self):
        from anton.authz.guards import audit_routes_behavioral
        findings = [f for f in audit_routes_behavioral(self.env.app)
                    if "default-deny fallback" in f]
        self.assertEqual(findings, [])


class TestGuardianWiring(PortalTestBase):
    def test_opt_out_flag_disables_the_thread(self):
        from anton.authz import _start_portal_guardian
        cfg = {"authz": {"portal_guardian": False}}
        self.assertIsNone(_start_portal_guardian(
            self.store, self.audit, self.env.data_dir, cfg))

    def test_guardian_thread_sweeps_and_stops_cleanly(self):
        import time
        from unittest.mock import patch
        from anton.authz import _start_portal_guardian
        calls = []

        def fake_sweep(store, audit, install_dir):
            calls.append(install_dir)
            return []

        stop = None
        with patch("anton.authz.portal.run_guardian_sweep", fake_sweep):
            stop = _start_portal_guardian(
                self.store, self.audit, self.env.data_dir,
                {"authz": {}}, first_tick_s=0.05, tick_s=0.05)
            deadline = time.time() + 2
            while not calls and time.time() < deadline:
                time.sleep(0.02)
        # sweep runs against the install dir (parent of data_dir) and the
        # thread stops cleanly instead of leaking past shutdown
        stop()
        self.assertTrue(calls)
        self.assertEqual(os.path.dirname(self.env.data_dir), calls[0])

    def test_guardian_tick_error_is_audited_not_fatal(self):
        import time
        from unittest.mock import patch
        from anton.authz import _start_portal_guardian

        def boom(*a, **k):
            raise RuntimeError("sweep exploded")

        stop = None
        with patch("anton.authz.portal.run_guardian_sweep", boom):
            stop = _start_portal_guardian(
                self.store, self.audit, self.env.data_dir,
                {"authz": {}}, first_tick_s=0.05, tick_s=0.05)
            deadline = time.time() + 2
            while time.time() < deadline and not raw_sqlite(
                    self.env.authz_db, "SELECT seq FROM audit_chain "
                    "WHERE event_type='guardian_error'"):
                time.sleep(0.02)
        stop()
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT payload_json FROM audit_chain "
                          "WHERE event_type='guardian_error'")
        self.assertTrue(any("RuntimeError" in (r[0] or "") for r in rows))


class TestAdditiveMigration(unittest.TestCase):
    """The portals table must arrive on existing installs without bricking
    them: a genuine pre-portals DB is re-baselined exactly once; anything
    else stays untouched for boot_check to refuse."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="portal-migration-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_genuine_pre_portals_db_is_sanctioned_and_rebaselined(self):
        from anton.authz.audit import AuditLog
        from anton.authz.boot import boot_check
        from anton.authz.schema import schema_signature
        from anton.authz.store import open_store

        db = os.path.join(self.tmp, "old-authz.db")
        s = open_store(db)  # fresh canonical DB of TODAY's code
        # rewind it into the pre-portals shape: drop the table and pin the
        # baseline to that older signature — exactly what an install that
        # predates the feature looks like on disk.
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE portals")
        old_sig = schema_signature(conn)
        conn.execute("INSERT INTO kv(key, value) VALUES('schema_hash', ?)",
                     (old_sig,))
        conn.commit()
        conn.close()

        s2 = open_store(db)
        live = schema_signature(s2.conn)
        self.assertIsNotNone(s2.kv_get("schema_hash"))
        self.assertEqual(s2.kv_get("schema_hash"), live)  # re-baselined
        # the table is back and boot_check accepts the upgraded DB
        has_table = s2.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='portals'"
        ).fetchone()
        self.assertTrue(has_table)
        boot_check(s2, AuditLog(s2), mode="multi_user")  # must not raise

    def test_drifted_db_is_not_healed_by_the_migration(self):
        from anton.authz.schema import schema_signature
        from anton.authz.store import open_store

        db = os.path.join(self.tmp, "tampered.db")
        s = open_store(db)
        # record the genuine baseline the way every established install has
        from anton.authz.audit import AuditLog
        from anton.authz.boot import boot_check
        boot_check(s, AuditLog(s), mode="first_boot")
        # tamper shape: drop the table AND desynchronize the baseline —
        # the preheal gate must refuse and the migration must not touch it.
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE portals")
        wrong_baseline = "f" * 64
        conn.execute("UPDATE kv SET value=? WHERE key='schema_hash'",
                     (wrong_baseline,))
        conn.commit()
        conn.close()

        s2 = open_store(db)
        self.assertTrue(s2.preheal_refusal)  # refused before any heal
        still_gone = s2.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='portals'"
        ).fetchone()
        self.assertIsNone(still_gone)
        self.assertEqual(s2.kv_get("schema_hash"), wrong_baseline)


if __name__ == "__main__":
    unittest.main()
