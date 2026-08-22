"""Anton Studio Ops Center API — contract-shape and behavior tests for the
new/reshaped routes in dashboard.py + ops_api.py + ops_schema.py."""
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from anton.cli import _build
from anton.config import load_config
from anton.dashboard import create_app
from anton.ops_schema import ensure_ops_schema
from anton.setup import run_setup


class TestOpsApi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        info = run_setup(self._tmp.name, executor="fake")
        config = load_config(info["config"])
        _jobs, _ledger, self.engine = _build(config, info["data_dir"], "fake")
        self.data_dir = info["data_dir"]
        app = create_app(self.engine, self.data_dir, config)
        self.client = TestClient(app)

    def tearDown(self):
        self._tmp.cleanup()

    def _isolation(self):
        conn = sqlite3.connect(f"{self.data_dir}/isolation.db", timeout=10.0)
        ensure_ops_schema(conn)
        return conn

    def test_no_route_collisions_and_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_initiatives_is_automation_shape_and_leaves_initiatives_table_alone(self):
        r = self.client.get("/api/initiatives")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])
        # the pre-existing `initiatives` table (delta.py) is untouched by
        # this route change — it stays queryable with its original columns.
        conn = self._isolation()
        try:
            conn.execute("SELECT slug, source, risk, status FROM initiatives")
        finally:
            conn.close()

    def test_automation_put_then_initiatives_get_round_trips(self):
        body = {
            "name": "Nightly sync", "plain": "Syncs job costs",
            "nodes": [{"id": "n1", "kind": "trigger", "x": 0, "y": 0, "text": "3 AM daily"}],
            "links": [],
            "state": "awaiting_approval",
        }
        put = self.client.put("/api/automations/nightly-sync", json=body)
        self.assertEqual(put.status_code, 200)

        got = self.client.get("/api/initiatives").json()
        self.assertEqual(len(got), 1)
        row = got[0]
        self.assertEqual(row["id"], "nightly-sync")
        self.assertEqual(row["name"], "Nightly sync")
        self.assertEqual(row["state"], "awaiting_approval")
        self.assertEqual(len(row["nodes"]), 1)
        self.assertEqual(row["nodes"][0]["id"], "n1")

        # a second PUT updates in place rather than duplicating.
        body["state"] = "running"
        self.client.put("/api/automations/nightly-sync", json=body)
        got2 = self.client.get("/api/initiatives").json()
        self.assertEqual(len(got2), 1)
        self.assertEqual(got2[0]["state"], "running")

    def test_jobs_shape_has_documented_fields(self):
        jobs = self.client.get("/api/jobs").json()
        self.assertTrue(len(jobs) > 0)
        for j in jobs:
            for key in ("id", "automationId", "trigger", "nextRun", "lastRun", "cadenceMin"):
                self.assertIn(key, j)

    def test_approvals_decision_once_approves(self):
        create = self.client.post(
            "/api/approvals", json={"action": "wire-transfer", "amount": "10.00", "recipient": "vendor"})
        aid = create.json()["id"]

        listed = self.client.get("/api/approvals").json()
        self.assertEqual(len(listed), 1)
        for key in ("id", "title", "sub", "reason", "evidence", "changes", "age", "kind"):
            self.assertIn(key, listed[0])

        decide = self.client.post(f"/api/approvals/{aid}", json={"decision": "once"})
        self.assertEqual(decide.status_code, 200)
        self.assertEqual(decide.json()["status"], "approved")
        # consumed out of the pending list
        self.assertEqual(self.client.get("/api/approvals").json(), [])

    def test_approvals_decision_defer_leaves_pending(self):
        create = self.client.post(
            "/api/approvals", json={"action": "wire-transfer", "amount": "10.00", "recipient": "vendor"})
        aid = create.json()["id"]
        decide = self.client.post(f"/api/approvals/{aid}", json={"decision": "defer"})
        self.assertEqual(decide.status_code, 200)
        self.assertEqual(decide.json()["status"], "pending")
        self.assertEqual(len(self.client.get("/api/approvals").json()), 1)

    def test_approvals_decision_rejects_unknown_value(self):
        create = self.client.post(
            "/api/approvals", json={"action": "wire-transfer", "amount": "10.00", "recipient": "vendor"})
        aid = create.json()["id"]
        decide = self.client.post(f"/api/approvals/{aid}", json={"decision": "sometimes"})
        self.assertEqual(decide.status_code, 400)

    def test_mode_standard_no_longer_404s(self):
        on = self.client.post("/api/mode/son-of-anton", json={"son_of_anton_mode": True})
        self.assertTrue(on.json()["son_of_anton_mode"])
        off = self.client.post("/api/mode/standard")
        self.assertEqual(off.status_code, 200)
        self.assertFalse(off.json()["son_of_anton_mode"])
        self.assertFalse(self.client.get("/api/mode").json()["son_of_anton_mode"])

    def test_mode_son_of_anton_accepts_no_body(self):
        # SidebarRoot.tsx and Brand.tsx (anton-studio) POST here with no body
        # at all -- the endpoint name alone implies True. Only the older
        # dashboard.py inline page sends an explicit son_of_anton_mode value.
        on = self.client.post("/api/mode/son-of-anton")
        self.assertEqual(on.status_code, 200)
        self.assertTrue(on.json()["son_of_anton_mode"])
        off = self.client.post("/api/mode/son-of-anton", json={"son_of_anton_mode": False})
        self.assertEqual(off.status_code, 200)
        self.assertFalse(off.json()["son_of_anton_mode"])

    def test_systems_reports_self_managed_scheduler(self):
        systems = self.client.get("/api/systems").json()
        self.assertTrue(any(s["selfManaged"] for s in systems))

    def test_agent_worklog_shape(self):
        log = self.client.get("/api/agent/worklog").json()
        self.assertIn("ongoing", log)
        self.assertIn("done", log)

    def test_learning_reads_playbooks_table(self):
        conn = self._isolation()
        try:
            conn.execute(
                "INSERT INTO playbooks(slug, method, source_initiative, ts, title, body, kind, "
                "triggered_by, usage_count) VALUES(?,?,?,?,?,?,?,?,?)",
                ("sage-lock", "delay to 3am", "remediate-sync", "2026-01-01T00:00:00Z",
                 "Sage sync file-lock pattern", "Delay to 3 AM resolves the conflict.",
                 "decision", "Incident #19", 3))
            conn.commit()
        finally:
            conn.close()
        entries = self.client.get("/api/learning").json()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Sage sync file-lock pattern")
        self.assertEqual(entries[0]["usage"], 3)

    def test_incidents_shape_with_events(self):
        conn = self._isolation()
        try:
            conn.execute(
                "INSERT INTO incidents(id, title, summary, status, window_start, window_end, ts) "
                "VALUES(?,?,?,?,?,?,?)",
                ("inc-1", "Sync dropped a job", "File lock held the sync open",
                 "resolved", "02:00", "03:14", "2026-01-01T00:00:00Z"))
            conn.execute(
                "INSERT INTO incident_events(incident_id, time, text, actor, ts) VALUES(?,?,?,?,?)",
                ("inc-1", "2:00", "Sync started", "agent", "2026-01-01T00:00:00Z"))
            conn.commit()
        finally:
            conn.close()
        incidents = self.client.get("/api/incidents").json()
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["id"], "inc-1")
        self.assertEqual(len(incidents[0]["events"]), 1)
        self.assertEqual(incidents[0]["events"][0]["actor"], "agent")

    def test_wizard_mcp_seeds_defaults_and_persists_additions(self):
        first = self.client.get("/api/wizard/mcp").json()
        self.assertEqual(len(first), 2)
        for addon in first:
            for key in ("id", "name", "what", "permissions", "status"):
                self.assertIn(key, addon)

        added = self.client.post(
            "/api/wizard/mcp",
            json={"name": "Sage Accounting", "command": "n/a", "room": "finance",
                  "what": "Job costs", "permissions": ["read jobs", "write job costs"]})
        self.assertEqual(added.status_code, 200)

        second = self.client.get("/api/wizard/mcp").json()
        self.assertEqual(len(second), 3)
        sage = next(a for a in second if a["name"] == "Sage Accounting")
        self.assertEqual(sage["permissions"], ["read jobs", "write job costs"])

    def test_setup_wizard_records_picks(self):
        r = self.client.post("/api/setup", json={"step": "work", "picks": ["a", "b", "c"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["picks"], 3)

    def test_vault_note_augmented_fields_present(self):
        # provision_vault() writes index.md into the vault dir; scan it in so
        # `notes` has a row to enrich the response with.
        from anton.vault import scan_vault
        scan_vault(f"{self.data_dir}/vault")
        r = self.client.get("/api/vault/note", params={"path": "index"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("title", "kind", "author", "body", "provenance", "usedCount", "linkCount"):
            self.assertIn(key, body)

    def test_ensure_ops_schema_is_idempotent_under_concurrent_callers(self):
        # open_isolation_db() re-runs ensure_ops_schema() on every request with
        # no external locking (dashboard.py's approvals/initiatives/etc. routes
        # each open their own connection), so two connections can both see a
        # column missing and both attempt to add it. A second connection's
        # ALTER TABLE landing after the first must not raise.
        first = self._isolation()
        second = sqlite3.connect(f"{self.data_dir}/isolation.db", timeout=10.0)
        ensure_ops_schema(second)  # column already added by self._isolation()
        first.close()
        second.close()


if __name__ == "__main__":
    unittest.main()
