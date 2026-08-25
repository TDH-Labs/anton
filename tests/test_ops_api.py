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
            "name": "Nightly sync", "plain": "Syncs sales totals",
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

    def test_agent_worklog_threads_honest_status(self):
        # Ledger rows must carry a status the UI can style truthfully: a
        # skipped run (provider prerequisite unmet) is not a success.
        from datetime import datetime, timezone

        from anton.models import RunRecord
        from anton.scheduler import SKIP_FLAG
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.engine.ledger.append(RunRecord.new(task="ok-job", exit_code=0,
                                                flags="cron;route:local",
                                                ts=f"{today}T10:00:00Z"))
        self.engine.ledger.append(RunRecord.new(task="fail-job", exit_code=1,
                                                flags="cron;route:local",
                                                ts=f"{today}T10:05:00Z"))
        self.engine.ledger.append(RunRecord.new(task="skip-job", exit_code=6,
                                                flags=SKIP_FLAG,
                                                output="skip-job skipped: nothing listening",
                                                ts=f"{today}T10:10:00Z"))
        done = {d["text"].split(" ")[0]: d
                for d in self.client.get("/api/agent/worklog").json()["done"]}
        self.assertEqual(done["ok-job"]["status"], "ok")
        self.assertEqual(done["fail-job"]["status"], "fail")
        self.assertEqual(done["skip-job"]["status"], "skipped")
        self.assertIn("skipped (no provider)", done["skip-job"]["text"])

    def test_learning_reads_playbooks_table(self):
        conn = self._isolation()
        try:
            conn.execute(
                "INSERT INTO playbooks(slug, method, source_initiative, ts, title, body, kind, "
                "triggered_by, usage_count) VALUES(?,?,?,?,?,?,?,?,?)",
                ("sync-lock", "delay to 3am", "remediate-sync", "2026-01-01T00:00:00Z",
                 "Nightly sync file-lock pattern", "Delay to 3 AM resolves the conflict.",
                 "decision", "Incident #19", 3))
            conn.commit()
        finally:
            conn.close()
        entries = self.client.get("/api/learning").json()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Nightly sync file-lock pattern")
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
            json={"name": "Accounting Sync", "command": "n/a", "room": "finance",
                  "what": "Sales totals", "permissions": ["read sales", "write sales totals"]})
        self.assertEqual(added.status_code, 200)

        second = self.client.get("/api/wizard/mcp").json()
        self.assertEqual(len(second), 3)
        acct = next(a for a in second if a["name"] == "Accounting Sync")
        self.assertEqual(acct["permissions"], ["read sales", "write sales totals"])

    def test_setup_wizard_records_picks(self):
        r = self.client.post("/api/setup", json={"step": "work", "picks": ["a", "b", "c"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["picks"], 3)

    def test_work_catalog_is_backend_served_and_beyond_accounting(self):
        # diagnose:setup-automations symptom 1: step-1 suggestions come from
        # the backend (single source of truth, like /api/wizard/catalog) and
        # cover far more than accounting.
        r = self.client.get("/api/wizard/work-catalog")
        self.assertEqual(r.status_code, 200)
        cats = r.json()["categories"]
        self.assertGreaterEqual(len(cats), 4)
        ids = {c["id"] for c in cats}
        self.assertTrue({"marketing", "customer-comms", "it-dev", "scheduling"} <= ids)
        for cat in cats:
            self.assertTrue(cat["cards"])
            for card in cat["cards"]:
                for key in ("id", "label", "sub", "prompt", "cadence", "steps"):
                    self.assertIn(key, card)
                for step in card["steps"]:
                    self.assertIn(step["assignee"], ("agent", "human"))

    def test_setup_wizard_materializes_picks_as_awaiting_drafts_never_finished(self):
        # diagnose:setup-automations symptom 2: picks must land as pending
        # drafts (awaiting_approval, needsSignoff, lastRun null) — never as
        # finished/running main-page rows.
        cats = self.client.get("/api/wizard/work-catalog").json()["categories"]
        pick_ids = [cats[0]["cards"][0]["id"], cats[1]["cards"][0]["id"]]
        r = self.client.post("/api/setup", json={"step": "review", "picks": pick_ids})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["drafted"], 2)

        got = self.client.get("/api/initiatives").json()
        by_id = {row["id"]: row for row in got}
        for pid in pick_ids:
            self.assertIn(pid, by_id)
            row = by_id[pid]
            self.assertEqual(row["state"], "awaiting_approval")
            self.assertNotEqual(row["state"], "running")
            self.assertTrue(row["needsSignoff"])
            self.assertIsNone(row["lastRun"])
            self.assertEqual(row["author"], "agent")
            self.assertTrue(row["nodes"])  # a reviewable diagram, not an empty row

        # Re-running setup never duplicates rows; unknown pick ids are ignored.
        again = self.client.post("/api/setup", json={"step": "review", "picks": pick_ids + ["not-a-real-card"]})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["drafted"], 0)
        self.assertEqual(len(self.client.get("/api/initiatives").json()), len(got))

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
