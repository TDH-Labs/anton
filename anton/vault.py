"""Vault module: provision, delta sensor, graph synthesis. Markdown + vault.db (§4.3, §6)."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from typing import List, Tuple

from .vault_db import init_vault_db

INDEX_TEMPLATE = """# Index

Second brain vault for this anton install. Notes live here as markdown;
`vault.db` co-located next to `vault/` holds the queryable index + graph.

## Maps of Content
- [[mocs/operations]]
- [[mocs/strategy]]
"""

MOC_TEMPLATE = """---
title: {title}
type: moc
---
# {title}

Member notes:
"""

NOTE_TEMPLATE = """---
type: note
tags: []
---
# {title}

(empty)
"""

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


def provision_vault(vault_dir: str) -> str:
    os.makedirs(vault_dir, exist_ok=True)
    for sub in ("notes", "mocs", "templates", "digests"):
        os.makedirs(os.path.join(vault_dir, sub), exist_ok=True)
    if not os.path.exists(os.path.join(vault_dir, "index.md")):
        with open(os.path.join(vault_dir, "index.md"), "w", encoding="utf-8") as f:
            f.write(INDEX_TEMPLATE)
    for moc in ("operations", "strategy"):
        p = os.path.join(vault_dir, "mocs", f"{moc}.md")
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8") as f:
                f.write(MOC_TEMPLATE.format(title=moc))
    init_vault_db(os.path.join(vault_dir, "vault.db"))
    # pre-index our own scaffolding so the first real scan reports only user changes
    scan_vault(vault_dir)
    return vault_dir


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _walk_md(vault_dir: str) -> List[str]:
    out = []
    for root, _dirs, files in os.walk(vault_dir):
        for name in files:
            if name.endswith(".md"):
                out.append(os.path.join(root, name))
    return out


def scan_vault(vault_dir: str) -> Tuple[List[dict], List[dict]]:
    """Return (new_or_modified, removed) note descriptors vs the vault.db index."""
    conn = init_vault_db(os.path.join(vault_dir, "vault.db"))
    try:
        conn.execute("DELETE FROM seen_items")
        new_mod = []
        removed = []
        known = {r[0] for r in conn.execute("SELECT path FROM notes")}
        seen = set()
        for p in _walk_md(vault_dir):
            rel = os.path.relpath(p, vault_dir)
            seen.add(rel)
            with open(p, encoding="utf-8") as f:
                text = f.read()
            h = _hash(text)
            conn.execute(
                "INSERT OR REPLACE INTO seen_items(source, item_hash, ts) VALUES(?,?,?)",
                ("vault", h, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(p), tz=dt.timezone.utc).isoformat()
            row = conn.execute("SELECT hash FROM notes WHERE path=?", (rel,)).fetchone()
            if row is None or row[0] != h:
                title = os.path.splitext(os.path.basename(rel))[0]
                conn.execute(
                    "INSERT OR REPLACE INTO notes(path, title, hash, mtime) VALUES(?,?,?,?)",
                    (rel, title, h, mtime),
                )
                new_mod.append({"path": rel, "hash": h[:12], "mtime": mtime})
        for rel in known - seen:
            conn.execute("DELETE FROM notes WHERE path=?", (rel,))
            removed.append({"path": rel})
        conn.commit()
    finally:
        conn.close()
    return new_mod, removed


def find_orphans(vault_dir: str) -> List[str]:
    """Notes with zero incoming or outgoing wikilinks."""
    conn = init_vault_db(os.path.join(vault_dir, "vault.db"))
    try:
        note_paths = [r[0] for r in conn.execute("SELECT path FROM notes")]
    finally:
        conn.close()
    links: dict[str, set] = {}
    for rel in note_paths:
        p = os.path.join(vault_dir, rel)
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        targets = {m.strip() for m in WIKILINK.findall(text)}
        links[rel] = targets
    incoming: dict[str, int] = {}
    for rel, targets in links.items():
        for t in targets:
            incoming[t] = incoming.get(t, 0) + 1
    orphans = []
    for rel in note_paths:
        out = len(links.get(rel, set()))
        inn = incoming.get(os.path.splitext(os.path.basename(rel))[0], 0) + \
              incoming.get(rel, 0)
        if out == 0 and inn == 0:
            orphans.append(rel)
    return orphans


def emit_candidate(db_conn, slug: str, source: str, risk: str = "low") -> None:
    db_conn.execute(
        "INSERT INTO initiatives(slug, source, risk, status, ts) VALUES(?,?,?,?,?)",
        (slug, source, risk, "pending",
         dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    db_conn.commit()

