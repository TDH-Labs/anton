"""CI-T-PRIN-01/02, CI-T-AUDIT-01 — §9 principals, §7 audit chain basics."""
import threading
import unittest

from helpers import build_env, raw_sqlite


class TestPrin01TypedNonHuman(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_admin_user_where_system_principal_required_fails(self):
        from anton.authz.datalayer import run_scheduled_job
        from anton.authz.principals import PrincipalTypeError
        admin = self.store.principal_of("owner")
        with self.assertRaises(PrincipalTypeError):
            run_scheduled_job(self.store, self.audit, admin)

    def test_migration_runner_requires_migration_principal(self):
        from anton.authz.boot import run_migration
        from anton.authz.principals import MigrationPrincipal, PrincipalTypeError
        admin = self.store.principal_of("owner")
        with self.assertRaises(PrincipalTypeError):
            run_migration(self.store, self.audit, principal=admin,
                          name="m1", sql="SELECT 1")
        run_migration(self.store, self.audit,
                      principal=MigrationPrincipal(migration_name="m1"),
                      name="m1", sql="SELECT 1")
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT seq FROM audit_chain WHERE event_type='migration'")
        self.assertTrue(rows)


class TestPrin02MigrationConstraints(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def test_hostile_migration_dropping_approval_trigger_fails_assertion(self):
        from anton.authz.boot import (MigrationIntegrityError, run_migration)
        from anton.authz.principals import MigrationPrincipal
        with self.assertRaises(MigrationIntegrityError):
            run_migration(
                self.store, self.audit,
                principal=MigrationPrincipal(migration_name="hostile-1"),
                name="hostile-1",
                sql="DROP TRIGGER trg_grant_no_self")


class TestAudit01ChainIntegrity(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _append(self, n, tag="t"):
        for i in range(n):
            self.audit.append("test_event", payload={"i": i, "tag": tag})

    def test_tamper_detection(self):
        from anton.authz.audit import ChainTampered
        self._append(10)
        ok, _ = self.audit.verify()
        self.assertTrue(ok)
        # tamper with one row
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        conn.execute("UPDATE audit_chain SET payload_json='{\"evil\":1}' "
                     "WHERE seq=5")
        conn.commit()
        conn.close()
        with self.assertRaises(ChainTampered):
            self.audit.verify()

    def test_tail_deletion_gap_detected(self):
        from anton.authz.audit import ChainGap
        self._append(10)
        import sqlite3
        conn = sqlite3.connect(self.env.authz_db)
        conn.execute("DELETE FROM audit_chain WHERE seq > 7")
        conn.commit()
        conn.close()
        with self.assertRaises(ChainGap):
            self.audit.verify()

    def test_concurrent_writers_single_valid_chain(self):
        errors = []

        def writer(tag):
            try:
                for i in range(25):
                    self.audit.append("load_test", payload={"tag": tag, "i": i})
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(f"w{j}",))
                   for j in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        ok, detail = self.audit.verify()
        self.assertTrue(ok, detail)
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT COUNT(*), COUNT(DISTINCT seq) FROM audit_chain "
                          "WHERE event_type='load_test'")
        self.assertEqual(rows[0][0], 150)
        self.assertEqual(rows[0][1], 150)


if __name__ == "__main__":
    unittest.main()
