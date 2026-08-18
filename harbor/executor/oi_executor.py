"""Optional OI-core executor (office/PDF/media specialist, Q1).

Uses `interpreter exec --json --sandbox read-only -o <tmp>`. Integration-tested on the
disposable VM. Tokens/usage parsed from JSONL events when present (cloud routes only).
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


class OIExecutor(Executor):
    def __init__(self, interpreter_bin: str = "interpreter"):
        self.interpreter_bin = interpreter_bin

    def available(self) -> bool:
        return shutil.which(self.interpreter_bin) is not None

    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        if not self.available():
            return RunResult(1, "", f"interpreter binary not found: {self.interpreter_bin}",
                             0, model, provider, error="ENOENT")
        started = time.monotonic()
        out_path = os.path.join(tempfile.gettempdir(), f"oi-exec-{os.getpid()}.txt")
        try:
            proc = subprocess.run(
                [self.interpreter_bin, "exec", "--json", "--sandbox", "read-only",
                 "--skip-git-repo-check", "-o", out_path, task],
                capture_output=True, text=True, cwd=cwd, timeout=timeout_s,
            )
            output = ""
            if os.path.exists(out_path):
                with open(out_path, encoding="utf-8") as f:
                    output = f.read().strip()
            tokens_in = tokens_out = None
            for line in proc.stdout.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = (ev.get("payload") or {}).get("usage") or ev.get("usage")
                if isinstance(usage, dict):
                    tokens_in = usage.get("input_tokens") or tokens_in
                    tokens_out = usage.get("output_tokens") or tokens_out
            return RunResult(
                exit_code=proc.returncode,
                output=output,
                stderr=proc.stderr,
                duration_ms=int((time.monotonic() - started) * 1000),
                model=model,
                provider=provider,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        except subprocess.TimeoutExpired:
            return RunResult(124, "", f"timed out after {timeout_s}s", 0, model, provider,
                             error="timeout")
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass
