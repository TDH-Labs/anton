"""Self-learning: Vercel-contract skill authoring + playbook extraction (§8)."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import yaml

EVALUATOR_STUB = '''#!/usr/bin/env python3
"""Evaluator for the __SLUG__ decision rule. Golden-testable (exit 0 on known-good)."""
import sys


def evaluate(input_value: float) -> float:
    # TODO: encode the extracted decision rule as a deterministic threshold.
    return input_value


if __name__ == "__main__":
    payload = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    print(f"{{decision: {{evaluate(payload)}}}}")
'''


def author_skill(*, title: str, description: str, condition: str,
                 steps: tuple[str, str, str], out_dir: str) -> str:
    slug = title.lower().strip().replace(" ", "-").replace("_", "-")
    os.makedirs(os.path.join(out_dir, "scripts"), exist_ok=True)
    skill_path = os.path.join(out_dir, "SKILL.md")

    fm_dict = {
        "name": slug,
        "description": description,
        "author": "anton-autonomous",
        "version": "1.0.0",
        "compatibility": ["fake", "pi", "oi", "ssh"],
    }
    fm_str = yaml.safe_dump(fm_dict, sort_keys=False).strip()

    body = f"""---
{fm_str}
---

# {title}

## Operational Directive
When the active context requires [{condition}], execute this protocol.

## Algorithmic Procedure
1. {steps[0]}
2. {steps[1]}
3. {steps[2]}

## Execution Artifact
Refer to accompanying script: `scripts/{slug}_evaluator.py`
"""
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(body)
    ev_path = os.path.join(out_dir, "scripts", f"{slug}_evaluator.py")
    with open(ev_path, "w", encoding="utf-8") as f:
        f.write(EVALUATOR_STUB.replace("__SLUG__", slug))
    return slug


def extract_playbook(db_path: str, *, task: str, exit_code: int, flags: str,
                     method: str) -> None:
    """ERL/ICT-style: after an initiative, persist the reusable method (not just the fact)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS playbooks (
            slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
            method TEXT, source_initiative TEXT, ts TEXT)""")
        slug = task.strip().lower().replace(" ", "-")
        conn.execute("INSERT OR REPLACE INTO playbooks(slug, method, source_initiative, ts) "
                     "VALUES(?,?,?,?)",
                     (slug, method, f"{task}:{flags}", dt.datetime.now(dt.timezone.utc).isoformat()))
        conn.commit()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def index_skills(data_dir: str) -> int:
    """Index every skill under data_dir/skills into skill_dependencies (db.py's
    SCHEMA). Public so both cli.py's `anton skills --index` and setup.py's
    fresh-install seeding (upskill.py's two standard meta-skills) can call the
    same logic instead of setup.py shelling out to the CLI."""
    skills_dir = os.path.join(data_dir, "skills")
    if not os.path.isdir(skills_dir):
        return 0
    conn = sqlite3.connect(os.path.join(data_dir, "isolation.db"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS skill_dependencies ("
        " skill_slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',"
        " prerequisite_skill TEXT, target_capability TEXT, mastery_score REAL,"
        " last_validated TEXT)")
    count = 0
    now = _now_iso()
    for slug in sorted(os.listdir(skills_dir)):
        skill_dir = os.path.join(skills_dir, slug)
        if not os.path.isdir(skill_dir):
            continue
        sk = os.path.join(skill_dir, "SKILL.md")
        has_script = any(fn.endswith(".py") for fn in os.listdir(skill_dir))
        if not os.path.exists(sk) and not has_script:
            continue
        desc = ""
        if os.path.exists(sk):
            with open(sk, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip(chr(34)).strip(chr(39))
                        break
        conn.execute("INSERT OR REPLACE INTO skill_dependencies"
                     "(skill_slug, target_capability, last_validated) VALUES(?,?,?)",
                     (slug, desc, now))
        count += 1
    conn.commit()
    conn.close()
    return count


def record_lesson(db_path: str, skill_slug: str, kind: str, text: str, source: str) -> None:
    """A failure of the upskilling process itself, or of a skill it produced,
    banked as an unconsumed lesson (skill_lessons, db.py's SCHEMA). Consolidated
    in batches by upskill.py's consolidate_skill(), not appended into the skill
    body directly -- see learn-from-edge-thinker's own Step 7 (merge + prune,
    never append-forever)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.execute(
            "INSERT INTO skill_lessons(skill_slug, kind, text, source, ts) VALUES(?,?,?,?,?)",
            (skill_slug, kind, text, source, _now_iso()))
        conn.commit()


def unconsumed_lessons(db_path: str, skill_slug: str) -> list[dict]:
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        rows = conn.execute(
            "SELECT id, kind, text, source, ts FROM skill_lessons "
            "WHERE skill_slug=? AND consumed_at IS NULL ORDER BY id", (skill_slug,)).fetchall()
    return [{"id": r[0], "kind": r[1], "text": r[2], "source": r[3], "ts": r[4]} for r in rows]


def mark_lessons_consumed(db_path: str, lesson_ids: list[int]) -> None:
    if not lesson_ids:
        return
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        now = _now_iso()
        conn.executemany(
            "UPDATE skill_lessons SET consumed_at=? WHERE id=?",
            [(now, lid) for lid in lesson_ids])
        conn.commit()
