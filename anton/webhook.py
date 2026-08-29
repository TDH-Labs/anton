"""Webhook receiver (stdlib). POST /hooks/<job_id> dispatches a job via the engine."""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .scheduler import JobEngine


def make_handler(engine: JobEngine):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed_path = urllib.parse.urlparse(self.path).path
            if parsed_path == "/health":
                self._send(200, {"ok": True, "jobs": len(engine.jobs),
                                 "ledger_rows": len(engine.ledger.read())})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            # R16-B: authenticate BEFORE any routing so unauthenticated
            # callers cannot use 404-vs-403 as a job-id existence oracle.
            expected_secret = getattr(engine, "webhook_secret", None)
            provided = self.headers.get("X-Anton-Secret", "")
            import hmac as _hmac
            if not expected_secret or not provided or not _hmac.compare_digest(
                    provided, expected_secret):
                self._send(403, {"error": "missing or invalid X-Anton-Secret"})
                return
            parsed_path = urllib.parse.urlparse(self.path).path
            if not parsed_path.startswith("/hooks/"):
                self._send(404, {"error": "not found"})
                return
            job_id = parsed_path[len("/hooks/"):]
            if not job_id:
                self._send(404, {"error": "not found"})
                return
            job = engine.by_id(job_id)
            if job is None or job.trigger.get("type") != "webhook":
                self._send(404, {"error": f"no webhook job {job_id!r}"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (ValueError, TypeError):
                length = 0
            length = max(0, min(length, 1048576))
            body = self.rfile.read(length).decode("utf-8", "replace") if length else ""

            # Inbox loop: messages posted to an inbox-* webhook job are
            # classified and applied (ungated kinds complete here; send
            # parks behind the outbound gate), just like /api/inbox/messages.
            # The engine's data_dir is the one anchor every consumer already
            # carries, so inbox.apply writes to the same vault/workqueue the
            # dashboard reads.
            if job_id.startswith("inbox-"):
                from . import inbox
                try:
                    payload = json.loads(body) if body else {}
                except ValueError:
                    payload = {}
                if isinstance(payload, list):
                    outcomes = []
                    for item in payload[:50]:
                        if not isinstance(item, dict):
                            continue
                        msg = inbox.InboxMessage.from_body(item)
                        try:
                            outcome = inbox.apply(msg, engine.data_dir)
                        except Exception as e:  # one bad message must not drop the batch
                            outcome = f"error: {type(e).__name__}: {e}"
                        outcomes.append({"message": msg.message_id, "kind": msg.kind,
                                         "gate": msg.gate, "outcome": outcome,
                                         "notes": msg.notes})
                    self._send(200, {"status": "ok", "count": len(outcomes),
                                     "items": outcomes})
                    return
                if isinstance(payload, dict):
                    msg = inbox.InboxMessage.from_body(payload)
                    outcome = inbox.apply(msg, engine.data_dir)
                    self._send(200, {"status": "ok", "message": msg.message_id,
                                     "kind": msg.kind, "gate": msg.gate,
                                     "outcome": outcome, "notes": msg.notes})
                    return
                self._send(400, {"error": "inbox webhook body must be a message object or array"})
                return

            record = engine.run_job(job)
            self._send(200, {"job_id": job.id, "exit": record.exit,
                             "ts": record.ts, "flags": record.flags})
        def log_message(self, *a):  # quiet
            pass
        def _send(self, code: int, payload: dict):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


class WebhookServer:
    def __init__(self, engine: JobEngine, host: str, port: int):
        self.httpd = ThreadingHTTPServer((host, port), make_handler(engine))
        self.port = self.httpd.server_address[1]

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
