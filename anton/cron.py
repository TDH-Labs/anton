"""Minimal deterministic 5-field cron (subset: *, lists, ranges, steps, numbers).

minute hour day_of_month month day_of_week  (dow: 0=Sunday)
"""
from __future__ import annotations

import datetime as dt


def _parse_field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        body = part
        if "/" in part:
            body, step_s = part.split("/", 1)
            step = int(step_s)
        if body in ("", "*"):
            lo_v, hi_v = lo, hi
        elif "-" in body:
            a, b = body.split("-", 1)
            lo_v, hi_v = int(a), int(b)
        else:
            lo_v = hi_v = int(body)
        lo_v, hi_v = max(lo, min(hi, lo_v)), max(lo, min(hi, hi_v))
        out.update(range(lo_v, hi_v + 1, step))
    return out


class Cron:
    def __init__(self, expr: str):
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"cron must have 5 fields, got {len(parts)}: {expr!r}")
        self.expr = expr
        self.minutes = _parse_field(parts[0], 0, 59)
        self.hours = _parse_field(parts[1], 0, 23)
        self.days = _parse_field(parts[2], 1, 31)
        self.months = _parse_field(parts[3], 1, 12)
        # cron convention: 0 or 7 = Sunday, 1 = Monday .. 6 = Saturday.
        # python weekday(): 0 = Monday .. 6 = Sunday -> w = (v + 6) % 7
        self.dows = {(v + 6) % 7 for v in _parse_field(parts[4], 0, 7)}

    def matches(self, when: dt.datetime) -> bool:
        if when.minute not in self.minutes:
            return False
        if when.hour not in self.hours:
            return False
        if when.month not in self.months:
            return False
        if when.day not in self.days:
            return False
        if when.weekday() not in self.dows:
            return False
        return True

    def next_after(self, when: dt.datetime, horizon_days: int = 366) -> dt.datetime | None:
        t = when.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        end = when + dt.timedelta(days=horizon_days)
        while t <= end:
            if self.matches(t):
                return t
            t += dt.timedelta(minutes=1)
        return None
