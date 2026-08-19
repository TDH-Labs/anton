"""Adversarial QA sandbox gate (R3/R6): py_compile + golden test -> promote or log."""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile


def _log(db_path: str, slug: str, stage: str, ok: bool, detail: str) -> None:
    if not db_path:
        return
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS sandbox_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT, stage TEXT, ok INTEGER, detail TEXT,
            ts TEXT DEFAULT (datetime('now')))""")
        conn.execute("INSERT INTO sandbox_log(slug, stage, ok, detail) VALUES(?,?,?,?)",
                     (slug, stage, 1 if ok else 0, detail[:500]))
        conn.commit()


def run_sandbox_gate(script_path: str, golden_payload: str | None = None,
                     db_path: str | None = None, slug: str | None = None) -> bool:
    slug = slug or os.path.splitext(os.path.basename(script_path))[0]
    clean_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with tempfile.TemporaryDirectory(prefix="agent_sandbox_") as tmpdir:
        script_copy = os.path.join(tmpdir, os.path.basename(script_path))
        shutil.copy2(script_path, script_copy)

        # 1) syntax gate
        proc = subprocess.run(["python3", "-m", "py_compile", script_copy],
                              capture_output=True, text=True, cwd=tmpdir, env=clean_env)
        if proc.returncode != 0:
            _log(db_path or "", slug, "py_compile", False, proc.stderr)
            return False

        # 2) golden test gate (optional)
        if golden_payload is not None:
            try:
                proc = subprocess.run(["python3", script_copy, golden_payload],
                                      capture_output=True, text=True, timeout=30,
                                      cwd=tmpdir, env=clean_env)
                ok = proc.returncode == 0
                _log(db_path or "", slug, "golden_test", ok, (proc.stderr or proc.stdout or "")[:500])
                return ok
            except subprocess.TimeoutExpired:
                _log(db_path or "", slug, "golden_test", False, "timeout")
                return False
        return True


def promote(script_path: str, skills_dir: str, slug: str | None = None) -> str:
    raw_slug = slug or os.path.splitext(os.path.basename(script_path))[0]
    if ".." in raw_slug or "/" in raw_slug or "\\" in raw_slug:
        raise ValueError(f"Path traversal detected in slug: {raw_slug!r}")
    safe_slug = re.sub(r"[^a-zA-Z0-9_\-]", "", raw_slug)
    if not safe_slug:
        raise ValueError("Invalid skill slug")
    target_dir = os.path.abspath(os.path.join(skills_dir, safe_slug))
    abs_skills = os.path.abspath(skills_dir)
    if not target_dir.startswith(abs_skills + os.sep) and target_dir != abs_skills:
        raise ValueError(f"Path traversal detected in slug: {raw_slug!r}")
    os.makedirs(target_dir, exist_ok=True)
    dst = os.path.join(target_dir, os.path.basename(script_path))
    shutil.copy2(script_path, dst)
    return dst

