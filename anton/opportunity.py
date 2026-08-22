"""Proactive opportunity scanning: the one piece of the three-skill learning
system that isn't reactive. delta.py's candidates and meta_learning.py's
routing only ever fire in response to something that already failed --
this module looks for things worth upskilling toward before anything
breaks, by surveying whatever this install actually has connected (its own
vault/second-brain, plus anything registered in mcp_servers -- email, QBO,
Drive, an allowlisted messaging channel, whatever the operator has wired up)
rather than any one hardcoded source. What's actually connected varies
install to install; this module never assumes a fixed source list.

A found opportunity becomes an `initiatives` candidate the same way a
delta-detected failure does, and flows through the exact same pipeline from
there: meta_learning.route() (an opportunity is, by construction, a subject
nobody has tried before, so decide() resolves it to learn_from_research)
-> upskill.run_upskill() -> the same sandbox gate and governor promotion
gate as everything else. This module only ever produces candidates; it
never authors or promotes a skill itself.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import os
import sqlite3
from typing import Optional

import yaml

from .routes import select_route
from .upskill import _dispatch, slugify
from .vault import emit_candidate

_MCP_SERVERS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS mcp_servers ("
    " id TEXT PRIMARY KEY, org_id TEXT DEFAULT 'default',"
    " name TEXT, what TEXT, permissions_json TEXT DEFAULT '[]',"
    " status TEXT DEFAULT 'active', room TEXT, ts TEXT)"
)


def list_connected_sources(data_dir: str) -> list[dict]:
    """Whatever this install actually has wired up. The vault (Anton's own
    second brain) is always available and always included; everything else
    comes from mcp_servers (Add-ons in the Ops Center UI) -- email, QBO,
    Drive, an allowlisted messaging channel, or anything else an operator
    has connected. Defensive CREATE TABLE: this runs from the scheduler
    loop, which may start before the dashboard process has ever run
    ops_schema.ensure_ops_schema()."""
    sources = [{"name": "vault", "what": "Anton's own second brain (notes, graph, digests)"}]
    db_path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(db_path):
        return sources
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        conn.execute(_MCP_SERVERS_SCHEMA)
        rows = conn.execute(
            "SELECT name, what FROM mcp_servers WHERE status='active'").fetchall()
    finally:
        conn.close()
    sources.extend({"name": name, "what": what} for name, what in rows)
    return sources


def build_scan_prompt(sources: list[dict], opportunities_dir: str) -> str:
    source_lines = "\n".join(f"- {s['name']}: {s['what']}" for s in sources)
    return f"""Survey the following sources this install has connected, looking for
genuine business opportunities worth actively upskilling toward -- not just reacting to
something that broke:

{source_lines}

For each source, look for recurring requests, emerging patterns, or explicit asks that
suggest a real, valuable capability gap -- something worth building real competence in,
not routine noise. Be selective: most days will surface nothing worth acting on, and
that is the correct, expected outcome.

READ-ONLY: only observe and report. Do not send anything, reply to anything, modify any
connected system, or take any action beyond reading and writing opportunity notes below.

For each genuine opportunity found, write one markdown file under {opportunities_dir}/,
named <YYYY-MM-DD>-<subject-slug>-<n>.md, with this exact frontmatter:
---
type: opportunity
subject: <a short slug for the opportunity>
source: <which connected source surfaced it>
worth: <low|medium|high -- your honest assessment of whether this is worth pursuing>
---

And a body with:
## What was observed
## Why this is worth pursuing
## What competence would need to be built

If you find nothing worth pursuing, write nothing -- an empty result is a correct,
expected outcome, not a failure."""


@dataclasses.dataclass
class Opportunity:
    subject: str
    source: str
    worth: str
    path: str


def verify_opportunities(vault_dir: str) -> list[Opportunity]:
    """Independently parse what actually got written -- same discipline as
    upskill.py's verify_research: never trust the dispatched agent's own
    claim of what it found."""
    opp_dir = os.path.join(vault_dir, "notes", "opportunities")
    found = []
    if not os.path.isdir(opp_dir):
        return found
    for fn in sorted(os.listdir(opp_dir)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(opp_dir, fn)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        try:
            fm = yaml.safe_load(text[3:end])
        except yaml.YAMLError:
            continue
        if not isinstance(fm, dict) or fm.get("type") != "opportunity":
            continue
        worth = str(fm.get("worth", "")).lower()
        if worth not in ("low", "medium", "high"):
            continue
        found.append(Opportunity(subject=fm.get("subject", ""), source=fm.get("source", ""),
                                 worth=worth, path=path))
    return found


def scan_for_opportunities(engine, *, min_worth: str = "high", model: Optional[str] = None,
                           provider: Optional[str] = None, timeout_s: Optional[float] = None) -> list[Opportunity]:
    """Dispatch the scan, verify what was actually written, and emit an
    initiatives candidate (opportunity-<slug>) for each opportunity meeting
    min_worth -- meta_learning.route() picks these up as fresh subjects, the
    same way it picks up an explicit `anton upskill --subject`."""
    order = {"low": 0, "medium": 1, "high": 2}
    route_ = select_route(prefer="cloud")
    model = model or route_.model
    provider = provider or route_.provider
    vault_dir = os.path.join(engine.data_dir, "vault")
    opp_dir = os.path.join(vault_dir, "notes", "opportunities")
    os.makedirs(opp_dir, exist_ok=True)

    sources = list_connected_sources(engine.data_dir)
    prompt = build_scan_prompt(sources, opp_dir)
    _dispatch(engine, task_label="opportunity:scan", prompt=prompt, model=model,
             provider=provider, timeout_s=timeout_s, slug="opportunity-scan", stage="scan")

    found = verify_opportunities(vault_dir)
    qualifying = [o for o in found if order.get(o.worth, -1) >= order.get(min_worth, 2)]
    db_path = os.path.join(engine.data_dir, "isolation.db")
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        for o in qualifying:
            slug = f"opportunity-{slugify(o.subject)}"
            emit_candidate(conn, slug, f"scan:{o.source}:worth={o.worth}")
    finally:
        conn.close()
    return qualifying
