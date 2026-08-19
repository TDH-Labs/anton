"""Executor contract: run a task -> RunResult. Executors are swappable.

Usage fields (tokens/cost) are filled only for cloud providers (Q1); local executors
leave them None. Integration with real runtimes happens on the disposable VM — never
on the reference machine.
"""
from __future__ import annotations

import abc
import dataclasses
import time
from typing import Optional


@dataclasses.dataclass
class RunResult:
    exit_code: int
    output: str
    stderr: str
    duration_ms: int
    model: str
    provider: str
    fallback_used: bool = False
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    cost_usd: Optional[float] = None
    error: Optional[str] = None


class Executor(abc.ABC):
    @abc.abstractmethod
    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        """Execute `task` and return a RunResult. Must not block past timeout_s."""
