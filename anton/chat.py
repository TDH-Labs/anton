"""Ask Anton: durable chat sessions over the same executor jobs dispatch to.

WHAT THIS STREAMS, PRECISELY. The `Executor` contract is `run() -> RunResult`
-- one blocking call that returns everything at once (PiExecutor shells out
with `subprocess.run`). No executor can emit tokens incrementally, so this
module streams PROGRESS, not tokens: a `start` event the moment the prompt is
accepted, `tick` events carrying elapsed seconds while the dispatch runs, and
one `result` event with the whole reply. That is the difference between a
30-second POST that looks like a hang and one that visibly works. Token-level
streaming would require changing the Executor contract for every executor,
which is a larger change than this surface justifies.

Sessions are durable because a chat that forgets on refresh is a worse
version of the one-shot endpoint it replaces. History lives in isolation.db
next to the rest of the Ops Center's state, so the dashboard process owns it
the same way it owns approvals.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from typing import Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages(session_id, id);
"""

# A title is the first prompt, trimmed -- enough to tell two conversations
# apart in a list without asking a model to name them.
TITLE_MAX = 60


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect(data_dir: str) -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.join(data_dir, "isolation.db"), timeout=10.0)
    conn.executescript(SCHEMA)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the chat tables on an already-open connection (ops_schema hook)."""
    conn.executescript(SCHEMA)


def create_session(data_dir: str, title: Optional[str] = None) -> dict:
    """Start a conversation. The id is a uuid4 hex, not a row counter: it
    appears in URLs the browser keeps."""
    sid = uuid.uuid4().hex
    now = _now()
    conn = _connect(data_dir)
    try:
        conn.execute(
            "INSERT INTO chat_sessions(id, title, created_at, updated_at) VALUES(?,?,?,?)",
            (sid, (title or "")[:TITLE_MAX] or None, now, now))
        conn.commit()
    finally:
        conn.close()
    return {"id": sid, "title": title, "created_at": now, "updated_at": now}


def list_sessions(data_dir: str, limit: int = 50) -> list[dict]:
    """Most recently active first."""
    conn = _connect(data_dir)
    try:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions "
            "ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
            for r in rows]


def get_messages(data_dir: str, session_id: str) -> list[dict]:
    conn = _connect(data_dir)
    try:
        rows = conn.execute(
            "SELECT role, content, ts FROM chat_messages WHERE session_id=? ORDER BY id",
            (session_id,)).fetchall()
    finally:
        conn.close()
    return [{"role": r[0], "content": r[1], "ts": r[2]} for r in rows]


def append_message(data_dir: str, session_id: str, role: str, content: str) -> None:
    """Record one turn and mark its session active.

    The session row is created on demand so a client can stream into a fresh
    id without a separate round trip."""
    now = _now()
    conn = _connect(data_dir)
    try:
        conn.execute(
            "INSERT INTO chat_sessions(id, title, created_at, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (session_id, content[:TITLE_MAX] if role == "user" else None, now, now))
        conn.execute(
            "INSERT INTO chat_messages(session_id, role, content, ts) VALUES(?,?,?,?)",
            (session_id, role, content, now))
        # Backfill a title from the first user turn of a session created
        # without one (the on-demand insert above, or an explicit create).
        if role == "user":
            conn.execute(
                "UPDATE chat_sessions SET title=? WHERE id=? AND (title IS NULL OR title='')",
                (content[:TITLE_MAX], session_id))
        conn.execute("UPDATE chat_sessions SET updated_at=? WHERE id=?", (now, session_id))
        conn.commit()
    finally:
        conn.close()


def delete_session(data_dir: str, session_id: str) -> bool:
    conn = _connect(data_dir)
    try:
        cur = conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        conn.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def sse(event: str, data: dict) -> str:
    """One server-sent event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def stream_reply(dispatch, data_dir: str, session_id: str, prompt: str,
                 tick_seconds: float = 1.0) -> Iterator[str]:
    """Yield SSE frames for one prompt: start, ticks while it runs, result.

    `dispatch` is a zero-argument callable returning a RunResult -- injected
    so the whole event sequence is testable without an executor, and so this
    module never has to know how a job is routed.

    The dispatch runs on a worker thread because it blocks; the generator
    stays free to emit ticks, which is the only reason a caller can tell the
    difference between working and hung.
    """
    import threading

    box: dict = {}

    def work():
        try:
            box["result"] = dispatch()
        except Exception as e:  # surfaced as an error frame, never a 500 mid-stream
            box["error"] = f"{type(e).__name__}: {e}"

    append_message(data_dir, session_id, "user", prompt)
    yield sse("start", {"session_id": session_id})

    thread = threading.Thread(target=work, daemon=True)
    started = dt.datetime.now(dt.timezone.utc)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=tick_seconds)
        elapsed = int((dt.datetime.now(dt.timezone.utc) - started).total_seconds())
        if thread.is_alive():
            yield sse("tick", {"elapsed_seconds": elapsed})

    if "error" in box:
        yield sse("error", {"message": box["error"]})
        return

    result = box.get("result")
    if result is None:
        yield sse("error", {"message": "dispatch returned nothing"})
        return
    if result.exit_code != 0:
        message = result.stderr or result.output or "chat dispatch failed"
        append_message(data_dir, session_id, "error", message)
        yield sse("error", {"message": message})
        return

    append_message(data_dir, session_id, "assistant", result.output)
    yield sse("result", {
        "reply": result.output,
        "model": result.model,
        "provider": result.provider,
        "duration_ms": result.duration_ms,
    })
