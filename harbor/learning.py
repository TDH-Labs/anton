"""Self-learning: Vercel-contract skill authoring + playbook extraction (§8)."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3

SKILL_TEMPLATE = """---
name: {slug}
description: {description}
author: Hyperagent-Autonomous-Builder
version: 1.0.0
compatibility: [goose, agent-zero, pi, cursor]
room_scope: [strategy, thought_partner, entrepreneurship]
---

# {title}

## Operational Directive
When the active context requires [{condition}], execute this protocol.

## Algorithmic Procedure
1. {step_1}
2. {step_2}
3. {step_3}

## Execution Artifact
Refer to accompanying script: `scripts/{slug}_evaluator.py`
"""

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
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(SKILL_TEMPLATE.format(slug=slug, description=description, title=title,
                                      condition=condition, step_1=steps[0],
                                      step_2=steps[1], step_3=steps[2]))
    ev_path = os.path.join(out_dir, "scripts", f"{slug}_evaluator.py")
    with open(ev_path, "w", encoding="utf-8") as f:
        f.write(EVALUATOR_STUB.replace("__SLUG__", slug))
    return slug


def extract_playbook(db_path: str, *, task: str, exit_code: int, flags: str,
                     method: str) -> None:
    """ERL/ICT-style: after an initiative, persist the reusable method (not just the fact)."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS playbooks (
        slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
        method TEXT, source_initiative TEXT, ts TEXT)""")
    slug = task.strip().lower().replace(" ", "-")
    conn.execute("INSERT OR REPLACE INTO playbooks(slug, method, source_initiative, ts) "
                 "VALUES(?,?,?,?)",
                 (slug, method, f"{task}:{flags}", dt.datetime.now(dt.timezone.utc).isoformat()))
    conn.commit()
    conn.close()
