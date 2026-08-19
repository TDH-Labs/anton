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
