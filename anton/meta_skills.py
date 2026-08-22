"""Two standard skills seeded into every fresh Anton install (setup.py calls
seed_meta_skills() right after provision_vault()): the research-first
upskilling methodology (upskill.py's own operating manual, run via
`anton upskill`) and its twin for iterating from Anton's own lived failures.

Adapted from a personal methodology the product's operator uses in a
separate, unrelated agent environment. Every reference to that environment's
own infrastructure (a personal second-brain path, a differently-named skill
CLI, room-based scoping) is rewritten here to Anton's own generic
equivalents -- this file must never reintroduce a reference back to that
environment, since these two skills ship to every business that installs
Anton, not just the operator's own machine. See tests/test_meta_skills.py
for the regression guard.
"""
from __future__ import annotations

import os

UPSKILL_FROM_RESEARCH = '''---
name: upskill-from-research
description: Become genuinely good at a subject by learning how the best in the world actually do it -- research across trades journals (edge cases), expert interviews (deep knowledge), authoritative books (foundation), and web sources; distill the durable heuristics and anti-patterns into an installable skill; promote it, use it, and self-correct on failure. Anton runs this automatically via `anton upskill --subject "..."`.
author: anton
version: 1.0.0
compatibility: [fake, pi, oi, ssh]
sources_required: true
---

# Upskill From Research

## Operational Directive

The way to become genuinely good at something is to learn how the best in the field
actually do it -- from depth, not from generic web noise. The method is research-rich
and source-disciplined:

1. **Trades journals** -- for **edge cases** (practitioners writing about the exceptions,
   failures, and field realities no overview covers).
2. **Expert interviews** -- for **deep knowledge and edge-case learning** (people who've
   done it for decades; they speak in mechanisms, not summaries).
3. **Books** -- for the **foundation** (the structural, complete treatment).
4. **Web / docs / case studies** -- for currency and specifics.

Distill these sources into an installable skill that encodes the durable heuristics --
the **do** rules, the **don't** rules, the numeric/hand thresholds -- then promote it
into this install's skill pool, use it, and when it fails, capture the failure mode back
into the skill (update the don't list) so competence compounds.

---

## Step 0 -- Competence Intake (run first, every time)

Before digging, write one paragraph: what is the core skill, what distinguishes a top
performer in it, and which of the 4 source types likely carries the most edge-case +
deep knowledge for THIS subject. This focuses the search.

## Step 1 -- Research the subject across ALL FOUR layers (not just web)

Gather at least 5 independent sources, deliberately covering all four types (skip a
type only if you name why):

1. **Trades journals & the trades press for this field** -- identify the top
   publications for the field. Look for free/online editions and Table of Contents
   previews available online. Read the Table of Contents across recent years' editions
   to map the field's real topics and edge cases, then fetch and read the relevant
   articles/features (not shorts). Capture edge cases verbatim.
2. **Top industry expert interviews** -- search for recognized top experts discussing
   the subject (video or written); pull transcripts using whatever fetch/transcription
   capability is available to you -- no fixed tool name assumed. 2-5 interviews,
   favoring ones where the expert explains workflow/decision-making rather than hype.
3. **Books** -- look up 2-4 definitive books on the subject via free and legal sources
   (e.g. Google Books previews, Internet Archive, Anna's Archive). Note their
   titles/editions/table of contents, and read the chapters that cover foundations and
   the decision frameworks. Capture the structural treatment.
4. **Universal sources** -- web/business docs, relevant trade association reports, case
   studies, run-books.

## Step 2 -- Capture sources to the vault

Store each source as a timestamped markdown note under this install's vault, at
`vault/notes/research/<subject-slug>/<date>-<subject-slug>-<TYPE>-<n>.md` where TYPE is
one of TRADES, INTERVIEW, BOOK, WEB. Each note's frontmatter records the exact source
(a URL, an ISBN, or an archive locator) and its title; the body records the key
claims/hedges with quotes and -- most important -- the edge cases and anti-patterns
that source surfaced.

## Step 3 -- Distill the durable skill

Synthesize across ALL captured sources into a single SKILL.md draft:
- the core workflow (step-by-step)
- the **do** list and the **don't** list (every anti-pattern found across sources)
- the numeric/heuristic thresholds when derivable (rules of thumb, cutoff ratios)
- **validation steps** (how to know a task is done right)
- **trigger** (when to use)
Keep it executable and specific, not a summary. If two sources contradict, record both
and pick the one with evidence/reputation, noting the conflict in the skill.

## Step 4 -- Promote and index

`anton upskill` does this automatically once the research and sandbox gates pass:
the skill is promoted into `data_dir/skills/<slug>/` and indexed into
`skill_dependencies` so it's discoverable. Never hand-edit `data_dir/skills/` directly --
only the sandbox-gated promotion path writes there.

## Step 5 -- Use, then self-correct

Use the skill on a real task. If it fails or the task is a near-miss:
- identify the failure mode (what the skill was missing -- an edge case, a bad
  instruction, a wrong assumption),
- record the failure as a lesson (`learning.record_lesson`) rather than hand-editing the
  skill file directly,
- once lessons accumulate past the consolidation threshold, `anton upskill --consolidate
  <slug>` merges and prunes them into the skill's do/don't lists in one pass.
Competence is a compounding loop, not a single installment.

## Step 6 -- Deliberate-Practice structure

The research layers give you the *map*; this step turns the map into *skill*. 100x
performance comes from how you practice, not just what you know. For the subject skill
you distill, do not stop at knowledge capture -- encode these into the skill body:

1. **Deliberate practice loop**: the skill must include (a) well-defined specific goals,
   (b) full-attention effort, (c) immediate informative feedback on each attempt, (d)
   repeated performance of the SAME task variant. A skill that teaches rules but has no
   feedback loop is a bibliography, not competence. Experience is not proof of mastery --
   capture the *mechanism* an expert uses, not their tenure.
2. **Directness**: the top of the stack is DOING the real thing, not working about it.
   The skill's core workflow should be direct (do the actual task end-to-end), with
   research/drills as adjuncts. If the skill reads like a survey, it is missing
   directness.
3. **Measurement gate**: a good skill has a measurable output metric and instructions to
   gate on it. Add a "what to measure to know it improved" line (units, a count, a
   ratio) to every distilled skill, not just "validation steps."
4. **Compounding, no silver bullet**: one research pass does not equal competence. The
   skill must be used repeatedly with feedback loops so gains compound; resist chasing a
   single "silver bullet" mechanism. Each cycle adds a don't-list entry -- that
   accumulation is the compounding.

## Step 7 -- Consolidate, do not bloat

Context bloat -- additive accumulation without holistic synthesis -- is the failure mode
of skill evolution. When you refine a skill, do not append rules endlessly: re-read the
whole skill, **merge** new entries into the existing structure, and **prune** rules
subsumed by newer/sharper ones. Prefer a folder shape when derivable thresholds exist:
SKILL.md (prose) + an evaluator script (deterministic check) + a validation protocol
(golden inputs that must pass). Never leave a numeric/threshold rule as prose that could
be a check.

## Step 8 -- Test generalization, not just the failing case

When a skill fails and you fix it, the failure may be overfitting -- the skill learned
the specific case it was distilled from, not the class. After any fix: re-run on (a) the
failing case AND (b) a different sibling input. Only if both pass does the fix
generalize; if only the original passes, distill the general rule, not the example.

## Step 9 -- Deep-work discipline inside the skill

The core workflow should be single-task, end-to-end, with no mid-task context-switching.
Encode in every distilled skill: one task per invocation; run it end-to-end in one pass;
external state consulted as explicit bounded steps, not scattered lookups.

## Anti-Patterns

- Never upskill from web articles alone -- that captures generic, aggregated,
  no-edge-case thinking. Always include trades/interview/book layers when they exist for
  the subject.
- Never use a journal without its Table of Contents -- the ToC of an issue or recent
  years gives you the real map of what practitioners of that discipline think matters.
- Never promote a skill without running it once (Step 5) -- an unused skill is a
  bibliography, not competence.
- Never write a skill without both a do list AND a don't list -- the anti-pattern list
  is what survives.
- Never hand-edit `data_dir/skills/` directly -- only the sandbox-gated promotion path
  writes there.
- Never append rules endlessly (context bloat) -- on every refine, re-read + merge +
  prune (Step 7).
- Never fix a skill for one failure and stop -- re-run on a sibling input too (Step 8).
- Never let a distilled skill scatter into multi-tasking -- one task per invocation,
  end-to-end (Step 9).

## Execution Artifact

- Research notes: `<data_dir>/vault/notes/research/<subject-slug>/`
- Distilled skill: `<data_dir>/skills/<slug>/`
- `skill_dependencies` table entry after promotion
'''

UPSKILL_FROM_EXPERIENCE = '''---
name: upskill-from-experience
description: Turn repeated failures, loops, and near-misses in Anton's own automations and skills into durable, repeatable competence -- diagnose the root cause, research and iterate with bounded attempts until success, then embed the do/don't path and resource-efficiency rules into the final skill or automation. Anton runs this when a task fails repeatedly (delta.py's scan_upskill_candidates) or when a promoted skill misses.
author: anton
version: 1.0.0
compatibility: [fake, pi, oi, ssh]
---

# Upskill From Experience -- Iterate To Embedded Competence

## Operational Directive

The fastest path to real competence at an operational task is not research alone -- it
is converting **Anton's own repeated failures and loops** into a repeatable skill that
encodes both the path to success and the avoidance of failure and wasted resources.
Every failure is tuition; the goal is to pay that tuition once and bank the lesson so
neither Anton nor the automation repeats it.

This skill is the operational twin of `upskill-from-research`: that skill distills from
external experts; this one distills from Anton's own lived practice. Run it when
something Anton runs keeps failing, looping, or costing too much.

## The Loop (run until success, then embed)

### 1. Detect the repeated failure / loop

Trigger: the same task fails at least twice, an automation exits non-zero repeatedly, a
loop burns time/API without progress, or a promoted skill misses on the same class of
input. Log the concrete evidence: task name, exit code, timestamps, what was attempted,
what resource was consumed (time, tokens, API calls, retries).

### 2. Diagnose root cause (before touching anything)

Read the actual failure output/log -- not a summary. Ask: is this a **config error**
(wrong path/flag/token), a **logic error** (wrong assumption in code), an
**environment error** (missing dependency, wrong host), or a **timing/ordering error**
(ran before its dependency)? Name the root cause in one sentence. If you can't, you are
not ready to fix -- gather one more diagnostic.

### 3. Research additional solutions (bounded)

Pull from the `upskill-from-research` method if the subject is genuinely new. For an
existing automation: look for the fix in the codebase's own history, sibling jobs that
already solved it, and skills already in `data_dir/skills/` that address the same
failure class. Cap research: at least 1 new candidate solution per failure, but never
more than about 3 diagnostic passes before attempting a fix -- research without attempts
is procrastination.

### 4. Attempt, verify, iterate (bounded retries)

Make ONE change at a time; verify with a real run. Never mark a fix done on intention --
re-run and read the exit code and output. On failure of the fix, iterate: update the
hypothesis, one more attempt. Budget the attempts (default 3 tries per root-cause
hypothesis); if you exceed the budget, escalate rather than burning resources in an
unbounded loop. Log each attempt: what changed, what happened, what it cost.

### 5. Document what worked and what did NOT work

For the successful path: the exact steps and the verification that proved it. For each
failed attempt: the anti-pattern (what looked reasonable but failed) and why it failed --
these become the DON'T list. Record resource efficiency: how many attempts it took, what
the wasted-resource pattern was, so the final skill avoids it.

### 6. Embed into the repeatable skill / automation

Update the target skill: add the DO path (the successful workflow) and the DON'T list
(every anti-pattern encountered) plus a measure line (the metric that proves success and
the resource-budget cap). Record each lesson via `learning.record_lesson` rather than
hand-editing the skill file -- `anton upskill --consolidate <slug>` merges and prunes
accumulated lessons into the skill in one pass once they cross the consolidation
threshold. Verify repeatability: run the updated skill/automation a second time to
confirm it now succeeds without the previous failure mode.

### 7. Bank the lesson (compounding)

The accumulation of banked lessons plus updated skills is what compounds -- every loop
closed once, never repeated.

## Anti-Patterns

- **Fixing the wrapper, not the cause** -- read the actual failure line, not a summary
  flag or wrapper status.
- **Two sources of truth diverging silently** -- when an automation depends on state,
  verify the SAME state the consumer uses, not a copy that can drift.
- **A scheduler that looks idle but isn't** -- check ALL scheduler/trigger layers before
  concluding "not running."
- **Unbounded retry loops** -- always cap attempts and escalate on budget exhaustion.
- **Assuming the stale value** -- "no new candidates" can mean idle, or it can mean the
  upstream capture broke days ago. Trace the full chain, not just the last hop.
- **Promoting a skill you never ran** -- a distilled skill is a bibliography until it has
  been run and verified at least once (Step 6). Never promote without a second real run.

## Execution Artifacts

- Per-failure log: attempts and costs (in-line while working)
- Vault note: `<data_dir>/vault/notes/research/<subject-slug>/` for any research pulled
  in during Step 3
- Updated skill: do/don't/measure embedded via banked lessons, consolidated, promoted
- Ledger row for the fixed automation (repeatability proof)
'''

META_LEARNING = '''---
name: meta-learning
description: The governor over all of Anton's skill acquisition -- given a task, decide whether to reuse an existing skill, learn from external research, or learn from Anton's own failures; sequence pending learning to unblock the most-blocking gap first; know when to stop researching and act; triage the skill portfolio so dormant skills are archived rather than endlessly refined; and drive proactive scanning of whatever sources this install has connected for opportunities worth pursuing, not just reacting to failures. This is the entry point `anton upskill` and Anton's automatic candidates both route through -- neither `upskill-from-research` nor `upskill-from-experience` should be invoked directly except by this skill or an explicit human command naming a subject.
author: anton
version: 1.0.0
compatibility: [fake, pi, oi, ssh]
---

# Meta-Learning

## Operational Directive

Learning is not free -- every research pass and every diagnostic loop costs real time
and real tokens. Meta-learning's job is to spend that budget where it actually helps,
never to learn something Anton already knows, and to know when to stop learning and do
the work instead. It sits above `upskill-from-research` (external expertise) and
`upskill-from-experience` (Anton's own lived practice) and decides which of the two --
if either -- a given gap actually needs.

## (a) Check the pool first -- reuse, never rebuild

Before dispatching either learning path, search the existing skill pool
(`data_dir/skills/`, indexed in `skill_dependencies`) for something that already covers
the task. A close match wins over a fresh research pass every time -- rebuilding
something Anton already knows is pure waste. Only proceed to learning when nothing in
the pool actually fits.

## (b) Decide learn-vs-do, and which learning path

If nothing in the pool fits, decide:
- **Learn from research** (`upskill-from-research`) when the gap is a genuinely new
  subject -- no local evidence exists yet, so external expertise is the only source.
- **Learn from experience** (`upskill-from-experience`) when the gap is Anton's own task
  failing repeatedly -- real failure evidence already exists locally and diagnosing it
  is faster and more grounded than external research.
Never confuse the two: researching an unrelated external subject does not fix a broken
local automation, and diagnosing one specific failure does not substitute for learning a
genuinely new domain.

## (c) Sequence to unblock the critical path

When more than one gap is pending, do not process them in arrival order by default.
Prioritize the gap blocking the most work, or blocking it the longest -- a competence gap
that has caused many repeated failures should close before a rarely-hit one, since
closing it unblocks more real work per unit of learning spent.

## (d) Know when to stop learning and act (optimal stopping)

More research is not always better. If a candidate fix or skill is already staged and
awaiting approval, do not dispatch another research pass on the same subject -- wait for
that one to resolve. If an existing skill covers the gap well enough to act now, prefer
acting over researching a marginally better version first. The bounded-attempt budgets in
both learning paths exist for the same reason: research and iteration without a stopping
rule is procrastination dressed as diligence.

## (e) Triage the skill portfolio

A skill nobody has applied in a long time is dormant, not "in need of refinement" --
periodically scan the pool for skills with no recent real-world application and archive
them rather than spending more learning budget improving something nothing uses. This
keeps the portfolio a set of skills actually in service, not an accumulating museum.

## (f) Scan proactively, not only reactively

The other four responsibilities all respond to something already breaking. Periodically
survey whatever this install actually has connected -- its own vault, plus anything
registered as an active integration (email, accounting, file storage, an allowlisted
messaging channel, or anything else wired up) -- for a genuine, worth-pursuing capability
gap, not just a task that failed. This scan is strictly read-only: observe and report,
never send, reply to, or modify anything in a connected system. Most scans should find
nothing worth acting on, and that is the correct, expected outcome, not a failure of the
scan. A finding that clears the bar becomes a candidate and goes through the exact same
research-first path as any other new subject -- it is never fabricated into a skill from
the scan alone.

## Anti-Patterns

- Never dispatch a learning pass without first checking the pool -- rebuilding a skill
  that already exists is the single most avoidable waste in this system.
- Never let a proactive scan take any action beyond reading and reporting -- it observes
  connected sources, it does not act on them.
- Never route a repeated local failure through external research, or a genuinely new
  subject through experience-diagnosis -- they need different evidence.
- Never let two research passes run on the same subject at once because the first one's
  outcome wasn't checked first.
- Never keep "improving" a skill nobody uses -- triage it out instead.
- Never let learning become the work -- optimal stopping means acting once the gap is
  closed well enough, not chasing a perfect skill before doing anything real.

## Execution Artifact

- Routing decision + reason (logged wherever the caller records it -- the ledger via
  the dispatched learning path, or the CLI's own output for an explicit `anton upskill`)
- Triage report: which skills stayed active, which were archived to
  `data_dir/skills-archive/`
'''


def seed_meta_skills(data_dir: str, *, force: bool = False) -> list[str]:
    """Write all three standard skills into data_dir/skills/, idempotently
    (skip a skill that already exists unless force=True, so a re-run doesn't
    clobber a user's own edits to the standard skills)."""
    written = []
    for slug, body in (
        ("upskill-from-research", UPSKILL_FROM_RESEARCH),
        ("upskill-from-experience", UPSKILL_FROM_EXPERIENCE),
        ("meta-learning", META_LEARNING),
    ):
        skill_dir = os.path.join(data_dir, "skills", slug)
        skill_path = os.path.join(skill_dir, "SKILL.md")
        if os.path.exists(skill_path) and not force:
            continue
        os.makedirs(skill_dir, exist_ok=True)
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(body)
        written.append(slug)
    return written
