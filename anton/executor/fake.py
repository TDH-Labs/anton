"""Deterministic stub executor for tests and dry-run demos. Never touches the fleet."""
from __future__ import annotations

import time
from typing import Optional

from .base import Executor, RunResult


class FakeExecutor(Executor):
    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        started = time.monotonic()
        time.sleep(0.001)
        return RunResult(
            exit_code=0,
            output=f"[fake] ok: {task[:200]}",
            stderr="",
            duration_ms=int((time.monotonic() - started) * 1000),
            model=model,
            provider=provider,
            fallback_used=False,
        )
