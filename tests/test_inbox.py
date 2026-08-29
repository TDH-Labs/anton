"""Inbox loop: classification, gate split, artifacts, API + webhook surfaces.

The one invariant this suite defends: only kind=send is outbound-gated;
file/extract/summarize/flag/draft complete without approval, and nothing
ever fabricates a send. The best-effort cli branches on runtime conditions
in a way tests cannot force — the harness-side of the loop is covered by
the authz route auditor + API tests below; the module-level tests force
conditions directly with real temp data dirs.
"""
import json
import os
import tempfile
import unittest

from anton import inbox
from anton.config import load_config
from anton.dashboard import create_app
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine


def _msg(**kw) -> inbox.InboxMessage:
    base = {
        "message_id": "m1", "from_addr": "vendor@example.com",
        "subject": "Invoice 1023 due", "body": "Amount due $450, ref INV-1023.",
        "received_at": "2026-08-01T10:00:00Z",
    }
    base.update(kw)
    return inbox.InboxMessage(**base)


class TestClassification(unittest.TestCase):
    def test_receipt_files_to_the_vault(self):
        m = _msg(subject="Your receipt from QuickBooks",
                 body="Thanks — your payment receipt is attached.")
        self.assertEqual(inbox.classify(m), "file")

    def test_request_for_reply_is_send(self):
        m = _msg(subject="can you reply",
                 body="Please reply with the updated numbers. Awaiting your response.")
        self.assertEqual(inbox.classify(m), "send")

    def test_urgency_without_reply_intent_is_flag_not_send(self):
        # The safety line: urgent alone must never become kind=send.
        m = _msg(subject="FINAL NOTICE",
                 body="This is urgent — action required by Friday.")
        self.assertEqual(inbox.classify(m), "flag")

    def test_numbers_and_reference_drive_extract(self):
        m = _msg(subject="statement", body="Outstanding balance $2,100. Ref QBO-009.")
        self.assertEqual(inbox.classify(m), "extract")

    def test_proposal_language_drives_draft(self):
        m = _msg(subject="proposal", body="What do you think — draft a quote?")
        self.assertEqual(inbox.classify(m), "draft")

    def test_plain_digest_is_summarize(self):
        m = _msg(subject="weekly news", body="Here's this week's updates.")
        self.assertEqual(inbox.classify(m), "summarize")


class TestApplyArtifacts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    @property
    def data_dir(self):
        return self.dir.name

    def test_file_writes_a_vault_note(self):
        m = _msg(subject="Your receipt", body="Thanks — your payment receipt is attached.")
        outcome = inbox.apply(m, self.data_dir)
        self.assertEqual(outcome, "filed to the vault")
        note = os.path.join(self.data_dir, "vault", "your-receipt.md")
        self.assertTrue(os.path.exists(note))

    def test_extract_writes_a_structured_row_not_a_note(self):
        m = _msg(subject="statement", body="Balance $2,100")
        inbox.apply(m, self.data_dir)
        rows = inbox.read_work("extractions", self.data_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["subject"], "statement")

    def test_flag_writes_a_work_card(self):
        m = _msg(subject="URGENT", body="final notice action required")
        inbox.apply(m, self.data_dir)
        rows = inbox.read_work("flags", self.data_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "flag")
        self.assertIsNone(rows[0]["gate"])

    def test_draft_writes_but_never_sends(self):
        m = _msg(subject="proposal", body="draft a quote")
        calls = []
        inbox.apply(m, self.data_dir, outbound_gate=lambda msg: calls.append(msg))
        drafts = os.path.join(self.data_dir, "drafts")
        self.assertEqual(len(os.listdir(drafts)), 1)
        # a draft is never a send: the outbound gate must not have fired
        self.assertEqual(calls, [])
        # and no "sent" artifact exists anywhere under the data dir
        sent = [p for p in os.listdir(self.data_dir) if p == "sent"]
        self.assertEqual(sent, [])

    def test_send_is_gated_and_parks(self):
        m = _msg(subject="can you reply", body="Please reply with the numbers.")
        calls = []
        inbox.apply(m, self.data_dir, outbound_gate=lambda msg: calls.append(msg))
        self.assertEqual(m.gate, "outbound")
        # the gate callable fired exactly once — the parking decision exists
        self.assertEqual(len(calls), 1)
        # and a held draft still exists
        drafts = os.path.join(self.data_dir, "drafts")
        self.assertEqual(len(os.listdir(drafts)), 1)

    def test_ungated_kinds_never_invoke_the_outbound_gate(self):
        for subject, body in (("Your receipt", "receipt attached"),
                              ("statement", "Balance $2,100"),
                              ("URGENT", "final notice action required")):
            m = _msg(subject=subject, body=body)
            calls = []
            inbox.apply(m, self.data_dir, outbound_gate=lambda msg: calls.append(msg))
            self.assertEqual(calls, [], f"{subject} must not hit the outbound gate")


class TestDashboardApi(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        data_dir = os.path.join(self.dir.name, "data")
        os.makedirs(data_dir, exist_ok=True)
        init_db(os.path.join(data_dir, "isolation.db"))
        ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        cfg = load_config()
        cfg["general"] = dict(cfg.get("general") or {})
        cfg["general"]["dashboard_token"] = "s3cret-legacy"
        cfg["authz"] = {"enabled": False}
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write("- id: x\n  trigger: { type: webhook }\n  recipe: x\n")
        engine = JobEngine(load_jobs(jobs_path), ledger, FakeExecutor(), cfg)
        app = create_app(engine, data_dir, cfg)
        from fastapi.testclient import TestClient
        self.client = TestClient(app)
        self.data_dir = data_dir

    def tearDown(self):
        self.dir.cleanup()

    def _h(self):
        return {"Authorization": "Bearer s3cret-legacy"}

    def test_ingest_files_a_message_and_reports_what_happened(self):
        r = self.client.post("/api/inbox/messages",
                             json={"subject": "Your receipt", "body": "receipt attached"},
                             headers=self._h())
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["kind"], "file")
        self.assertEqual(body["gate"], None)
        self.assertEqual(body["outcome"], "filed to the vault")

    def test_ingest_send_kind_is_gated_not_sent(self):
        r = self.client.post("/api/inbox/messages",
                             json={"subject": "can you reply",
                                   "body": "Please reply with the numbers."},
                             headers=self._h())
        body = r.json()
        self.assertEqual(body["kind"], "send")
        self.assertEqual(body["gate"], "outbound")
        # outcome says parked — never "sent"
        self.assertIn("parked", body["outcome"])

    def test_unauth_ingest_refused(self):
        r = self.client.post("/api/inbox/messages",
                             json={"subject": "s", "body": "b"})
        self.assertEqual(r.status_code, 401)

    def test_queue_streams_read_back_what_apply_wrote(self):
        self.client.post("/api/inbox/messages",
                         json={"subject": "statement", "body": "Balance $2,100"},
                         headers=self._h())
        r = self.client.get("/api/inbox/queue?stream=extractions", headers=self._h())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["items"]), 1)
        bad = self.client.get("/api/inbox/queue?stream=nope", headers=self._h())
        self.assertEqual(bad.status_code, 400)


class TestWebhookInboxPath(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        jobs_path = os.path.join(self.dir.name, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write("- id: inbox-triage\n  trigger: { type: webhook }\n  recipe: inbox\n")
        self.ledger = Ledger(os.path.join(self.dir.name, "runs.jsonl"))
        cfg = load_config()
        cfg.setdefault("general", {})["webhook_secret"] = "whsec-test"
        self.engine = JobEngine(load_jobs(jobs_path), self.ledger, FakeExecutor(), cfg)
        from anton.webhook import WebhookServer
        self.headers = {"X-Anton-Secret": "whsec-test"}
        self.srv = WebhookServer(self.engine, "127.0.0.1", 0)
        self.srv.start()

    def tearDown(self):
        self.srv.stop()
        self.dir.cleanup()

    def _post(self, path, body):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=5)
        conn.request("POST", path, body=json.dumps(body), headers=self.headers)
        resp = conn.getresponse()
        data = resp.read().decode()
        conn.close()
        return resp.status, json.loads(data) if data else {}

    def test_batch_of_messages_processes_individually(self):
        status, body = self._post("/hooks/inbox-triage", [
            {"subject": "Your receipt", "body": "receipt attached"},
            {"subject": "can you reply", "body": "Please reply with numbers."},
            {"subject": "URGENT", "body": "final notice action required"},
        ])
        self.assertEqual(status, 200, body)
        self.assertEqual(body["count"], 3)
        kinds = {item["kind"] for item in body["items"]}
        self.assertIn("file", kinds)
        self.assertIn("send", kinds)
        self.assertIn("flag", kinds)
        gated = [i for i in body["items"] if i["gate"]]
        self.assertEqual(len(gated), 1)
        self.assertEqual(gated[0]["gate"], "outbound")

    def test_single_message_through_webhook(self):
        status, body = self._post("/hooks/inbox-triage",
                                  {"subject": "statement", "body": "Balance $2,100"})
        self.assertEqual(status, 200)
        self.assertEqual(body["kind"], "extract")


if __name__ == "__main__":
    unittest.main()