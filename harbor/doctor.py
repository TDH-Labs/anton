"""harbor doctor — read-only admin diagnostics (mirrors interpreter doctor's role)."""
from __future__ import annotations

import os
import sqlite3
import sys

from .canary import compute_tripwires
from .config import load_config


def run_doctor(data_dir: str, executor_name: str = "fake") -> tuple[list[str], bool]:
    lines: list[str] = []
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        lines.append(f"{'✓' if passed else '✗'} {label}" + (f" — {detail}" if detail else ""))

    check("python", sys.version_info >= (3, 11), f"{sys.version.split()[0]}")

    cfg = load_config(os.path.join(data_dir, "..", "config.yaml"))

    check("data dir", os.path.isdir(data_dir), data_dir)
    jobs_path = os.path.join(data_dir, "jobs.yaml")
    check("jobs.yaml", os.path.exists(jobs_path))
    jobs = []
    if os.path.exists(jobs_path):
        from .jobs import load_jobs
        try:
            jobs = load_jobs(jobs_path)
            check("jobs parse", True, f"{len(jobs)} job(s)")
        except Exception as e:  # noqa: BLE001
            check("jobs parse", False, str(e))

    ledger_path = os.path.join(data_dir, "runs.jsonl")
    rows = 0
    if os.path.exists(ledger_path):
        from .ledger import Ledger
        rows = len(Ledger(ledger_path).read())
    lines.append(f"ledger: {rows} row(s)" + ("" if rows else " (none yet — first run creates it)"))

    for name in ("isolation.db", os.path.join("vault", "vault.db")):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                res = conn.execute("PRAGMA quick_check").fetchone()
                conn.close()
                check(f"db {name}", res and res[0] == "ok", str(res[0]) if res else "?")
            except sqlite3.Error as e:
                check(f"db {name}", False, str(e))
        else:
            check(f"db {name}", False, "missing")

    vault_index = os.path.join(data_dir, "vault", "index.md")
    check("vault index", os.path.exists(vault_index))

    from .executor import OIExecutor, PiExecutor
    for exe in (PiExecutor(), OIExecutor()):
        check(f"executor {type(exe).__name__}",
              exe.available() or type(exe).__name__ == "FakeExecutor",
              "binary found" if exe.available() else "binary not installed (use --executor fake)")

    from .ledger import Ledger
    if jobs:
        trips = compute_tripwires(jobs, Ledger(ledger_path))
        mark = "within cadence" if not trips else f"{len(trips)} tripwire(s) (jobs not yet run — operational, not install)"
        lines.append(f"canary: {mark}")

    b = cfg.get("budgets", {})
    lines.append(f"budgets: {b}")
    return lines, ok
