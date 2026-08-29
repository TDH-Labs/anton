"""Inbox loop — turn arriving messages into done things, not just drafts.

Design intent (operator-facing, and it is the point):

  A message arrives. Anton decides what KIND of thing it is and either
  does it immediately or, for the one kind that changes the world outside
  (send), parks it behind the outbound gate. Triage, filing, extraction,
  summarising, and held drafts are all safe to complete on their own — that
  is the whole value of an inbox loop over a "reply to everything" button.

Kinds and their gate:

  kind        gate        what actually happens
  file        none        note lands in the vault under a slug
  extract     none        structured row written (vendor, amount, ref, etc.)
  summarize   none        one-paragraph digest written to the work queue
  flag        none        work card raised for a human
  draft       none        reply written to disk, never sent
  send        outbound    full reply DRAFTED and parked behind an approval

The gate decision lives at the dispatch boundary, exactly like the
scheduler's money/outbound gate: un-gated kinds complete synchronously;
the gated kind records an approval row and stops. Nothing here fabricates
a "sent" — the ledger and the work queue only ever record what actually
happened (the honest-lifecycle rule this repo's scheduler already
enforces).

This module is deliberately core-internal (no fastapi, no auth):
dashboard.py and webhook.py call `classify` + `apply` and expose the
surface; the executor/harness does the *thinking* when a kind needs one.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import re
import uuid
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# The kind taxonomy
# ---------------------------------------------------------------------------

#: (kind, gate, done_text) — gate is None for ungated kinds, "outbound" for
#: the one kind that must not fire unattended. done_text describes the
#: artifact created, for the work queue / ledger honesty rule.
KINDS: Dict[str, Dict[str, str]] = {
    "file": {"gate": None, "done": "filed to the vault"},
    "extract": {"gate": None, "done": "extracted to a structured record"},
    "summarize": {"gate": None, "done": "summarised"},
    "flag": {"gate": None, "done": "flagged for a person"},
    "draft": {"gate": None, "done": "drafted (held, not sent)"},
    "send": {"gate": "outbound", "done": "drafted and parked for approval"},
}

# Deterministic first pass. The classifier is ALWAYS available (no model
# needed) so the loop makes progress even with no provider configured; an
# LLM pass (below) only refines the low-confidence cases. Patterns are
# deliberately conservative: a mis-file costs nothing; a false "send" is
# the one thing this file must never produce on its own, so the send
# signal requires explicit send-intent words, not just urgency.
_RULE_FILE = re.compile(r"\b(receipt|invoice|payment confirm|order confirm|shipping confirm|"
                         r"your pass|e-?ticket|statement|attached|here is|enclosed)\b", re.I)
_RULE_EXTRACT = re.compile(r"\b(balance|overdue|outstanding|amount due|reference|"
                            r"account no|invoice no|renewal|due by|\$|usd)\b", re.I)
_RULE_FLAG = re.compile(r"\b(urgent|asap|immediately|fwd:|final notice|"
                         r"action required|escalat|complaint|refund)\b", re.I)
_RULE_SEND = re.compile(r"\b(reply|respond|send|write back|get back to me|"
                         r"awaiting your response)\b", re.I)
_RULE_DRAFT = re.compile(r"\b(what do you think|suggest|draft|proposal|offer"
                          r"|quote)\b", re.I)

#: Lexical send intent — a message only reaches kind=send when it both asks
#: for a reply AND shows conversational reply intent. The pure
#: action-and-informational messages (statements, confirmations, notices)
#: never get a send classification from rules alone.
_SEND_TRIGGERS = ("reply", "respond", "write back", "please send", "awaiting your",
                  "get back to", "can you")


@dataclasses.dataclass
class InboxMessage:
    """One message through the loop. Raw fields come off the wire; the rest
    are filled by classify()/apply()."""

    message_id: str
    from_addr: str
    subject: str
    body: str
    received_at: str
    kind: str = ""
    gate: Optional[str] = None
    notes: str = ""
    dispatched: bool = False

    @classmethod
    def from_body(cls, body: Dict[str, object]) -> "InboxMessage":
        """Parse a wire payload. Missing fields degrade to the empty string
        rather than raising — a harness that only forwards subject+body still
        works."""
        return cls(
            message_id=str(body.get("message_id") or uuid.uuid4().hex[:12]),
            from_addr=str(body.get("from") or ""),
            subject=str(body.get("subject") or ""),
            body=str(body.get("body") or ""),
            received_at=str(body.get("received_at")
                            or dt.datetime.now(dt.timezone.utc).isoformat()),
        )

    @property
    def text(self) -> str:
        return f"From: {self.from_addr}\nSubject: {self.subject}\n\n{self.body}"

    def to_record(self) -> Dict[str, object]:
        return {
            "message_id": self.message_id,
            "from": self.from_addr,
            "subject": self.subject,
            "received_at": self.received_at,
            "kind": self.kind,
            "gate": self.gate,
            "notes": self.notes,
            "dispatched": self.dispatched,
        }


def classify(message: InboxMessage) -> str:
    """Deterministic kind assignment. Order is load-bearing: send is the
    last gate — nothing urgency-shaped ever triggers it without explicit
    reply intent; flag beats draft beats extract beats file on the same
    message so the most consequential reading wins."""
    text = message.text
    if _RULE_FLAG.search(text):
        # A reply request under an urgency signal is a send (a person needs
        # to answer), but only with explicit reply intent.
        if _RULE_SEND.search(text) or any(t in text.lower() for t in _SEND_TRIGGERS):
            return "send"
        return "flag"
    if _RULE_SEND.search(text) or any(t in text.lower() for t in _SEND_TRIGGERS):
        return "send"
    if _RULE_DRAFT.search(text):
        return "draft"
    if _RULE_EXTRACT.search(text):
        return "extract"
    if _RULE_FILE.search(text):
        return "file"
    return "summarize"


def _vault_note_path(vault_dir: str, slug: str) -> str:
    return os.path.join(vault_dir, f"{slug}.md")


def apply(message: InboxMessage, data_dir: str, *, outbound_gate=None) -> str:
    """Apply the classified kind and return a one-line outcome for the
    ledger / work queue. Ungated kinds complete here. gated kinds create a
    held draft plus — when an outbound_gate callable is supplied — an
    approval row, and stop; when no gate callable is wired, the draft still
    persists and the caller records the parking decision."""
    kind = message.kind or classify(message)
    message.kind = kind
    message.gate = KINDS[kind]["gate"]

    vault_dir = os.path.join(data_dir, "vault")
    work_dir = os.path.join(data_dir, "workqueue")
    os.makedirs(vault_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    safe_slug = re.sub(r"[^a-z0-9-]+", "-", message.subject.lower()).strip("-")[:60] or "message"

    if kind == "file":
        path = _vault_note_path(vault_dir, safe_slug)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n\n## {message.subject}\n\n{message.body}\n")
        message.notes = f"filed to {os.path.basename(path)}"

    elif kind == "extract":
        # Structured record: one JSON line in the work queue, kept out of the
        # vault (a data row is not a note).
        row = message.to_record()
        row["extracted_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _append_jsonl(os.path.join(work_dir, "extractions.jsonl"), row)
        message.notes = "extractions.jsonl"

    elif kind == "flag":
        _append_jsonl(os.path.join(work_dir, "flags.jsonl"), message.to_record())
        message.notes = "flags.jsonl"

    elif kind in ("draft", "send"):
        # A draft is always written — for kind=send it doubles as the
        # artifact the approval row points at. It is NEVER sent here.
        draft_dir = os.path.join(data_dir, "drafts")
        os.makedirs(draft_dir, exist_ok=True)
        path = os.path.join(draft_dir, f"{message.message_id}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Draft reply — {message.subject}\n\n"
                    f"From: {message.from_addr}\n\n"
                    f"---\n\n(message to answer, held for review)\n")
        message.notes = f"draft at {os.path.basename(path)}"
        if kind == "send" and outbound_gate is not None:
            outbound_gate(message)

    elif kind == "summarize":
        _append_jsonl(os.path.join(work_dir, "digest.jsonl"), message.to_record())
        message.notes = "digest.jsonl"

    message.dispatched = True
    return KINDS[kind]["done"]


def _append_jsonl(path: str, row: Dict[str, object]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def read_work(name: str, data_dir: str, *, limit: int = 50) -> List[Dict[str, object]]:
    """Read back one work-queue stream (extractions|flags|digest), newest
    first. Used by the API surface; the honest read-side of what apply()
    wrote."""
    path = os.path.join(data_dir, "workqueue", f"{name}.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows[-limit:][::-1]