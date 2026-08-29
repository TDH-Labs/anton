"""Ask Anton: durable sessions and the SSE progress stream."""
from __future__ import annotations

import os
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from anton import chat
from anton.config import load_config
from anton.dashboard import create_app
from anton.db import init_db
from anton.executor.base import Executor, RunResult
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine
from anton.vault import provision_vault

JOBS = """
- id: noop
  trigger: { type: webhook }
  recipe: noop
"""


class SlowExecutor(Executor):
    """Blocks long enough that the stream must emit ticks before the result."""

    def __init__(self, seconds: float = 2.5):
        self.seconds = seconds

    def available(self) -> bool:
        return True

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        time.sleep(self.seconds)
        return RunResult(0, f"answered: {task}", "", int(self.seconds * 1000),
                         model, provider)


class FailingExecutor(Executor):
    def available(self) -> bool:
        return True

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        return RunResult(1, "", "the model refused", 5, model, provider)


class RaisingExecutor(Executor):
    def available(self) -> bool:
        return True

    def run(self, task, *, model, provider, cwd=None, timeout_s=None):
        raise RuntimeError("executor blew up")


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data_dir = self.dir.name
        jobs_path = os.path.join(self.data_dir, "jobs.yaml")
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(JOBS)
        init_db(os.path.join(self.data_dir, "isolation.db"))
        provision_vault(os.path.join(self.data_dir, "vault"))
        self.jobs = load_jobs(jobs_path)
        self.ledger = Ledger(os.path.join(self.data_dir, "runs.jsonl"))

    def tearDown(self):
        self.dir.cleanup()

    def client(self, executor=None):
        engine = JobEngine(self.jobs, self.ledger, executor or SlowExecutor(0.01),
                           load_config(), data_dir=self.data_dir)
        return TestClient(create_app(engine, self.data_dir, load_config()))


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = self.dir.name
        init_db(os.path.join(self.d, "isolation.db"))

    def tearDown(self):
        self.dir.cleanup()

    def test_no_sessions_initially(self):
        self.assertEqual(chat.list_sessions(self.d), [])

    def test_create_then_list(self):
        s = chat.create_session(self.d)
        self.assertEqual([x["id"] for x in chat.list_sessions(self.d)], [s["id"]])

    def test_messages_round_trip_in_order(self):
        s = chat.create_session(self.d)
        chat.append_message(self.d, s["id"], "user", "hello")
        chat.append_message(self.d, s["id"], "assistant", "hi back")
        msgs = chat.get_messages(self.d, s["id"])
        self.assertEqual([(m["role"], m["content"]) for m in msgs],
                         [("user", "hello"), ("assistant", "hi back")])

    def test_appending_to_an_unknown_session_creates_it(self):
        # The browser generates the id and streams straight into it.
        chat.append_message(self.d, "brand-new-id", "user", "first words")
        self.assertIn("brand-new-id", [s["id"] for s in chat.list_sessions(self.d)])

    def test_title_is_backfilled_from_the_first_user_turn(self):
        s = chat.create_session(self.d)
        self.assertIsNone(s["title"])
        chat.append_message(self.d, s["id"], "user", "reconcile the invoices please")
        self.assertEqual(chat.list_sessions(self.d)[0]["title"],
                         "reconcile the invoices please")

    def test_a_later_turn_does_not_overwrite_the_title(self):
        s = chat.create_session(self.d)
        chat.append_message(self.d, s["id"], "user", "first")
        chat.append_message(self.d, s["id"], "user", "second")
        self.assertEqual(chat.list_sessions(self.d)[0]["title"], "first")

    def test_long_titles_are_trimmed(self):
        chat.append_message(self.d, "s1", "user", "x" * 500)
        self.assertEqual(len(chat.list_sessions(self.d)[0]["title"]), chat.TITLE_MAX)

    def test_delete_removes_session_and_its_messages(self):
        s = chat.create_session(self.d)
        chat.append_message(self.d, s["id"], "user", "hi")
        self.assertTrue(chat.delete_session(self.d, s["id"]))
        self.assertEqual(chat.list_sessions(self.d), [])
        self.assertEqual(chat.get_messages(self.d, s["id"]), [])

    def test_deleting_an_absent_session_reports_false(self):
        self.assertFalse(chat.delete_session(self.d, "nope"))

    def test_most_recently_active_sorts_first(self):
        a = chat.create_session(self.d)
        b = chat.create_session(self.d)
        chat.append_message(self.d, a["id"], "user", "bump a")
        self.assertEqual(chat.list_sessions(self.d)[0]["id"], a["id"])
        self.assertIn(b["id"], [s["id"] for s in chat.list_sessions(self.d)])


class TestStreamFrames(unittest.TestCase):
    """stream_reply takes an injected dispatch, so the frame sequence is
    testable with no executor and no HTTP."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.d = self.dir.name
        init_db(os.path.join(self.d, "isolation.db"))

    def tearDown(self):
        self.dir.cleanup()

    def frames(self, dispatch, tick=0.05):
        return list(chat.stream_reply(dispatch, self.d, "sess-1", "a question", tick))

    def test_start_then_result(self):
        out = self.frames(lambda: RunResult(0, "the answer", "", 3, "m", "p"))
        self.assertIn("event: start", out[0])
        self.assertIn("event: result", out[-1])
        self.assertIn("the answer", out[-1])

    def test_ticks_are_emitted_while_a_slow_dispatch_runs(self):
        def slow():
            time.sleep(0.4)
            return RunResult(0, "done", "", 400, "m", "p")
        out = self.frames(slow, tick=0.05)
        self.assertTrue(any("event: tick" in f for f in out),
                        "a slow dispatch must report progress, not look hung")
        self.assertIn("event: result", out[-1])

    def test_the_prompt_is_recorded_before_the_answer_arrives(self):
        self.frames(lambda: RunResult(0, "reply", "", 1, "m", "p"))
        msgs = chat.get_messages(self.d, "sess-1")
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])

    def test_a_nonzero_exit_becomes_an_error_frame_and_is_recorded(self):
        out = self.frames(lambda: RunResult(1, "", "model refused", 1, "m", "p"))
        self.assertIn("event: error", out[-1])
        self.assertIn("model refused", out[-1])
        roles = [m["role"] for m in chat.get_messages(self.d, "sess-1")]
        self.assertEqual(roles, ["user", "error"])

    def test_a_raising_dispatch_becomes_an_error_frame_not_a_crash(self):
        def boom():
            raise RuntimeError("kaboom")
        out = self.frames(boom)
        self.assertIn("event: error", out[-1])
        self.assertIn("kaboom", out[-1])

    def test_no_assistant_turn_is_recorded_when_the_dispatch_fails(self):
        self.frames(lambda: RunResult(1, "", "nope", 1, "m", "p"))
        self.assertNotIn("assistant",
                         [m["role"] for m in chat.get_messages(self.d, "sess-1")])


class TestChatApi(_Base):
    def test_sessions_endpoint_starts_empty(self):
        self.assertEqual(self.client().get("/api/chat/sessions").json()["sessions"], [])

    def test_create_and_read_a_session(self):
        c = self.client()
        sid = c.post("/api/chat/sessions").json()["id"]
        body = c.get(f"/api/chat/sessions/{sid}").json()
        self.assertEqual(body["session_id"], sid)
        self.assertEqual(body["messages"], [])

    def test_delete_unknown_session_is_404(self):
        self.assertEqual(self.client().delete("/api/chat/sessions/nope").status_code, 404)

    def test_stream_returns_event_stream_frames(self):
        c = self.client()
        r = c.post("/api/chat/stream", json={"prompt": "hello there", "session_id": "s9"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/event-stream", r.headers["content-type"])
        self.assertIn("event: start", r.text)
        self.assertIn("event: result", r.text)
        self.assertIn("answered: hello there", r.text)

    def test_stream_persists_the_exchange(self):
        c = self.client()
        c.post("/api/chat/stream", json={"prompt": "remember me", "session_id": "s10"})
        msgs = c.get("/api/chat/sessions/s10").json()["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[0]["content"], "remember me")

    def test_stream_is_ledger_accounted_like_the_one_shot_endpoint(self):
        c = self.client()
        c.post("/api/chat/stream", json={"prompt": "hi", "session_id": "s11"})
        rows = self.ledger.read()
        chat_rows = [r for r in rows if r["task"] == "chat"]
        self.assertEqual(len(chat_rows), 1)
        self.assertIn("source:api/chat", chat_rows[0]["flags"])

    def test_a_failing_dispatch_streams_an_error_rather_than_a_500(self):
        c = self.client(FailingExecutor())
        r = c.post("/api/chat/stream", json={"prompt": "x", "session_id": "s12"})
        self.assertEqual(r.status_code, 200, "the stream already started; it must not 500")
        self.assertIn("event: error", r.text)
        self.assertIn("the model refused", r.text)

    def test_a_raising_executor_streams_an_error(self):
        c = self.client(RaisingExecutor())
        r = c.post("/api/chat/stream", json={"prompt": "x", "session_id": "s13"})
        self.assertIn("event: error", r.text)

    def test_streaming_into_a_new_id_creates_the_session(self):
        c = self.client()
        c.post("/api/chat/stream", json={"prompt": "fresh", "session_id": "never-created"})
        ids = [s["id"] for s in c.get("/api/chat/sessions").json()["sessions"]]
        self.assertIn("never-created", ids)

    def test_the_one_shot_endpoint_still_works(self):
        r = self.client().post("/api/chat", json={"prompt": "classic"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("classic", r.json()["reply"])


if __name__ == "__main__":
    unittest.main()
