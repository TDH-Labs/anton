"""Adversarial QA sandbox gate (R3/R6): py_compile + golden test -> promote or log."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
import subprocess


def _log(db_path: str, slug: str, stage: str, ok: bool, detail: str) -> None:
    if not db_path:
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS sandbox_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slug TEXT, stage TEXT, ok INTEGER, detail TEXT,
        ts TEXT DEFAULT (datetime('now')))""")
    conn.execute("INSERT INTO sandbox_log(slug, stage, ok, detail) VALUES(?,?,?,?)",
                 (slug, stage, 1 if ok else 0, detail[:500]))
    conn.commit()
    conn.close()


def run_sandbox_gate(script_path: str, golden_payload: str | None = None,
                     db_path: str | None = None, slug: str | None = None) -> bool:
    slug = slug or os.path.splitext(os.path.basename(script_path))[0]
    # 1) syntax gate
    proc = subprocess.run(["python3", "-m", "py_compile", script_path],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        _log(db_path or "", slug, "py_compile", False, proc.stderr)
        return False
    # 2) golden test gate (optional)
    if golden_payload is not None:
        proc = subprocess.run(["python3", script_path, golden_payload],
                              capture_output=True, text=True, timeout=30)
        ok = proc.returncode == 0
        _log(db_path or "", slug, "golden_test", ok, (proc.stderr or proc.stdout or "")[:500])
        return ok
    return True


def promote(script_path: str, skills_dir: str, slug: str | None = None) -> str:
    slug = slug or os.path.splitext(os.path.basename(script_path))[0]
    target_dir = os.path.join(skills_dir, slug)
    os.makedirs(target_dir, exist_ok=True)
    dst = os.path.join(target_dir, os.path.basename(script_path))
    shutil.copy2(script_path, dst)
    return dst
