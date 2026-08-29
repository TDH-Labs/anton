"""Additive schema for the Anton Studio Ops Center contract.

Every change here is additive: new nullable columns on existing tables (never
a rename or drop) and new tables for concepts the original schema had no
room for. `initiatives` (delta.py's candidate-remediation table) and the
money/outbound-gate columns on `approvals` are untouched — this module only
adds alongside them, so `db.py`'s SCHEMA and every existing table stay
exactly as they were for callers that only know the old columns.
"""
from __future__ import annotations

import sqlite3

# (table, column, column_def) — applied only when the column is missing.
_APPROVALS_COLUMNS = [
    ("approvals", "title", "TEXT"),
    ("approvals", "sub", "TEXT"),
    ("approvals", "reason", "TEXT"),
    ("approvals", "evidence", "TEXT"),
    ("approvals", "changes_json", "TEXT"),
    ("approvals", "kind", "TEXT"),
]

_NEW_TABLES = """
CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    name TEXT NOT NULL, plain TEXT,
    trigger_kind TEXT, trigger_display TEXT, trigger_expr TEXT,
    needs_signoff INTEGER DEFAULT 1, author TEXT DEFAULT 'agent',
    last_run TEXT, state TEXT DEFAULT 'awaiting_approval', risk TEXT DEFAULT 'low',
    nodes_json TEXT DEFAULT '[]', links_json TEXT DEFAULT '[]',
    source_initiative_id INTEGER, ts TEXT
);
CREATE TABLE IF NOT EXISTS systems (
    id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    name TEXT NOT NULL, sub TEXT, state TEXT,
    last_check TEXT, health TEXT DEFAULT 'ok', self_managed INTEGER DEFAULT 0, ts TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    title TEXT, summary TEXT, status TEXT DEFAULT 'open',
    window_start TEXT, window_end TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS incident_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT,
    time TEXT, text TEXT, actor TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS wizard_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    picks_json TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS mcp_servers (
    id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    name TEXT, what TEXT, permissions_json TEXT DEFAULT '[]',
    status TEXT DEFAULT 'active', room TEXT, ts TEXT
);
"""

_PLAYBOOKS_COLUMNS = [
    ("playbooks", "title", "TEXT"),
    ("playbooks", "body", "TEXT"),
    ("playbooks", "kind", "TEXT DEFAULT 'decision'"),
    ("playbooks", "triggered_by", "TEXT"),
    ("playbooks", "usage_count", "INTEGER DEFAULT 0"),
    ("playbooks", "vault_path", "TEXT"),
]

# notes lives in vault.db, not isolation.db (vault_db.py's SCHEMA).
_NOTES_COLUMNS = [
    ("notes", "author", "TEXT DEFAULT 'agent'"),
    ("notes", "kind", "TEXT"),
    ("notes", "provenance", "TEXT"),
]


def _add_missing_columns(conn: sqlite3.Connection, columns: list[tuple[str, str, str]]) -> None:
    for table, column, coldef in columns:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")
            except sqlite3.OperationalError as exc:
                # open_isolation_db() re-runs this check-then-ALTER on every
                # request with no external locking, so two connections can
                # both see the column missing and both attempt to add it —
                # the loser hits this, not a real failure: the column exists
                # either way.
                if "duplicate column name" not in str(exc):
                    raise


def ensure_ops_schema(isolation_db_conn: sqlite3.Connection) -> None:
    """Apply the Ops Center's additive schema to an open isolation.db
    connection: approvals' UI-card columns, playbooks' learning-entry
    columns (db.py's SCHEMA — both tables live in isolation.db, not
    vault.db), and the new automations/systems/incidents/wizard/mcp tables."""
    _add_missing_columns(isolation_db_conn, _APPROVALS_COLUMNS)
    _add_missing_columns(isolation_db_conn, _PLAYBOOKS_COLUMNS)
    isolation_db_conn.executescript(_NEW_TABLES)
    # running_jobs / job_state: live dispatch state and operator steering,
    # owned by job_state.py because the scheduler process writes them and the
    # dashboard process reads them.
    from .job_state import ensure_schema as ensure_job_state_schema
    ensure_job_state_schema(isolation_db_conn)
    # chat_sessions / chat_messages: durable Ask Anton history, owned by
    # chat.py.
    from .chat import ensure_schema as ensure_chat_schema
    ensure_chat_schema(isolation_db_conn)
    isolation_db_conn.commit()


def ensure_vault_ops_schema(vault_db_conn: sqlite3.Connection) -> None:
    """Apply the Ops Center's additive schema to an open vault.db connection."""
    _add_missing_columns(vault_db_conn, _NOTES_COLUMNS)
    vault_db_conn.commit()
