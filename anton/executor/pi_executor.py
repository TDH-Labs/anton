"""Embedded pi-mono executor (default, Q1).

Integration-tested on the disposable VM, never on the reference machine. The pi CLI is
invoked headless (`pi -ne -ns --model <model> -p <task>`); tokens are not reliably
exposed in pi's output, so metering for cloud routes is captured by the provider-route
metering wrapper (future) — RunResult.tokens_* stay None here.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from typing import Optional

from .base import Executor, RunResult


class PiExecutor(Executor):
    def __init__(self, pi_bin: str = "pi"):
        self.pi_bin = pi_bin

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
                [self.pi_bin, "-ne", "-ns", "--model", model, "-p", task],
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
