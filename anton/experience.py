"""learn-from-experience's own-practice path: diagnose Anton's OWN repeated
failures from real ledger output, not external research. Distinct from
upskill.py's edge-thinker/external-research path (meta_learning.py decides
which of the two a given candidate should go through, and neither is called
directly by delta.py's candidates anymore -- see meta_learning.route()).

Shares upskill.py's distillation contract (SKILL.md + a real evaluator with
--selftest) and the same sandbox-gate/governor-promotion machinery, since
both paths must end at the same deterministic-evaluator synthesis and the
same safety gates -- only the SOURCE of the distillation differs (real
failure logs here, external research there).
"""
from __future__ import annotations

import os
from typing import Optional

from .learning import record_lesson
from .routes import select_route
from .sandbox import run_sandbox_gate
from .upskill import UpskillResult, _dispatch, _promote_staged_skill, validate_distilled_skill
from .governor import AUTO_EXECUTE, classify

_PROMOTION_RISK_PROFILE = {"ev": 0.9, "feasibility": 0.9, "risk": "low", "kind": "internal"}


def gather_failure_samples(ledger, task: str, *, limit: int = 5) -> list[dict]:
    """The real evidence learn-from-experience's own Step 2 requires reading
    ('the actual failure output/log -- not the wrapper's summary'). Most
    recent failures first."""
    samples = [r for r in ledger.read() if r.get("task") == task and r.get("exit") != 0]
    samples.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return samples[:limit]


def build_diagnosis_prompt(task: str, slug: str, failure_samples: list[dict],
                           research_dir: str, out_dir: str, *, max_attempts: int = 3) -> str:
    samples_text = "\n\n".join(
        f"--- attempt at {s.get('ts')} ---\nexit={s.get('exit')}  flags={s.get('flags')}\n"
        f"output: {(s.get('output') or '')[:1000]}"
        for s in failure_samples
    )
    return f"""Task "{task}" has failed repeatedly. Here is the REAL failure output from
its last {len(failure_samples)} failed run(s) -- read it, do not guess from a summary:

{samples_text}

Follow this loop (bounded, do not exceed {max_attempts} fix attempts):

1. Diagnose the root cause from the actual output above: is it a config error (wrong
   path/flag/token), a logic error (wrong assumption), an environment error (missing
   dependency, wrong host), or a timing/ordering error (ran before its dependency)? Name
   it in one sentence. If you can't, gather one more diagnostic before attempting a fix.
2. Research additional solutions only if genuinely needed (bounded -- at most a couple of
   diagnostic passes; research without an attempt is procrastination). Look for the fix
   in the codebase's own history and sibling tasks that already solved something similar
   before searching externally.
3. Attempt one change at a time; verify with a real re-run of the task, not intention.
   On failure, iterate with an updated hypothesis, up to the attempt budget.
4. Document what worked (the exact steps + the verification that proved it) and what did
   NOT work (each failed attempt as an anti-pattern: what looked reasonable but failed,
   and why).

Then write the result as an installable skill at {out_dir}/SKILL.md with this exact shape:

---
name: {slug}
description: <one sentence: what this fixes and when to apply it>
author: anton-upskill
version: 1.0.0
---

# <Title>

## Operational Directive
<the diagnostic + fix workflow, step by step>

## Do
<the successful path, specifically -- not generic advice>

## Don't
<every failed attempt as a named anti-pattern, from step 4 above>

## Measure
<the resource/efficiency lesson: how many attempts it took, what was wasted, and the
budget cap so a future run doesn't repeat the waste>

## Validation
<how to verify the fix actually worked -- the specific re-run and what a passing result
looks like>

ALSO write {out_dir}/scripts/{slug}_evaluator.py: a real Python evaluator with a
`--selftest` mode asserting at least 2 golden (input, expected) pairs derived from what
you actually learned -- not a placeholder.

If useful research notes were pulled in during step 2, save them under {research_dir}/
following the usual <date>-<subject>-<TYPE>-<n>.md convention so they're not lost, but
this skill's promotion does not require the >=5-source research gate -- it is grounded
in real failure evidence, not external research."""


def dispatch_experience_iteration(engine, task: str, *, max_attempts: int = 3,
                                  model: Optional[str] = None, provider: Optional[str] = None,
                                  timeout_s: Optional[float] = None) -> UpskillResult:
    """The learn-from-experience path: diagnose -> attempt -> verify -> iterate
    -> embed, from Anton's own real failures. Ends at the SAME sandbox gate +
    governor promotion as upskill.run_upskill (edge-thinker), sharing
    upskill.py's promotion helpers rather than duplicating them."""
    from .upskill import slugify
    slug = slugify(task)
    route = select_route(prefer="cloud")
    model = model or route.model
    provider = provider or route.provider
    vault_dir = os.path.join(engine.data_dir, "vault")
    research_dir = os.path.join(vault_dir, "notes", "research", slug)
    out_dir = os.path.join(engine.data_dir, "staging", slug)
    os.makedirs(research_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "scripts"), exist_ok=True)

    samples = gather_failure_samples(engine.ledger, task)
    if not samples:
        return UpskillResult(slug=slug, subject=task, status="insufficient_research",
                             detail="no real failure samples in the ledger for this task")

    prompt = build_diagnosis_prompt(task, slug, samples, research_dir, out_dir,
                                    max_attempts=max_attempts)
    _dispatch(engine, task_label=f"upskill:{slug}:experience", prompt=prompt,
             model=model, provider=provider, timeout_s=timeout_s, slug=slug, stage="experience")

    ok, problems = validate_distilled_skill(out_dir, slug)
    if not ok:
        record_lesson(os.path.join(engine.data_dir, "isolation.db"), slug, "dont",
                      f"experience-iteration output invalid: {'; '.join(problems)}",
                      source="experience:validate")
        return UpskillResult(slug=slug, subject=task, status="sandbox_failed",
                             detail="; ".join(problems))

    script_path = os.path.join(out_dir, "scripts", f"{slug}_evaluator.py")
    sandbox_ok = run_sandbox_gate(script_path, golden_payload="--selftest",
                                  db_path=os.path.join(engine.data_dir, "isolation.db"), slug=slug)
    if not sandbox_ok:
        record_lesson(os.path.join(engine.data_dir, "isolation.db"), slug, "dont",
                      "sandbox gate (py_compile / --selftest) failed", source="experience:sandbox")
        return UpskillResult(slug=slug, subject=task, status="sandbox_failed",
                             detail="sandbox gate failed")

    ruling = classify(_PROMOTION_RISK_PROFILE["ev"], _PROMOTION_RISK_PROFILE["feasibility"],
                      risk=_PROMOTION_RISK_PROFILE["risk"], kind=_PROMOTION_RISK_PROFILE["kind"])
    if ruling.route != AUTO_EXECUTE:
        import datetime as dt
        import sqlite3
        import uuid
        db_path = os.path.join(engine.data_dir, "isolation.db")
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            nonce = f"upskill-{slug}-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO approvals(nonce, action, amount, recipient, status,"
                " ts, initiator_human, initiator_principal) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (nonce, f"upskill_promote:{slug}", "", "", "pending",
                 dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "system", "system:upskill"))
            conn.commit()
        return UpskillResult(slug=slug, subject=task, status="pending_approval",
                             detail=f"route={ruling.route}")

    _promote_staged_skill(engine.data_dir, slug, out_dir)
    return UpskillResult(slug=slug, subject=task, status="promoted")
