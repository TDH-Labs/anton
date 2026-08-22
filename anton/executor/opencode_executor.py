"""opencode executor: shells out to the `opencode` CLI (github.com/sst/opencode),
a headless, multi-provider AI agent, as an alternative to the default PiExecutor.

Invoked as `opencode run <task> --model <provider/model> --format json`, matching
`opencode run --help`'s documented headless syntax. `--format json` emits one JSON
event per line (step_start / text / tool / step_finish / ...); this class reads
the stream for the final assembled text plus token/cost accounting off the
step_finish event's `tokens`/`cost` fields -- the same "never trust a single
unstructured stdout blob" posture PiExecutor and OIExecutor already take, just
against a richer event stream than either of those expose.

`model` must already be in opencode's own `provider/model` form (e.g.
"opencode-go/deepseek-v4-flash") -- this class does not remap Anton's routes.py
local/cloud model aliases, since opencode has its own independent provider
registry (`opencode providers`, `opencode models`) that Anton doesn't mirror.
Standard provider keys (ANTHROPIC_API_KEY etc., already loaded into this
process's environment by cli.py's _load_secrets_into_env) reach opencode for
free -- it falls back to the same env vars pi does when no separate opencode
credentials file entry exists, so no extra credential wiring is needed for
those providers specifically.

`playwright_profile_dir`, when set, gives the dispatched agent real browser
tools scoped to one already-authenticated, persisted Chromium profile
(browser_login.py's session_dir) via @playwright/mcp -- an already-logged-in
browser, never the credential that logged it in. Registered through a scoped
XDG_CONFIG_HOME so this doesn't touch any other opencode config on the
machine; XDG_DATA_HOME is left alone (that's where opencode's own auth.json
lives, and none of this needs to change how *opencode itself* authenticates).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional

from .base import Executor, RunResult


class OpenCodeExecutor(Executor):
    def __init__(self, opencode_bin: str = "opencode", playwright_mcp_bin: str = "playwright-mcp",
                playwright_profile_dir: Optional[str] = None):
        self.opencode_bin = opencode_bin
        self.playwright_mcp_bin = playwright_mcp_bin
        self.playwright_profile_dir = playwright_profile_dir
        self._scoped_config_home: Optional[str] = None

    def available(self) -> bool:
        return shutil.which(self.opencode_bin) is not None

    def _mcp_env(self) -> Optional[dict]:
        """Writes the scoped opencode.json once (not per-run -- the profile
        dir doesn't change between calls) and returns the env override to
        merge into subprocess.run's environment. Returns None when no
        browser MCP wiring was requested, so run() can pass the process's
        own environment through unmodified in the common case."""
        if not self.playwright_profile_dir:
            return None
        if self._scoped_config_home is None:
            root = tempfile.mkdtemp(prefix="anton-opencode-mcp-")
            config_dir = os.path.join(root, "opencode")
            os.makedirs(config_dir, exist_ok=True)
            config = {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    "playwright": {
                        "type": "local",
                        # --headless: Anton's real deployment has no display
                        # server to launch a headed browser against, and
                        # headed is @playwright/mcp's own default.
                        "command": [self.playwright_mcp_bin, "--user-data-dir", self.playwright_profile_dir,
                                   "--headless"],
                        "enabled": True,
                    },
                },
            }
            with open(os.path.join(config_dir, "opencode.json"), "w", encoding="utf-8") as f:
                json.dump(config, f)
            self._scoped_config_home = root
        return {**os.environ, "XDG_CONFIG_HOME": self._scoped_config_home}

    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        if not self.available():
            return RunResult(1, "", f"opencode binary not found: {self.opencode_bin}",
                             0, model, provider, error="ENOENT")
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [self.opencode_bin, "run", task, "--model", model, "--format", "json"],
                capture_output=True, text=True, cwd=cwd, timeout=timeout_s, env=self._mcp_env(),
            )
        except subprocess.TimeoutExpired:
            return RunResult(124, "", f"timed out after {timeout_s}s", 0, model, provider,
                             error="timeout")

        text_parts = []
        tokens_in = tokens_out = None
        cost_usd = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            part = ev.get("part", {})
            if ev.get("type") == "text" and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif ev.get("type") == "step_finish":
                tok = part.get("tokens", {})
                tokens_in = tok.get("input", tokens_in)
                tokens_out = tok.get("output", tokens_out)
                cost_usd = part.get("cost", cost_usd)

        return RunResult(
            exit_code=proc.returncode,
            output="\n".join(text_parts) if text_parts else proc.stdout,
            stderr=proc.stderr,
            duration_ms=int((time.monotonic() - started) * 1000),
            model=model,
            provider=provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )
