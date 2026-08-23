"""Break-glass, recovery artifact, single-operator pending actions
(AUTHZ-SPEC §5, REQ-APPR-03/04/05)."""
from __future__ import annotations

import datetime as dt
import hashlib
import time


class BreakGlassRateLimited(Exception):
    pass


class BreakGlassDeliveryFailed(Exception):
    pass


class RecoveryArtifactError(Exception):
    pass


def _epoch() -> float:
    return time.time()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Break-glass elevation (REQ-APPR-03)
# ---------------------------------------------------------------------------

def request_breakglass(store, audit, principal, reason: str,
                       duration_min: float, channels,
                       rate_limit: tuple[int, int] = (1, 3600)) -> dict:
    """channels: list of callables f(message) -> bool. Success if either
    delivers; undelivered channels are flagged. Rate limits prevent
    normalization. Elevation windows expire automatically."""
    max_count, window_s = rate_limit
    cutoff = _epoch() - window_s
    cutoff_str = dt.datetime.fromtimestamp(
        cutoff, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Deliver channels OUTSIDE the write lock — never hold the global authz
    # write lock across unbounded network I/O (R4-4 regression fix): a hung
    # channel must not wedge login/sessions/grants/audit.
    ok = failed = 0
    message = (f"BREAK-GLASS elevation by "
               f"{principal.principal_id}: {reason}")
    for channel in channels:
        try:
            if channel(message):
                ok += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    # REQ-APPR-03: "success if either delivers" — a fully silent elevation
    # is refused and audited (R2A-6).
    if ok == 0:
        audit.append("breakglass_refused", actor=principal, payload={
            "reason": "no_channel_delivered", "channels_failed": failed})
        raise BreakGlassDeliveryFailed(
            "break-glass refused: no notification channel delivered")

    # Rate check + insert happen atomically under the write lock; the
    # (slow) delivery already happened above so the critical section is
    # short and concurrent requests cannot both observe n < limit (R3B-4).
    with store.lock:
        n = store.conn.execute(
            "SELECT COUNT(*) FROM breakglass_events WHERE ts > ?",
            (cutoff_str,)).fetchone()[0]
        if n >= max_count:
            raise BreakGlassRateLimited(
                f"break-glass limited to {max_count} per {window_s}s")
        expires = _epoch() + duration_min * 60
        store.conn.execute(
            "INSERT INTO breakglass_events(principal, reason, expires, ts,"
            " channels_ok, channels_failed) VALUES(?,?,?,?,?,?)",
            (principal.principal_id, reason, expires, _now(), ok, failed))
        store.conn.commit()
    audit.append("breakglass", actor=principal, payload={
        "reason": reason, "duration_min": duration_min,
        "channels_ok": ok, "channels_failed": failed})
    return {"elevated": True, "expires": expires,
            "channels_ok": ok, "channels_failed": failed}


def elevation_active(store, principal_id: str) -> bool:
    row = store.conn.execute(
        "SELECT 1 FROM breakglass_events WHERE principal=? AND expires > ?"
        " LIMIT 1", (principal_id, _epoch())).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Offline recovery artifact (REQ-APPR-04)
# ---------------------------------------------------------------------------

def generate_recovery_artifact(store, n_codes: int = 2) -> list[str]:
    """Generates one-time recovery codes; only sha256 hashes are stored.
    The plaintext codes are for the operator to store OFF-MACHINE."""
    import secrets as pysecrets
    codes = [pysecrets.token_hex(6) for _ in range(n_codes)]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    store.kv_set("recovery_codes", "\n".join(hashes))
    return codes


def use_recovery_artifact(store, audit, broker, code: str,
                          failed_channels=None) -> dict:
    """Works with all channels down and no second approver; triggers a
    mandatory post-hoc audit entry and forces broker re-keying.

    Atomicity (R3B-5): verification and consumption happen under the store
    lock (only ONE concurrent caller can win a given code), and rotation is
    attempted BEFORE consumption so a re-key failure does not burn the
    operator's last offline code."""
    failed_channels = failed_channels or []
    digest = hashlib.sha256(code.encode()).hexdigest()
    with store.lock:
        stored = store.kv_get("recovery_codes") or ""
        lines = [l for l in stored.splitlines() if l]
        if digest not in lines:
            raise RecoveryArtifactError("invalid recovery code")
        # rotate first: failure here preserves the code for another try
        try:
            new_version = broker.rotate_master_key()
        except Exception as e:
            audit.append("recovery_rekey_failed", payload={
                "error_class": type(e).__name__})
            raise RecoveryArtifactError(
                f"recovery unlock aborted: broker re-key failed ({e})") from e

        remaining = [l for l in lines if l != digest]
        store.kv_set("recovery_codes", "\n".join(remaining))
        store.conn.execute(
            "INSERT INTO breakglass_events(principal, reason, expires, ts,"
            " channels_ok, channels_failed, recovery)"
            " VALUES('recovery-artifact', 'offline recovery', ?, ?, ?, ?, 1)",
            (_epoch() + 900, _now(),
             len([f for f in failed_channels if f]),
             len([f for f in failed_channels if not f])))
        store.conn.commit()

    audit.append("recovery_artifact_used", payload={
        "channels_failed": len(failed_channels),
        "broker_rekeyed": True})
    return {"unlocked": True, "key_version": new_version}


# ---------------------------------------------------------------------------
# Single-operator pending-actions delay window (REQ-APPR-05a)
# ---------------------------------------------------------------------------

def submit_pending_action(store, kind: str, payload_json: str,
                          delay_s: float) -> int:
    with store.lock:
        cur = store.conn.execute(
            "INSERT INTO pending_actions(kind, payload_json, ready_at, ts)"
            " VALUES(?,?,?,?)",
            (kind, payload_json, _epoch() + delay_s, _now()))
        store.conn.commit()
        return cur.lastrowid


def pending_action_ready(store, pid: int, now: float | None = None) -> bool:
    now = now if now is not None else _epoch()
    row = store.conn.execute(
        "SELECT ready_at, applied FROM pending_actions WHERE id=?",
        (pid,)).fetchone()
    return bool(row and not row["applied"] and row["ready_at"] <= now)


def apply_ready(store, now: float | None = None) -> list[dict]:
    """The scheduled job that promotes matured pending actions. The schema
    invariant set is identical in both modes — single-operator mode never
    drops triggers, it only delays application."""
    now = now if now is not None else _epoch()
    rows = store.conn.execute(
        "SELECT * FROM pending_actions WHERE applied=0 AND ready_at <= ?",
        (now,)).fetchall()
    applied = []
    for r in rows:
        with store.lock:
            store.conn.execute(
                "UPDATE pending_actions SET applied=1 WHERE id=?", (r["id"],))
            store.conn.commit()
        applied.append({"id": r["id"], "kind": r["kind"],
                        "payload": r["payload_json"]})
    return applied
