"""vault.db — the brain's queryable layer, co-located with the markdown vault.

Markdown is the human-facing artifact; vault.db is the index/graph/state. Both are
written and synced together.
"""
from __future__ import annotations

import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    path TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    title TEXT, hash TEXT, mtime TEXT, toc TEXT
);
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    from_note TEXT, to_note TEXT, kind TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    name TEXT, mentions INTEGER DEFAULT 0, first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS mocs (
    slug TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default', title TEXT, member_notes TEXT
);
CREATE TABLE IF NOT EXISTS seen_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    source TEXT, item_hash TEXT, ts TEXT, UNIQUE(source, item_hash)
);
CREATE TABLE IF NOT EXISTS digest_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    path TEXT, generated_at TEXT, summary TEXT
);
CREATE TABLE IF NOT EXISTS embeddings (
    note_id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',
    model TEXT, vector BLOB, dim INTEGER
);
"""


def init_vault_db(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
