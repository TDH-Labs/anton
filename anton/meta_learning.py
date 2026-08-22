"""meta-learning: the governor over learn-from-research (upskill.py,
edge-thinker) and learn-from-experience (experience.py) -- and over the
whole skill portfolio. This module is the actual entry point delta.py's
candidates and the `anton upskill` CLI should call; neither upskill.py's
run_upskill nor experience.py's dispatch_experience_iteration should be
invoked directly by anything except this module and manual/explicit calls
(cmd_upskill --subject still calls run_upskill directly when a human names
an unambiguous new subject -- see route()'s docstring for exactly when that
applies).

Five responsibilities, each a function here, matching the skill text seeded
by meta_skills.py's META_LEARNING:
  (a) check the existing skill pool first, reuse, never rebuild -- find_existing_skill
  (b) decide learn-vs-do, and which of the two learning paths -- decide
  (c) sequence pending learning to unblock the critical path -- sequence_pending_upskills
  (d) know when to stop learning and act (optimal stopping) -- decide's "stop" outcome
  (e) triage the skill portfolio: usage, routing, staleness -- triage_skill_portfolio
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import os
import shutil
import sqlite3
from typing import Optional

from .experience import dispatch_experience_iteration
from .governor import AUTO_EXECUTE
from .upskill import UpskillResult, _dispatch_gate_ruling, run_upskill, slugify


@dataclasses.dataclass
class Decision:
    action: str  # "reuse" | "learn_from_research" | "learn_from_experience" | "stop"
    skill_slug: Optional[str]
    reason: str


def find_existing_skill(data_dir: str, subject_or_task: str) -> Optional[str]:
    """(a) Check the pool first. Exact slug match, then a cheap keyword-
    overlap match against each skill's indexed description -- good enough to
    catch "widget repair" matching a skill titled "widgets: repair
    procedure" without needing embeddings Anton doesn't have."""
    slug = slugify(subject_or_task)
    skills_dir = os.path.join(data_dir, "skills")
    if os.path.isdir(os.path.join(skills_dir, slug)):
        return slug
    db_path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        rows = conn.execute("SELECT skill_slug, target_capability FROM skill_dependencies").fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    query_words = {w for w in slug.split("-") if len(w) > 2}
    if not query_words:
        return None
    best_slug, best_overlap = None, 0
    for existing_slug, desc in rows:
        desc_words = {w.lower() for w in (desc or "").replace("-", " ").split() if len(w) > 2}
        overlap = len(query_words & desc_words)
        if overlap > best_overlap:
            best_slug, best_overlap = existing_slug, overlap
    # require at least half the query's meaningful words to match -- a loose
    # single-word coincidence isn't reuse, it's a false positive.
    if best_slug and best_overlap >= max(1, len(query_words) // 2):
        return best_slug
    return None


def _has_recent_pending_attempt(data_dir: str, slug: str, *, window_hours: int = 24) -> bool:
    """(d) optimal stopping, the narrow case: don't re-dispatch research for
    something already staged and awaiting approval -- wait for that to
    resolve instead of burning another research pass on the same subject."""
    db_path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(db_path):
        return False
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=window_hours)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        row = conn.execute(
            "SELECT id FROM approvals WHERE action=? AND status='pending' AND ts>=?",
            (f"upskill_promote:{slug}", since)).fetchone()
    finally:
        conn.close()
    return row is not None


def decide(engine, subject_or_task: str, *, is_repeated_failure: bool = False) -> Decision:
    """(b) learn-vs-do, and which learning path. (d) optimal stopping."""
    slug = slugify(subject_or_task)
    existing = find_existing_skill(engine.data_dir, subject_or_task)
    if existing:
        return Decision("reuse", existing, f"matches existing skill {existing}")
    if _has_recent_pending_attempt(engine.data_dir, slug):
        return Decision("stop", slug, "already staged and awaiting approval -- not re-dispatching")
    if is_repeated_failure:
        return Decision("learn_from_experience", slug,
                        "repeated failure of Anton's own task -- diagnose real evidence, not external research")
    return Decision("learn_from_research", slug,
                    "no existing skill and no local failure evidence -- research external expertise")


def route(engine, subject_or_task: str, *, is_repeated_failure: bool = False, **kwargs) -> UpskillResult:
    """The actual entry point. delta.py's candidates and `anton upskill` both
    call this, not upskill.run_upskill / experience.dispatch_experience_iteration
    directly -- meta-learning decides which of those two (if either) applies."""
    d = decide(engine, subject_or_task, is_repeated_failure=is_repeated_failure)
    if d.action == "reuse":
        return UpskillResult(slug=d.skill_slug, subject=subject_or_task, status="reused", detail=d.reason)
    if d.action == "stop":
        return UpskillResult(slug=d.skill_slug, subject=subject_or_task, status="stopped", detail=d.reason)
    if d.action == "learn_from_experience":
        return dispatch_experience_iteration(engine, subject_or_task, **kwargs)
    return run_upskill(engine, subject_or_task, **kwargs)


def sequence_pending_upskills(engine) -> list[str]:
    """(c) sequence to unblock the critical path. Anton has no general
    dependency graph between jobs/skills to do true critical-path analysis,
    so this is a documented proxy: highest repeat-count first (the ledger
    flags carry it, e.g. "repeated_failures:N"), then oldest first -- a
    competence gap blocking the most runs, longest, goes first."""
    db_path = os.path.join(engine.data_dir, "isolation.db")
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        rows = conn.execute(
            "SELECT slug, source, ts FROM initiatives WHERE status='pending' AND slug LIKE 'upskill-%'"
        ).fetchall()
    finally:
        conn.close()

    def _repeat_count(source: str) -> int:
        if "repeated_failures:" not in source:
            return 0
        try:
            return int(source.rsplit(":", 1)[1])
        except ValueError:
            return 0

    rows.sort(key=lambda r: (-_repeat_count(r[1]), r[2]))
    return [r[0] for r in rows]


def process_pending_candidates(engine) -> list[dict]:
    """The entry point delta.py's automatically-detected candidates go
    through -- called from cli.py's cmd_serve loop. Still gated by
    upskill.py's research-start governor profile (starting research needs a
    wider bash+write tool grant than any other auto job gets, so it stays
    conservative-by-default regardless of which of the two learning paths
    meta-learning eventually picks), sequenced by (c) critical-path proxy,
    then routed through decide()/route() rather than calling either learning
    path directly."""
    ordered_slugs = sequence_pending_upskills(engine)
    db_path = os.path.join(engine.data_dir, "isolation.db")
    outcomes = []
    for slug in ordered_slugs:
        subject = slug[len("upskill-"):]
        ruling = _dispatch_gate_ruling()
        if ruling.route != AUTO_EXECUTE:
            outcomes.append({"slug": slug, "action": "left_pending", "route": ruling.route})
            continue
        result = route(engine, subject, is_repeated_failure=True)
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            conn.execute("UPDATE initiatives SET status='dispatched' WHERE slug=?", (slug,))
            conn.commit()
        outcomes.append({"slug": slug, "action": "dispatched", "status": result.status})
    return outcomes


def sequence_pending_opportunities(engine) -> list[str]:
    """Same proxy-sequencing idea as sequence_pending_upskills, applied to
    opportunity.py's candidates: highest self-assessed worth first (the
    scan already filtered to min_worth, so ties are common), then oldest
    first."""
    db_path = os.path.join(engine.data_dir, "isolation.db")
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        rows = conn.execute(
            "SELECT slug, source, ts FROM initiatives WHERE status='pending' AND slug LIKE 'opportunity-%'"
        ).fetchall()
    finally:
        conn.close()

    worth_rank = {"high": 2, "medium": 1, "low": 0}

    def _worth(source: str) -> int:
        if "worth=" not in source:
            return 0
        return worth_rank.get(source.rsplit("worth=", 1)[1], 0)

    rows.sort(key=lambda r: (-_worth(r[1]), r[2]))
    return [r[0] for r in rows]


def process_pending_opportunities(engine) -> list[dict]:
    """The entry point opportunity.py's scan-detected candidates go
    through, mirroring process_pending_candidates: same research-start
    governor gate (a scan finding still needs the wider bash+write tool
    grant to research), same sequencing-then-routing shape. An opportunity
    is by construction a subject nobody has tried before, so
    is_repeated_failure=False -- decide() resolves it to reuse (pool
    already covers it) or learn_from_research, never straight to
    learn_from_experience (there's no failure evidence for something that
    hasn't been attempted yet)."""
    ordered_slugs = sequence_pending_opportunities(engine)
    db_path = os.path.join(engine.data_dir, "isolation.db")
    outcomes = []
    for slug in ordered_slugs:
        subject = slug[len("opportunity-"):]
        ruling = _dispatch_gate_ruling()
        if ruling.route != AUTO_EXECUTE:
            outcomes.append({"slug": slug, "action": "left_pending", "route": ruling.route})
            continue
        result = route(engine, subject, is_repeated_failure=False)
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            conn.execute("UPDATE initiatives SET status='dispatched' WHERE slug=?", (slug,))
            conn.commit()
        outcomes.append({"slug": slug, "action": "dispatched", "status": result.status})
    return outcomes


@dataclasses.dataclass
class TriageReport:
    active: list[str]
    archived: list[str]


def triage_skill_portfolio(engine, *, stale_days: int = 90) -> TriageReport:
    """(e) portfolio triage: a skill with zero applications
    (task=f"{slug}:apply", the convention learning.record_lesson's
    lesson-capture scan also uses) in the last stale_days is dormant --
    archived (moved, not deleted -- reversible), not "improved". The two
    standard meta-skills (upskill-from-research, upskill-from-experience,
    meta-learning itself) are never triaged: they have no jobs to apply
    against by design and are always available."""
    protected = {"upskill-from-research", "upskill-from-experience", "meta-learning"}
    skills_dir = os.path.join(engine.data_dir, "skills")
    if not os.path.isdir(skills_dir):
        return TriageReport(active=[], archived=[])
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=stale_days)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    applied_recently = set()
    for row in engine.ledger.read():
        task = row.get("task", "")
        if row.get("ts", "") >= since and task.endswith(":apply"):
            applied_recently.add(task[: -len(":apply")])

    active, archived = [], []
    archive_dir = os.path.join(engine.data_dir, "skills-archive")
    for slug in sorted(os.listdir(skills_dir)):
        if slug in protected or not os.path.isdir(os.path.join(skills_dir, slug)):
            continue
        if slug in applied_recently:
            active.append(slug)
            continue
        os.makedirs(archive_dir, exist_ok=True)
        dest = os.path.join(archive_dir, slug)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.move(os.path.join(skills_dir, slug), dest)
        db_path = os.path.join(engine.data_dir, "isolation.db")
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            conn.execute("DELETE FROM skill_dependencies WHERE skill_slug=?", (slug,))
            conn.commit()
        archived.append(slug)
    return TriageReport(active=active, archived=archived)
