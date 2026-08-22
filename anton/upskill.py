"""Research-first upskilling (§8, extended). The current single-heuristic
skill authoring (learning.py's author_skill, driven by manually-supplied
title/condition/steps) stays as-is for a human explicitly dictating a
skill's content. This module is the OTHER path: research across trades
journals, expert interviews, books, and web sources (>=5 sources across
>=2 types, verified in the vault, never trusted from the dispatched agent's
self-report) BEFORE any skill is distilled and promoted. See
anton/meta_skills.py for the two standard skills this module's own
methodology is seeded from (upskill-from-research is this module's operating
manual; upskill-from-experience is its twin for Anton's own lived failures).

Research and distillation dispatch need real bash+write from the executor --
strictly more capability than the read-only default (config.py's
general.pi_tools) any other auto-executed job gets. That is reflected in two
separate governor gates: starting research (gated only for automatically
delta-detected candidates -- an explicit `anton upskill --subject` requires
no gate, same posture as author_skill's --title today) and promoting the
distilled skill (always gated, but only ever reached after research
sufficiency + the sandbox gate already passed).
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import os
import re
import sqlite3
from typing import Optional

import yaml

from .governor import AUTO_EXECUTE, classify
from .jobs import Job
from .learning import index_skills, mark_lessons_consumed, record_lesson, unconsumed_lessons
from .models import RunRecord
from .routes import select_route
from .sandbox import promote, run_sandbox_gate
from .vault import emit_candidate

SOURCE_TYPES = ("TRADES", "INTERVIEW", "BOOK", "WEB")

# Governor inputs for an *automatically* delta-detected upskill candidate
# (nobody chose the subject -- see delta.py's scan_upskill_candidates).
# Deliberately conservative: research dispatch needs a wider bash+write tool
# grant than any other auto-executed job, so a fresh install should not have
# an unattended agent with that grant firing on its own inference by
# default. A deployment that wants full autonomy calls
# set_dispatch_risk_profile() to lower this below the auto_threshold.
_DISPATCH_RISK_PROFILE = {"ev": 0.5, "feasibility": 0.8, "risk": "medium", "kind": "internal"}

# Governor inputs for promoting an already-research-verified, already
# sandbox-gate-passed distillation. "low risk" here is earned by two prior
# gates having already run, not assumed.
_PROMOTION_RISK_PROFILE = {"ev": 0.9, "feasibility": 0.9, "risk": "low", "kind": "internal"}


def set_dispatch_risk_profile(*, ev: float, feasibility: float, risk: str = "low",
                              kind: str = "internal") -> None:
    """Let a deployment opt an automatically-detected upskill candidate into
    unattended dispatch (mirrors canary.py's register_repair_recipe)."""
    _DISPATCH_RISK_PROFILE.update({"ev": ev, "feasibility": feasibility, "risk": risk, "kind": kind})


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "subject"


# --------------------------------------------------------------------------
# Step 1: research
# --------------------------------------------------------------------------

def build_research_prompt(subject: str, research_dir: str, *, min_sources: int = 5,
                          min_types: int = 2, missing_types: Optional[list[str]] = None) -> str:
    retry_note = ""
    if missing_types:
        retry_note = (
            f"\nA prior attempt fell short. You still need sources from: "
            f"{', '.join(missing_types)}. Notes already on disk under {research_dir} "
            f"already count toward the total -- add to them, do not discard them.\n"
        )
    return f"""Research the subject "{subject}" the way a top performer would learn it,
across all four source layers (skip a type only if you name why in a note):

1. TRADES -- the field's top trade journals/publications. Find free/online editions,
   read the Table of Contents of recent issues to map real topics and edge cases, then
   fetch and read the relevant articles. Capture edge cases verbatim.
2. INTERVIEW -- recognized top experts discussing this subject (video or written); pull
   transcripts with whatever fetch/transcription capability you have. Favor interviews
   where the expert explains workflow/decisions, not hype.
3. BOOK -- 2-4 definitive books via free/legal sources (Google Books previews, Internet
   Archive, Anna's Archive). Read the foundational chapters and decision frameworks.
4. WEB -- docs, case studies, trade-association reports, run-books, for currency.
{retry_note}
Gather at least {min_sources} independent sources spanning at least {min_types} of the
four types above.

For EACH source, write one markdown file under:
  {research_dir}/<YYYY-MM-DD>-{slugify(subject)}-<TYPE>-<n>.md
where <TYPE> is exactly one of TRADES, INTERVIEW, BOOK, WEB and <n> is a counter
starting at 1 for that type.

Each file MUST start with this exact frontmatter shape (fill in every field):
---
type: research
subject: {slugify(subject)}
source_type: <TYPE>
source_title: <the source's real title>
source_ref: <a URL, an ISBN, or an archive locator -- something checkable>
captured: <ISO8601 timestamp>
---

And MUST contain these three sections in the body:
## Key claims
## Edge cases
## Anti-patterns

Do not write a summary skill yet -- only capture sources in this pass."""


@dataclasses.dataclass
class ResearchReport:
    sources: list[dict]
    by_type: dict[str, int]
    sufficient: bool
    missing_types: list[str]
    reasons: list[str]


def _parse_frontmatter(text: str) -> Optional[dict]:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def verify_research(vault_dir: str, subject_slug: str, *, min_sources: int = 5,
                    min_types: int = 2) -> ResearchReport:
    """Independently count what actually landed in the vault -- never trust
    the dispatched agent's own claim of what it did."""
    research_dir = os.path.join(vault_dir, "notes", "research", subject_slug)
    sources: list[dict] = []
    by_type: dict[str, int] = {}
    if os.path.isdir(research_dir):
        for fn in sorted(os.listdir(research_dir)):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(research_dir, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            fm = _parse_frontmatter(text)
            if not fm or fm.get("type") != "research":
                continue
            source_type = str(fm.get("source_type", "")).upper()
            if source_type not in SOURCE_TYPES:
                continue
            if not fm.get("source_ref"):
                continue
            if "## key claims" not in text.lower() or "## edge cases" not in text.lower():
                continue
            sources.append({"path": path, "source_type": source_type,
                            "source_ref": fm.get("source_ref"), "source_title": fm.get("source_title")})
            by_type[source_type] = by_type.get(source_type, 0) + 1
    missing_types = [t for t in SOURCE_TYPES if t not in by_type]
    sufficient = len(sources) >= min_sources and len(by_type) >= min_types
    reasons = []
    if len(sources) < min_sources:
        reasons.append(f"{len(sources)}/{min_sources} sources")
    if len(by_type) < min_types:
        reasons.append(f"{len(by_type)}/{min_types} source types")
    return ResearchReport(sources=sources, by_type=by_type, sufficient=sufficient,
                          missing_types=missing_types, reasons=reasons)


# --------------------------------------------------------------------------
# Step 2: distillation
# --------------------------------------------------------------------------

def build_distillation_prompt(subject: str, slug: str, research_dir: str, out_dir: str) -> str:
    return f"""Read every research note under {research_dir}. Synthesize across ALL of
them into a single installable skill at {out_dir}/SKILL.md with this exact shape:

---
name: {slug}
description: <one sentence: what this skill is for and when to use it>
author: anton-upskill
version: 1.0.0
---

# <Title>

## Operational Directive
<the core workflow, step by step, executable and specific -- not a summary>

## Do
<the durable do-rules derived from the research>

## Don't
<EVERY anti-pattern found across the research notes -- this list is what survives>

## Measure
<a concrete metric/unit/ratio that proves the skill worked -- not prose>

## Validation
<how to know a task done with this skill is done right>

If two sources contradict, record both and pick the one with more evidence/reputation,
noting the conflict.

ALSO write {out_dir}/scripts/{slug}_evaluator.py: a real Python evaluator encoding the
derived numeric/threshold decision rule(s) as a function `evaluate(input_value)`. The
script must support a `--selftest` CLI mode: when invoked as
`python3 {slug}_evaluator.py --selftest`, it must run at least 2 golden (input, expected)
assertions derived from the research and exit 0 only if all pass, non-zero otherwise.
Do not leave a TODO or an unconditional pass -- encode the actual rule."""


def validate_distilled_skill(out_dir: str, slug: str) -> tuple[bool, list[str]]:
    """Cheap structural gate before spending a sandbox subprocess: does the
    dispatched agent's output even follow the contract."""
    problems = []
    skill_path = os.path.join(out_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        problems.append("SKILL.md missing")
    else:
        with open(skill_path, encoding="utf-8") as f:
            text = f.read()
        fm = _parse_frontmatter(text)
        if not fm or not fm.get("name") or not fm.get("description"):
            problems.append("SKILL.md frontmatter missing name/description")
        lower = text.lower()
        for section in ("## do", "## don't", "## measure", "## validation"):
            if section not in lower:
                problems.append(f"SKILL.md missing {section} section")
    script_path = os.path.join(out_dir, "scripts", f"{slug}_evaluator.py")
    if not os.path.exists(script_path):
        problems.append("evaluator script missing")
    else:
        with open(script_path, encoding="utf-8") as f:
            script_text = f.read()
        if "--selftest" not in script_text:
            problems.append("evaluator script has no --selftest mode")
    return (len(problems) == 0, problems)


# --------------------------------------------------------------------------
# Ledger/budget-accounted dispatch (mirrors JobEngine.run_job's bookkeeping --
# this never bypasses it just because it isn't a jobs.yaml-defined job)
# --------------------------------------------------------------------------

def _dispatch(engine, *, task_label: str, prompt: str, model: str, provider: str,
             timeout_s: Optional[float], slug: str, stage: str, attempt: int = 1) -> RunRecord:
    started = dt.datetime.now(dt.timezone.utc)
    result = engine.executor.run(prompt, model=model, provider=provider, timeout_s=timeout_s)
    synthetic_job = Job(id=f"upskill-{slug}", trigger={}, recipe=task_label)
    breach = engine.enforce_budget(synthetic_job, {
        "tokens_in": result.tokens_in, "tokens_out": result.tokens_out, "cost_usd": result.cost_usd,
    })
    exit_code = 3 if breach else result.exit_code
    flags = f"upskill;stage:{stage};attempt:{attempt}" + (f";budget-breach:{breach}" if breach else "")
    record = RunRecord.new(task=task_label, exit_code=exit_code, flags=flags,
                           output=result.output, model=result.model, provider=result.provider,
                           fallback_used=result.fallback_used, tokens_in=result.tokens_in,
                           tokens_out=result.tokens_out, cost_usd=result.cost_usd,
                           duration_ms=result.duration_ms,
                           ts=started.strftime("%Y-%m-%dT%H:%M:%SZ"))
    engine.ledger.append(record)
    engine._record_metering(record)
    if engine.data_dir:
        with sqlite3.connect(os.path.join(engine.data_dir, "isolation.db"), timeout=10.0) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS upskill_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "org_id TEXT DEFAULT 'default', slug TEXT, subject TEXT, stage TEXT, "
                "attempt INTEGER, ok INTEGER, detail TEXT, ts TEXT)")
            conn.execute(
                "INSERT INTO upskill_runs(slug, subject, stage, attempt, ok, detail, ts) "
                "VALUES(?,?,?,?,?,?,?)",
                (slug, task_label, stage, attempt, 1 if exit_code == 0 else 0,
                 (result.stderr or result.output or "")[:500], record.ts))
            conn.commit()
    return record


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

@dataclasses.dataclass
class UpskillResult:
    slug: str
    subject: str
    status: str  # "promoted" | "pending_approval" | "insufficient_research" | "sandbox_failed"
    research: Optional[ResearchReport] = None
    detail: str = ""


def run_upskill(engine, subject: str, *, min_sources: int = 5, min_types: int = 2,
                max_research_attempts: int = 3, model: Optional[str] = None,
                provider: Optional[str] = None, timeout_s: Optional[float] = None) -> UpskillResult:
    """The full research-first pipeline: never authors a skill from a single
    delta/heuristic. See module docstring for the two-gate governor design."""
    slug = slugify(subject)
    route = select_route(prefer="cloud")
    model = model or route.model
    provider = provider or route.provider
    vault_dir = os.path.join(engine.data_dir, "vault")
    research_dir = os.path.join(vault_dir, "notes", "research", slug)
    os.makedirs(research_dir, exist_ok=True)

    report = verify_research(vault_dir, slug, min_sources=min_sources, min_types=min_types)
    missing_types = report.missing_types
    for attempt in range(1, max_research_attempts + 1):
        if report.sufficient:
            break
        prompt = build_research_prompt(subject, research_dir, min_sources=min_sources,
                                       min_types=min_types, missing_types=missing_types)
        _dispatch(engine, task_label=f"upskill:{slug}:research", prompt=prompt,
                 model=model, provider=provider, timeout_s=timeout_s, slug=slug,
                 stage="research", attempt=attempt)
        report = verify_research(vault_dir, slug, min_sources=min_sources, min_types=min_types)
        missing_types = report.missing_types

    if not report.sufficient:
        db_path = os.path.join(engine.data_dir, "isolation.db")
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            emit_candidate(conn, f"upskill-{slug}",
                           f"upskill:insufficient_research:{','.join(report.reasons)}")
        finally:
            conn.close()
        return UpskillResult(slug=slug, subject=subject, status="insufficient_research",
                             research=report, detail="; ".join(report.reasons))

    out_dir = os.path.join(engine.data_dir, "staging", slug)
    os.makedirs(os.path.join(out_dir, "scripts"), exist_ok=True)
    dist_prompt = build_distillation_prompt(subject, slug, research_dir, out_dir)
    _dispatch(engine, task_label=f"upskill:{slug}:distill", prompt=dist_prompt,
             model=model, provider=provider, timeout_s=timeout_s, slug=slug, stage="distill")

    ok, problems = validate_distilled_skill(out_dir, slug)
    if not ok:
        record_lesson(os.path.join(engine.data_dir, "isolation.db"), slug, "dont",
                      f"distillation output invalid: {'; '.join(problems)}", source="upskill:validate")
        return UpskillResult(slug=slug, subject=subject, status="sandbox_failed",
                             research=report, detail="; ".join(problems))

    script_path = os.path.join(out_dir, "scripts", f"{slug}_evaluator.py")
    sandbox_ok = run_sandbox_gate(script_path, golden_payload="--selftest",
                                  db_path=os.path.join(engine.data_dir, "isolation.db"), slug=slug)
    if not sandbox_ok:
        record_lesson(os.path.join(engine.data_dir, "isolation.db"), slug, "dont",
                      "sandbox gate (py_compile / --selftest) failed", source="upskill:sandbox")
        return UpskillResult(slug=slug, subject=subject, status="sandbox_failed", research=report,
                             detail="sandbox gate failed")

    ruling = classify(_PROMOTION_RISK_PROFILE["ev"], _PROMOTION_RISK_PROFILE["feasibility"],
                      risk=_PROMOTION_RISK_PROFILE["risk"], kind=_PROMOTION_RISK_PROFILE["kind"])
    if ruling.route != AUTO_EXECUTE:
        db_path = os.path.join(engine.data_dir, "isolation.db")
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            import uuid
            nonce = f"upskill-{slug}-{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO approvals(nonce, action, amount, recipient, status, hmac, ts) "
                "VALUES (?,?,?,?,?,?,?)",
                (nonce, f"upskill_promote:{slug}", "", "", "pending", "",
                 dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
            conn.commit()
        return UpskillResult(slug=slug, subject=subject, status="pending_approval",
                             research=report, detail=f"route={ruling.route}")

    _promote_staged_skill(engine.data_dir, slug, out_dir)
    return UpskillResult(slug=slug, subject=subject, status="promoted", research=report)


def _promote_staged_skill(data_dir: str, slug: str, out_dir: str) -> None:
    import shutil
    script_path = os.path.join(out_dir, "scripts", f"{slug}_evaluator.py")
    promote(script_path, os.path.join(data_dir, "skills"), slug=slug)
    staging_skill = os.path.join(out_dir, "SKILL.md")
    if os.path.exists(staging_skill):
        dest_dir = os.path.join(data_dir, "skills", slug)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(staging_skill, os.path.join(dest_dir, "SKILL.md"))
    index_skills(data_dir)


def approve_pending_promotion(engine, slug: str) -> bool:
    """Complete a promotion left pending_approval by run_upskill, once an
    operator approves `upskill_promote:<slug>` in the approvals table
    (dashboard.py's existing POST /api/approvals/{aid} flow)."""
    db_path = os.path.join(engine.data_dir, "isolation.db")
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        row = conn.execute(
            "SELECT id FROM approvals WHERE action=? AND status='approved' ORDER BY id ASC LIMIT 1",
            (f"upskill_promote:{slug}",)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE approvals SET status='consumed' WHERE id=?", (row[0],))
        conn.commit()
    out_dir = os.path.join(engine.data_dir, "staging", slug)
    _promote_staged_skill(engine.data_dir, slug, out_dir)
    return True


def _dispatch_gate_ruling():
    """The research-start governor gate, read by meta_learning.py's
    process_pending_candidates -- kept here since _DISPATCH_RISK_PROFILE
    lives here (set_dispatch_risk_profile is the public override point)."""
    return classify(_DISPATCH_RISK_PROFILE["ev"], _DISPATCH_RISK_PROFILE["feasibility"],
                    risk=_DISPATCH_RISK_PROFILE["risk"], kind=_DISPATCH_RISK_PROFILE["kind"])


# --------------------------------------------------------------------------
# Step 7 (edge-thinker's own): consolidate, do not bloat
# --------------------------------------------------------------------------

def build_consolidation_prompt(slug: str, skill_path: str, lessons: list[dict]) -> str:
    lesson_lines = "\n".join(f"- ({l['kind']}) {l['text']} [source: {l['source']}]" for l in lessons)
    return f"""Read the current skill at {skill_path} in full, and these unconsumed
lessons from real use:

{lesson_lines}

Rewrite {skill_path}'s ## Do and ## Don't sections to MERGE these lessons into the
existing structure -- do not append them as a growing list. Prune any existing rule that
a newer, sharper lesson subsumes. Keep the rest of the file (frontmatter, Operational
Directive, Measure, Validation) intact unless a lesson specifically requires updating
one of those too."""


def consolidate_skill(engine, slug: str, *, threshold: int = 3, model: Optional[str] = None,
                      provider: Optional[str] = None, timeout_s: Optional[float] = None) -> bool:
    db_path = os.path.join(engine.data_dir, "isolation.db")
    lessons = unconsumed_lessons(db_path, slug)
    if len(lessons) < threshold:
        return False
    skill_path = os.path.join(engine.data_dir, "skills", slug, "SKILL.md")
    if not os.path.exists(skill_path):
        return False
    route = select_route(prefer="cloud")
    model = model or route.model
    provider = provider or route.provider
    prompt = build_consolidation_prompt(slug, skill_path, lessons)
    _dispatch(engine, task_label=f"upskill:{slug}:consolidate", prompt=prompt,
             model=model, provider=provider, timeout_s=timeout_s, slug=slug, stage="consolidate")
    mark_lessons_consumed(db_path, [l["id"] for l in lessons])
    index_skills(engine.data_dir)
    return True
