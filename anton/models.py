"""Core data model. R9: the ledger records model/provider/tokens/duration from day one.

tokens_in/tokens_out/cost_usd are populated ONLY for cloud providers (Q1); local
providers keep them None and `token_accounting` identifies the regime.
"""
from __future__ import annotations

import dataclasses
import platform
import time
import uuid
from typing import Optional


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclasses.dataclass
class RunRecord:
    ts: str
    task: str
    exit: int
    flags: str
    output: str
    model: str
    provider: str
    fallback_used: bool
    tokens_in: Optional[int]
    tokens_out: Optional[int]
    cost_usd: Optional[float]
    duration_ms: int
    host: str
    session_id: str
    org_id: str = "default"
    token_accounting: str = "local"  # "local" | "cloud"

    @classmethod
    def new(
        cls,
        *,
        task: str,
        ts: Optional[str] = None,
        exit_code: int,
        flags: str = "",
        output: str = "",
        model: str = "",
        provider: str = "local",
        fallback_used: bool = False,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        cost_usd: Optional[float] = None,
        duration_ms: int = 0,
        session_id: Optional[str] = None,
        org_id: str = "default",
    ) -> "RunRecord":
        accounting = "cloud" if provider not in ("local", "ollama", "lmstudio") else "local"
        if accounting == "local":
            tokens_in = tokens_out = None
            cost_usd = None
        return cls(
            ts=ts or _now_iso(),
            task=task,
            exit=exit_code,
            flags=flags,
            output=output,
            model=model,
            provider=provider,
            fallback_used=fallback_used,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            host=platform.node(),
            session_id=session_id or str(uuid.uuid4()),
            org_id=org_id,
            token_accounting=accounting,
        )

    def to_json(self) -> dict:
        return dataclasses.asdict(self)
