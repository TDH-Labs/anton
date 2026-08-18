"""Ambition governor: EV × feasibility scoring + confidence-gated routing (R1/R5/R7 overrides)."""
from __future__ import annotations

import dataclasses

AUTO_EXECUTE = "auto_execute"
PRESENT_WITH_EVIDENCE = "present_with_evidence"
LEARN_FIRST = "learn_first"
PRESENT_FOR_APPROVAL = "present_for_approval"

HARD_GATE_KINDS = {"money", "outbound"}


@dataclasses.dataclass
class Ruling:
    route: str
    score: float
    reasons: list[str]


def score(ev: float, feasibility: float) -> float:
    return round(ev * feasibility, 3)


def classify(ev: float, feasibility: float, *,
             risk: str = "low", kind: str = "internal",
             auto_threshold: float = 0.7) -> Ruling:
    s = score(ev, feasibility)
    reasons: list[str] = []
    if kind in HARD_GATE_KINDS:
        return Ruling(PRESENT_FOR_APPROVAL, s, ["hard gate: kind=%s" % kind])
    if s >= auto_threshold and risk == "low":
        return Ruling(AUTO_EXECUTE, s, ["score>=threshold and low risk"])
    if risk == "high":
        reasons.append("high risk")
    if feasibility < 0.4:
        return Ruling(LEARN_FIRST, s, reasons + ["low feasibility -> learn first"])
    return Ruling(PRESENT_WITH_EVIDENCE, s, reasons + ["uncertain -> present with evidence"])
