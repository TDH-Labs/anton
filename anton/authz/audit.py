"""WORM-anchored hash-chained audit log (AUTHZ-SPEC §7, REQ-AUDIT-01).

Append-only SQLite with per-entry hash chaining and monotonic sequence
numbers. A single writer lock serializes chain writes (R2-N7) so
concurrent writers produce one valid chain.

HONEST LIMIT (review R2A-7): tail-truncation detection compares the chain
against kv.audit_head_seq, which lives in the SAME database — an attacker
with raw DB access can rewrite both. That check defends against partial/
accidental truncation, not a full DB-level attacker; the authoritative
control against that threat is external WORM anchoring (REQ-AUDIT-02,
scheduled for the audit phase), not this in-file comparison.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading

GENESIS = "0" * 64


class ChainTampered(Exception):
    pass


class ChainGap(Exception):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _principal_str(actor) -> str:
    return getattr(actor, "principal_id", None) or str(actor)


def _sponsor(actor) -> str:
    return getattr(actor, "human_id", None) or _principal_str(actor)


class AuditLog:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()

    def append(self, event_type: str, actor=None, payload: dict | None = None,
               workspace: str = "default", agent_instance: str = "",
               tool_credential: str = "", sponsor_user: str | None = None) -> int:
        actor_str = _principal_str(actor)
        sponsor = sponsor_user if sponsor_user is not None else (
            _sponsor(actor) if actor is not None else actor_str)
        payload_json = json.dumps(payload or {}, sort_keys=True)
        ts = _now()
        with self._lock:
            with self.store.lock:
                row = self.store.conn.execute(
                    "SELECT seq, hash FROM audit_chain ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                seq = (row["seq"] + 1) if row else 1
                prev_hash = row["hash"] if row else GENESIS
                digest = self._entry_hash(
                    prev_hash, seq, ts, event_type, actor_str, payload_json,
                    sponsor_user=str(sponsor), workspace=str(workspace),
                    agent_instance=str(agent_instance),
                    tool_credential=str(tool_credential))
                self.store.conn.execute(
                    "INSERT INTO audit_chain(seq, ts, event_type, actor,"
                    " sponsor_user, workspace, agent_instance, tool_credential,"
                    " payload_json, prev_hash, hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (seq, ts, event_type, actor_str, str(sponsor),
                     str(workspace), str(agent_instance), str(tool_credential),
                     payload_json, prev_hash, digest))
                self.store.kv_set("audit_head_seq", str(seq))
                if not getattr(self.store, "in_migration_txn", False):
                    self.store.conn.commit()
        return seq

    @staticmethod
    def _entry_hash(prev_hash, seq, ts, event_type, actor, payload_json,
                    sponsor_user="", workspace="default",
                    agent_instance="", tool_credential="") -> str:
        """Hash covers the full row INCLUDING the four-identity columns —
        rewriting sponsor attribution is tamper-evident (REQ-AUDIT-01)."""
        basis = "|".join(str(x) for x in (
            prev_hash, seq, ts, event_type, actor, payload_json,
            sponsor_user, workspace, agent_instance, tool_credential))
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def head(self) -> int:
        val = self.store.kv_get("audit_head_seq")
        return int(val) if val else 0

    def verify(self) -> tuple[bool, str]:
        """Full-chain verification. Raises ChainTampered / ChainGap;
        returns (True, 'ok') when the chain is intact."""
        prev = GENESIS
        count = 0
        for row in self.store.conn.execute(
                "SELECT * FROM audit_chain ORDER BY seq ASC"):
            expect = self._entry_hash(
                prev, row["seq"], row["ts"], row["event_type"], row["actor"],
                row["payload_json"], sponsor_user=row["sponsor_user"],
                workspace=row["workspace"],
                agent_instance=row["agent_instance"],
                tool_credential=row["tool_credential"])
            if row["prev_hash"] != prev or row["hash"] != expect:
                raise ChainTampered(f"chain verification failed at seq={row['seq']}")
            prev = row["hash"]
            count += 1
        max_seq = self.head()
        if max_seq and count < max_seq:
            raise ChainGap(
                f"expected {max_seq} entries, found {count} — tail truncation")
        return True, "ok"

    def rows_by_type(self, event_type: str) -> list[dict]:
        rows = self.store.conn.execute(
            "SELECT * FROM audit_chain WHERE event_type=? ORDER BY seq",
            (event_type,)).fetchall()
        return [dict(r) for r in rows]
