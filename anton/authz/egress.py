"""Egress channels: AgentPhone/Email opt-in connections, tag gate,
governor apply (handoff #11; AUTHZ-SPEC §6 gate semantics for Phase 1).

Channels are privileged creations (REQ-EGRESS-06), dormant until an
explicit opt-in (audit-chained), and every outbound payload is classified
and checked against the recipient's clearance before the governor's
outbound hard gate routes it into the approvals spine. Nothing here sends
by itself: `execute_send` invokes a deployment-injected sender only after
an approver != initiator signed off and the TOCTOU hash check passes.
"""
from __future__ import annotations

import datetime as dt

from . import rbac
from .approvals import create_approval, execute_approved


def classify_outbound():
    """Governor apply: outbound is a hard gate — always approval."""
    from ..governor import PRESENT_FOR_APPROVAL, classify
    ruling = classify(ev=1.0, feasibility=1.0, risk="low", kind="outbound")
    assert ruling.route == PRESENT_FOR_APPROVAL
    return ruling

TAG_ORDER = {"PUBLIC": 0, "INTERNAL": 1, "SECRET": 2}


class EgressBlocked(Exception):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def max_tag(tags) -> str:
    """Derived content inherits the max tag of its inputs (REQ-EGRESS-02)."""
    level = -1
    out = "PUBLIC"
    for t in tags:
        if t not in TAG_ORDER:
            raise ValueError(f"unknown tag {t!r}")
        if TAG_ORDER[t] > level:
            level, out = TAG_ORDER[t], t
    return out


def require_capability(actor, capability: str, store, audit, what: str) -> None:
    if not rbac.can(getattr(actor, "role", None), capability):
        audit.append("authorization_denied", actor=actor, payload={
            "reason": "missing_capability", "capability": capability,
            "what": what})
        raise PermissionError(f"{what} requires capability {capability}")


def create_channel(store, audit, actor, channel_id: str, kind: str,
                   address: str, clearance: str = "INTERNAL",
                   recipient_name: str = "") -> None:
    require_capability(actor, "egress.channels.manage", store, audit,
                       "egress.channel.create")
    if kind not in ("agentphone_sms", "agentphone_call", "email", "webhook"):
        raise ValueError(f"unknown channel kind {kind!r}")
    if clearance not in TAG_ORDER:
        raise ValueError(f"unknown clearance {clearance!r}")
    with store.lock:
        store.conn.execute(
            "INSERT INTO egress_channels(id, kind, address, recipient_name,"
            " clearance, opt_in, created_by, created) VALUES(?,?,?,?,?,0,?,?)",
            (channel_id, kind, address, recipient_name, clearance,
             actor.user_id, _now()))
        store.conn.commit()
    audit.append("egress_channel_created", actor=actor, payload={
        "channel_id": channel_id, "kind": kind,
        "clearance": clearance})


def opt_in(store, audit, actor, channel_id: str) -> None:
    """Explicit consent to use a channel — the default is OFF."""
    require_capability(actor, "egress.channels.manage", store, audit,
                       "egress.channel.opt_in")
    row = store.conn.execute("SELECT id FROM egress_channels WHERE id=?",
                             (channel_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such channel {channel_id}")
    with store.lock:
        store.conn.execute(
            "UPDATE egress_channels SET opt_in=1 WHERE id=?", (channel_id,))
        store.conn.execute(
            "INSERT INTO egress_optins(channel_id, actor_id, ts) VALUES(?,?,?)",
            (channel_id, actor.user_id, _now()))
        store.conn.commit()
    audit.append("egress_opted_in", actor=actor,
                 payload={"channel_id": channel_id})


def build_send_payload(store, channel_id: str, tag: str, body: str) -> dict:
    """Canonical wire payload for a gated send. Callers pass THIS dict back
    to execute_send after approval — any drift trips the TOCTOU hash."""
    row = store.conn.execute(
        "SELECT kind, address FROM egress_channels WHERE id=?",
        (channel_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such channel {channel_id}")
    return {"egress": True, "channel_id": channel_id, "kind": row["kind"],
            "to": row["address"], "tag": tag, "body": body}


def submit_send(store, audit, actor, channel_id: str, tag: str,
                body: str) -> int:
    """Gate + classify + route. Returns an approval id; nothing is sent
    until the approval spine completes."""
    row = store.conn.execute(
        "SELECT * FROM egress_channels WHERE id=?", (channel_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such channel {channel_id}")
    if not row["opt_in"]:
        audit.append("egress_blocked", actor=actor, payload={
            "reason": "channel_not_opted_in", "channel_id": channel_id})
        raise EgressBlocked(
            f"channel {channel_id} has not been opted in")
    if tag not in TAG_ORDER:
        raise ValueError(f"unknown tag {tag!r}")
    if TAG_ORDER[tag] > TAG_ORDER[row["clearance"]]:
        audit.append("egress_blocked", actor=actor, payload={
            "reason": "tag_exceeds_clearance", "channel_id": channel_id,
            "tag": tag, "clearance": row["clearance"]})
        raise EgressBlocked(
            f"payload tag {tag} exceeds recipient clearance "
            f"{row['clearance']} on {channel_id}")

    # Governor apply: outbound is a hard gate — always approval, regardless
    # of score (kind="outbound" ∈ HARD_GATE_KINDS).
    ruling = classify_outbound()
    if ruling.route != "present_for_approval":
        audit.append("egress_blocked", actor=actor, payload={
            "reason": "governor_unexpected_route",
            "route": ruling.route})
        raise EgressBlocked("governor did not hard-gate this send")

    return create_approval(store, audit, initiator=actor,
                           payload=build_send_payload(store, channel_id,
                                                      tag, body),
                           policy_version="egress-v1")


def execute_send(store, audit, sender, approval_id: int,
                 current_payload: dict) -> dict:
    """Runs only after approve() by a distinct human and the payload-hash
    TOCTOU check. `sender(payload) -> dict` is injected at deployment
    (AgentPhone MCP / SMTP); the spine never ships a live sender."""
    execute_approved(store, audit, approval_id=approval_id,
                     current_payload=current_payload)
    result = sender(current_payload)
    audit.append("egress_sent", payload={
        "approval_id": approval_id,
        "channel_id": current_payload.get("channel_id"),
        "ok": bool(result.get("ok"))})
    return result
