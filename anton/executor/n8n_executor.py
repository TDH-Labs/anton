"""n8n executor: dispatches a task to one specific n8n workflow via its
webhook trigger, instead of running it through a local LLM-driven coding
agent. The workflow does the actual work -- deterministic steps, native
connectors, its own AI Agent node where it needs judgment -- and returns a
result through its own Respond to Webhook node; this class only shells out
over HTTP, the same way OpenCodeExecutor shells out to a subprocess.

Anton's governor gates a dispatch BEFORE it reaches here (scheduler.py's
_provider_block / job.gate), same as every other executor -- this class
trusts that the call already cleared approval and just executes.

One instance per workflow (job.executor: {name: n8n, webhook_url: ...} in
jobs.yaml), matching OpenCodeExecutor's one-instance-per-mcp_profile shape
-- a job that needs a different n8n workflow gets a different N8NExecutor,
cached by (name, webhook_url) the same way scheduler.py already caches
per-(name, mcp_profile) OpenCodeExecutor instances.

The response contract a workflow's Respond to Webhook node must return is
intentionally minimal, so a workflow doesn't need Anton-specific knowledge
to be dispatchable: {"output": str, "exit_code": int (default 0),
"error": str (optional)}. Anything else in the body is ignored.
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Optional

from .base import Executor, RunResult


def _http_post_json(url: str, body: dict, headers: dict, timeout_s: Optional[float]):
    import httpx
    r = httpx.post(url, json=body, headers=headers, timeout=timeout_s)
    return r.status_code, r.text


def _http_get(url: str, timeout_s: float):
    import httpx
    r = httpx.get(url, timeout=timeout_s)
    return r.status_code


class N8NExecutor(Executor):
    def __init__(self, webhook_url: str, api_key: Optional[str] = None,
                health_url: Optional[str] = None,
                post_transport=None, get_transport=None):
        """webhook_url: this job's specific n8n workflow webhook endpoint.
        api_key: sent as a header if the workflow's webhook requires
        n8n's optional header auth.
        health_url: defaults to the webhook's own origin + /healthz --
        override when several workflows share one n8n instance and you'd
        rather not hit each workflow's own endpoint just to check liveness.
        post_transport / get_transport: injectable for tests (matching
        qbo_oauth.py's transport-injection pattern) -- real dispatch uses
        httpx directly, CI never touches the network."""
        self.webhook_url = webhook_url
        self.api_key = api_key
        self.health_url = health_url or self._default_health_url(webhook_url)
        self._post = post_transport or _http_post_json
        self._get = get_transport or _http_get

    @staticmethod
    def _default_health_url(webhook_url: str) -> str:
        parsed = urllib.parse.urlparse(webhook_url)
        return f"{parsed.scheme}://{parsed.netloc}/healthz"

    def available(self) -> bool:
        try:
            status = self._get(self.health_url, 5.0)
        except Exception:
            return False
        return status == 200

    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        started = time.monotonic()
        headers = {"X-N8N-Api-Key": self.api_key} if self.api_key else {}
        try:
            status, text = self._post(
                self.webhook_url, {"task": task, "model": model, "provider": provider},
                headers, timeout_s,
            )
        except Exception as e:
            return RunResult(1, "", str(e), int((time.monotonic() - started) * 1000),
                             model, provider, error=type(e).__name__)
        duration_ms = int((time.monotonic() - started) * 1000)
        if status != 200:
            return RunResult(1, "", f"n8n webhook returned {status}: {text[:500]}",
                             duration_ms, model, provider, error=f"http_{status}")
        import json
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            return RunResult(1, "", f"n8n webhook returned non-JSON: {text[:500]}",
                             duration_ms, model, provider, error="bad_response")
        return RunResult(
            exit_code=int(body.get("exit_code", 0)),
            output=str(body.get("output", "")),
            stderr=str(body.get("error", "")),
            duration_ms=duration_ms,
            model=model,
            provider=provider,
        )
