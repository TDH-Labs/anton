"""Embedded pi-mono executor (default).

The pi CLI is invoked headless (`pi -ne -ns --tools <tools> --model <model> -p <task>`);
tokens are not reliably exposed in pi's output, so metering for cloud routes is captured
by the provider-route metering wrapper (future) — RunResult.tokens_* stay None here.

`tools` gates what pi's invocation is allowed to *do*, independent of the governor's
EV/risk scoring, which only gates *whether* a task is dispatched at all (governor.py) —
nothing upstream of this class restricts tool access. pi's own default (no --tools flag)
enables bash/edit/write unrestricted, so DEFAULT_TOOLS below is deliberately read-only
("read,grep,find,ls" — pi --help's own documented "Read-only mode" example). Callers that
need write/bash access pass a wider `tools` explicitly, an informed per-deployment choice,
not this class's default.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Optional

from .base import Executor, RunResult

DEFAULT_TOOLS = "read,grep,find,ls"


class PiExecutor(Executor):
    def __init__(self, pi_bin: str = "pi", tools: str = DEFAULT_TOOLS):
        self.pi_bin = pi_bin
        self.tools = tools

    def available(self) -> bool:
        return shutil.which(self.pi_bin) is not None

    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        if not self.available():
            return RunResult(1, "", f"pi binary not found: {self.pi_bin}", 0, model, provider,
                             error="ENOENT")
        started = time.monotonic()
        try:
            proc = subprocess.run(
                [self.pi_bin, "-ne", "-ns", "--tools", self.tools, "--model", model, "-p", task],
                capture_output=True, text=True, cwd=cwd, timeout=timeout_s,
            )
            return RunResult(
                exit_code=proc.returncode,
                output=proc.stdout,
                stderr=proc.stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
                model=model,
                provider=provider,
            )
        except subprocess.TimeoutExpired:
            return RunResult(124, "", f"timed out after {timeout_s}s", 0, model, provider,
                             error="timeout")
