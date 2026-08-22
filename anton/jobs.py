"""jobs.yaml loader — manifest-as-executable-spec (R6: triggers/verify are code)."""
from __future__ import annotations

import dataclasses
from typing import List, Optional

import yaml

from .cron import Cron


@dataclasses.dataclass
class Job:
    id: str
    trigger: dict          # {type: cron|webhook|delta, ...}
    recipe: str
    model_route: str = "local-default"
    budget: Optional[dict] = None
    verify: Optional[str] = None
    expected_cadence_min: Optional[int] = None
    dry_run: bool = False
    gate: Optional[dict] = None
    cron: Optional[Cron] = None
    # Overrides JobEngine's default executor for just this job, e.g.
    # {name: opencode, mcp_profile: quickbooks} to dispatch through
    # OpenCodeExecutor with @playwright/mcp attached to a stored-login
    # session's persistent profile (browser_login.py). None means "use the
    # engine's default executor," the only behavior that existed before this
    # field -- everything else is opt-in.
    executor: Optional[dict] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        trigger = d.get("trigger") or {}
        cron = None
        if trigger.get("type") == "cron":
            cron = Cron(trigger["expr"])
        return cls(
            id=str(d["id"]),
            trigger=trigger,
            recipe=str(d.get("recipe", d["id"])),
            model_route=d.get("model_route", "local-default"),
            budget=d.get("budget"),
            verify=d.get("verify"),
            expected_cadence_min=d.get("expected_cadence_min"),
            dry_run=bool(d.get("dry_run", False)),
            gate=d.get("gate"),
            cron=cron,
            executor=d.get("executor"),
        )

    def next_fire(self, now):
        if self.cron:
            return self.cron.next_after(now)
        return None


def load_jobs(path: str) -> List[Job]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    return [Job.from_dict(d) for d in raw]
