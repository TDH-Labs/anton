"""Host-side executor over SSH (the n8n->SSH->Mac pattern, containerized).

The container runs the control plane; the executor runs recipes on a host machine
(Mac or otherwise) that has pi/OI + credentials. Config via env:
  HARBOR_SSH_HOST        e.g. 100.105.232.122 or mac-studio.local
  HARBOR_SSH_USER        ssh user
  HARBOR_SSH_KEY         path to an ssh private key (optional)
  HARBOR_SSH_COMMAND     shell command template; <recipe> and <model> are substituted
                         default: "bash -lc 'export PATH=$HOME/.local/bin:$PATH; run-local-recipe.sh <recipe>'"
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Optional

from .base import Executor, RunResult

DEFAULT_COMMAND = "bash -lc 'export PATH=$HOME/.local/bin:$PATH; run-local-recipe.sh <recipe>'"


class SSHExecutor(Executor):
    def __init__(self, *, host: Optional[str] = None, user: Optional[str] = None,
                 key: Optional[str] = None, command: Optional[str] = None,
                 ssh_bin: str = "ssh"):
        self.host = host or os.environ.get("HARBOR_SSH_HOST") or ""
        self.user = user or os.environ.get("HARBOR_SSH_USER") or ""
        self.key = key or os.environ.get("HARBOR_SSH_KEY") or ""
        self.command = command or os.environ.get("HARBOR_SSH_COMMAND") or DEFAULT_COMMAND
        self.ssh_bin = ssh_bin

    def available(self) -> bool:
        return bool(self.host and shutil.which(self.ssh_bin))

    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        if not self.available():
            return RunResult(1, "", f"ssh executor unavailable (host={self.host!r})",
                             0, model, provider, error="unavailable")
        target = f"{self.user}@{self.host}" if self.user else self.host
        cmd = self.command.replace("<recipe>", task).replace("<model>", model)
        args = [self.ssh_bin]
        if self.key:
            args += ["-i", self.key]
        args += ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15",
                 target, cmd]
        started = time.monotonic()
        try:
            proc = subprocess.run(args, capture_output=True, text=True, cwd=cwd,
                                  timeout=timeout_s)
            return RunResult(
                exit_code=proc.returncode,
                output=proc.stdout,
                stderr=proc.stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
                model=model, provider=provider,
            )
        except subprocess.TimeoutExpired:
            return RunResult(124, "", f"ssh timed out after {timeout_s}s", 0, model, provider,
                             error="timeout")
