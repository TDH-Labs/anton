"""Approvals: append-only, approver≠initiator, TOCTOU-safe (AUTHZ-SPEC §5).

Approval rows are created once and never amended (schema triggers reject
UPDATE/DELETE). The payload hash is recomputed at execution time so any
post-approval mutation is detected (REQ-APPR-01). Human binding collapses
service identities to their owning human (REQ-APPR-02).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3


class ApprovalRejected(Exception):
    pass


class PayloadTamperError(Exception):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def create_approval(store, audit, initiator, payload: dict,
                    policy_version: str) -> int:
    with store.lock:
        cur = store.conn.execute(
            "INSERT INTO authz_approvals(initiator_principal, initiator_human,"
            " payload_hash, payload_json, policy_version, created)"
            " VALUES(?,?,?,?,?,?)",
            (initiator.principal_id, initiator.human_id,
             _payload_hash(payload), json.dumps(payload, sort_keys=True),
             policy_version, _now()))
        store.conn.commit()
        aid = cur.lastrowid
    audit.append("approval_created", actor=initiator, payload={
        "approval_id": aid, "payload_hash": _payload_hash(payload),
        "policy_version": policy_version})
    return aid


def approve(store, audit, approver, approval_id: int,
            decision: str = "approved") -> None:
    """Records a decision row. The schema trigger rejects decisions where
    the approver's HUMAN equals the initiator's human — initiating through
    a service identity does not satisfy approver ≠ initiator."""
    row = store.conn.execute(
        "SELECT * FROM authz_approvals WHERE id=?", (approval_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such approval {approval_id}")
    already = store.conn.execute(
        "SELECT 1 FROM approval_decisions WHERE approval_id=?",
        (approval_id,)).fetchone()
    if already:
        raise ApprovalRejected("approval already decided")
    # R9: shared-key decision evidence — a raw-SQL writer cannot fabricate a
    # valid evidence hmac without the decision secret.
    import hashlib as _hashlib
    import hmac as _hmac
    secret = getattr(store, "decision_secret", None)
    evidence = None
    if secret:
        evidence = _hmac.new(secret.encode(),
                             f"{approval_id}:{row['payload_hash']}".encode(),
                             _hashlib.sha256).hexdigest()
    try:
        with store.lock:
            # ux_decision_once makes the decision one-per-approval at the
            # schema level; two concurrent approvers race on the INSERT.
            store.conn.execute(
                "INSERT INTO approval_decisions(approval_id,"
                " approver_principal, approver_human, decision, evidence_hmac, ts)"
                " VALUES(?,?,?,?,?,?)",
                (approval_id, approver.principal_id, approver.human_id,
                 decision, evidence, _now()))
            store.conn.commit()
    except sqlite3.IntegrityError as e:
        audit.append("authorization_denied", actor=approver, payload={
            "reason": "decision_race_or_self_approval",
            "approval_id": approval_id})
        raise ApprovalRejected(str(e)) from e
    audit.append("approval_decided", actor=approver, payload={
        "approval_id": approval_id, "decision": decision})


# Alias matching CI test naming.
decide_approval = approve


def execute_approved(store, audit, approval_id: int,
                     current_payload: dict) -> None:
    """TOCTOU gate: any edit to the payload after approval invalidates the
    approval (hash mismatch detected at execution time). One-shot: an
    approval is consumed by its first execution."""
    row = store.conn.execute(
        "SELECT * FROM authz_approvals WHERE id=?", (approval_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such approval {approval_id}")
    decision = store.conn.execute(
        "SELECT decision, evidence_hmac FROM approval_decisions "
        "WHERE approval_id=?", (approval_id,)).fetchone()
    if decision is None or decision["decision"] != "approved":
        audit.append("authorization_denied", payload={
            "reason": "execution_without_approved_decision",
            "approval_id": approval_id})
        raise ApprovalRejected("no approved decision for this approval")
    # R9: shared-key evidence — a raw-SQL fabricated decision (two fake
    # humans) cannot produce a valid hmac.
    secret = getattr(store, "decision_secret", None)
    if secret:
        import hashlib as _hashlib
        import hmac as _hmac
        expected = _hmac.new(secret.encode(),
                             f"{approval_id}:{row['payload_hash']}".encode(),
                             _hashlib.sha256).hexdigest()
        got = decision["evidence_hmac"]
        if not got or not _hmac.compare_digest(got, expected):
            audit.append("authorization_denied", payload={
                "reason": "decision_evidence_invalid",
                "approval_id": approval_id})
            raise ApprovalRejected(
                f"decision evidence invalid (approval {approval_id})")
    if _payload_hash(current_payload) != row["payload_hash"]:
        audit.append("approval_tamper", payload={
            "approval_id": approval_id,
            "expected": row["payload_hash"],
            "actual": _payload_hash(current_payload)})
        raise PayloadTamperError(
            f"payload mutated after approval (approval {approval_id})")
    try:
        with store.lock:
            store.conn.execute(
                "INSERT INTO approval_executions(approval_id, executed_at)"
                " VALUES(?,?)", (approval_id, _now()))
            store.conn.commit()
    except sqlite3.IntegrityError as e:
        audit.append("authorization_denied", payload={
            "reason": "approval_already_executed",
            "approval_id": approval_id})
        raise ApprovalRejected(
            f"approval {approval_id} already executed") from e
    audit.append("approval_executed", payload={"approval_id": approval_id})
