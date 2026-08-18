"""Localhost OAuth callback server (onboarding wizard, §10). Never exposes tokens."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

INSTRUCTIONS = """<html><body><h2>harbor-sas — OAuth callback</h2>
<p>Waiting for the provider to redirect back…</p></body></html>"""


class CallbackServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, timeout_s: int = 120):
        self.result: dict = {}
        self.timeout_s = timeout_s

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/callback":
                    qs = parse_qs(parsed.query)
                    self.server.result.update({"code": qs.get("code", [""])[0],
                                               "state": qs.get("state", [""])[0]})
                    self._send(200, "OAuth callback received — you can close this tab.")
                else:
                    self._send(200, INSTRUCTIONS, html=True)
            def log_message(self, *a):  # quiet
                pass
            def _send(self, code: int, body: str, html: bool = False):
                data = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/html" if html else "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.result: dict = {}   # shared state: handler writes, wait() reads
        self.port = self.httpd.server_address[1]

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def wait(self) -> dict:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            if self.httpd.result:
                return self.httpd.result
            time.sleep(0.1)
        raise TimeoutError(f"no OAuth callback within {self.timeout_s}s")

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
