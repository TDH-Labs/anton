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
    #: Does a successful run() need a live model provider behind it -- a
    #: reachable local endpoint or a cloud API key? Declared here rather than
    #: inferred with isinstance in scheduler._provider_block, so a stub
    #: inherits the right answer from whatever it subclasses and a new
    #: executor states its own. A nominal isinstance check in another module
    #: is undiscoverable to the author of a new executor: a test stub
    #: subclassing Executor directly silently became gated on the developer's
    #: local Ollama, passing locally and failing on CI. True is the honest
    #: conservative default -- an executor that calls a model must say
    #: nothing and still be gated.
    requires_model_provider: bool = True

    @abc.abstractmethod
    def run(self, task: str, *, model: str, provider: str,
            cwd: Optional[str] = None, timeout_s: Optional[float] = None) -> RunResult:
        """Execute `task` and return a RunResult. Must not block past timeout_s."""
