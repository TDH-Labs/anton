"""Markdown digest — read-only projection over ledger + registries + canary (§4.2)."""
from __future__ import annotations

import datetime as dt
import os
import tempfile

from .canary import compute_tripwires
from .vault_db import init_vault_db


def _ts_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_digest(engine, vault_dir: str, config: dict,
                 heartbeat_path: str | None = None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    now_iso = _ts_now()
    ledger = engine.ledger
    rows = ledger.read()
    day_ago = (now - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")

    completed = [r for r in rows if r["ts"] >= day_ago and r["task"] != "fleet-canary"]
    tripwires = compute_tripwires(engine.jobs, ledger, now=now)

    # LLM usage (cloud rows only, last 24h)
    usage = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "cloud_runs": 0}
    for r in rows:
        if r["ts"] < day_ago or r.get("token_accounting") != "cloud":
            continue
        usage["tokens_in"] += r.get("tokens_in") or 0
        usage["tokens_out"] += r.get("tokens_out") or 0
        usage["cost_usd"] += r.get("cost_usd") or 0.0
        usage["cloud_runs"] += 1

    running = "—"
    if heartbeat_path and os.path.exists(heartbeat_path):
        age_s = time_since(heartbeat_path)
        running = "yes (heartbeat %ds ago)" % age_s if age_s < 300 else "stale"

    # pipeline ahead: pending initiatives
    initiatives = []
    db_path = os.path.join(os.path.dirname(vault_dir), "isolation.db")
    if os.path.exists(db_path):
        import sqlite3
        try:
            conn = sqlite3.connect(db_path)
            initiatives = conn.execute(
                "SELECT slug, source, risk, score FROM initiatives WHERE status='pending'").fetchall()
            conn.close()
        except sqlite3.Error:
            pass

    status = "PASS" if not tripwires else "ATTENTION"

    lines = [
        "# Control Plane Digest",
        "",
        f"Generated: {now_iso}  ·  Status: **{status}**",
        "",
        "## 1. Fleet status (canary)",
        "",
    ]
    if tripwires:
        lines += [f"- ⚠ TRIPWIRE **{t['job_id']}** last_seen={t.get('last_seen')} "
                  f"expected={t['expected_min']}min" for t in tripwires]
    else:
        lines.append("- All scheduled jobs within cadence.")
    lines += ["", "## 2. Completed (last 24h)", "",
              "| ts | task | rc | model | provider | ms |", "|---|---|---|---|---|---|"]
    for r in completed[-15:]:
        lines.append(f"| {r['ts']} | {r['task']} | {r['exit']} | {r.get('model') or ''} | "
                     f"{r.get('provider') or ''} | {r.get('duration_ms') or ''} |")
    lines += ["", f"## 3. Running now: {running}", "",
              "## 4. Pipeline ahead (pending initiatives)", ""]
    if initiatives:
        lines += [f"- {slug} (source={source}, risk={risk})" for slug, source, risk, _ in initiatives]
    else:
        lines.append("- (none)")
    lines += ["", "## 5. LLM usage (24h, cloud)", "",
              f"- cloud runs: {usage['cloud_runs']}",
              f"- tokens: {usage['tokens_in']} in / {usage['tokens_out']} out",
              f"- cost: ${usage['cost_usd']:.4f}", "",
              "## 6. Gate & budget posture", ""]
    b = config.get("budgets", {})
    lines += [f"- per-job tokens max: {b.get('tokens_max_per_job')}",
              f"- per-job cost max: ${b.get('cost_usd_max_per_job')}",
              f"- daily tokens max: {b.get('daily_tokens_max')}",
              f"- daily cost max: ${b.get('daily_cost_usd_max')}",
              "- breaches this window: " +
              (", ".join(r['task'] for r in completed if 'budget-breach' in r.get('flags', '')) or "none"),
              "", "## 7. Registry", "",
              f"- jobs defined: {len(engine.jobs)}",
              f"- ledger rows: {len(rows)}"]
    return "\n".join(lines) + "\n"


def time_since(path: str) -> int:
    return int((dt.datetime.now(dt.timezone.utc).timestamp() -
                os.path.getmtime(path)))


def write_digest(path: str, content: str, vault_dir: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)
    conn = init_vault_db(os.path.join(vault_dir, "vault.db"))
    conn.execute(
        "INSERT INTO digest_history(path, generated_at, summary) VALUES(?,?,?)",
        (os.path.basename(path), _ts_now(), content.splitlines()[2] if len(content.splitlines()) > 2 else ""),
    )
    conn.commit()
    conn.close()
    return path
