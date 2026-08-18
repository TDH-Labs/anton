"""Expected-vs-actual canary (R6): now - last_run > 2×cadence -> tripwire."""
from __future__ import annotations

import datetime as dt
from typing import List

from .jobs import Job
from .ledger import Ledger

FACTOR = 2


def compute_tripwires(jobs: List[Job], ledger: Ledger,
                      now: dt.datetime | None = None) -> List[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    tripwires = []
    for job in jobs:
        cadence = job.expected_cadence_min
        if not cadence:
            continue
        last = ledger.last_run(job.id)
        if last is None:
            tripwires.append({"job_id": job.id, "last_seen": None,
                              "expected_min": cadence, "status": "tripwire"})
            continue
        last_dt = dt.datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
        age_min = (now - last_dt).total_seconds() / 60.0
        if age_min > FACTOR * cadence:
            tripwires.append({"job_id": job.id, "last_seen": last["ts"],
                              "expected_min": cadence, "age_min": round(age_min, 1),
                              "status": "tripwire"})
    return tripwires
