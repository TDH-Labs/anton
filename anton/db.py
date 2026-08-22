"""isolation.db — agent-harness state. Tenant-ready: org_id on every table (Q4)."""
from __future__ import annotations

import sqlite3
import os

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default', room TEXT, started TEXT, state_ref TEXT
);
CREATE TABLE IF NOT EXISTS initiatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    slug TEXT, source TEXT, risk TEXT, score REAL, status TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    nonce TEXT UNIQUE, action TEXT, amount TEXT, recipient TEXT, status TEXT, hmac TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    scope TEXT, kind TEXT, cap REAL, used REAL DEFAULT 0, period_start TEXT
);
CREATE TABLE IF NOT EXISTS metering (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    ts TEXT, provider TEXT, model TEXT, tokens_in INTEGER, tokens_out INTEGER,
    cost_usd REAL, job_id TEXT
);
CREATE TABLE IF NOT EXISTS seen_external_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    source TEXT, item_hash TEXT, ts TEXT, UNIQUE(source, item_hash)
);
CREATE TABLE IF NOT EXISTS skill_dependencies (
    skill_slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    prerequisite_skill TEXT, target_capability TEXT, mastery_score REAL, last_validated TEXT
);
CREATE TABLE IF NOT EXISTS confidence_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    prediction REAL, outcome REAL, ts TEXT
);
CREATE TABLE IF NOT EXISTS sandbox_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    slug TEXT, stage TEXT, ok INTEGER, detail TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS playbooks (
    slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    method TEXT, source_initiative TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS upskill_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    slug TEXT, subject TEXT, stage TEXT, attempt INTEGER, ok INTEGER, detail TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS skill_lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    skill_slug TEXT, kind TEXT, text TEXT, source TEXT, consumed_at TEXT, ts TEXT
);
"""


def init_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
