"""Connection grants & self-grant prevention (AUTHZ-SPEC §4).

The schema triggers in schema.py are the enforcement point; this module is
the typed API around them plus scope hygiene (REQ-GRNT-04).
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

WRITE_HINTS = ("write", "full_access", "admin", "delete")


class SelfGrantError(Exception):
    pass


class MutualEscalationError(SelfGrantError):
    pass


class ScopeHygieneError(Exception):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_grant(store, audit, granter, grantee_user_id: str,
                 connection_id: str, scope: str, oauth_scopes: list[str],
                 policy_version: str = "v1") -> int:
    if scope not in ("use", "full"):
        raise ValueError("scope must be 'use' or 'full'")
    try:
        with store.lock:
            cur = store.conn.execute(
                "INSERT INTO connection_grants(granter_id, grantee_id,"
                " connection_id, scope, oauth_scopes_json, policy_version,"
                " active, created) VALUES(?,?,?,?,?,?,1,?)",
                (granter.user_id, grantee_user_id, connection_id, scope,
                 json.dumps(sorted(oauth_scopes)), policy_version, _now()))
            store.conn.commit()
            grant_id = cur.lastrowid
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if "mutual escalation" in msg:
            raise MutualEscalationError(msg) from e
        raise SelfGrantError(msg) from e
    audit.append("grant_created", actor=granter, payload={
        "grant_id": grant_id, "grantee": grantee_user_id,
        "connection_id": connection_id, "scope": scope,
        "oauth_scopes": sorted(oauth_scopes),
        "policy_version": policy_version})
    return grant_id


def revoke_grant(store, audit, actor, grant_id: int) -> None:
    row = store.conn.execute(
        "SELECT * FROM connection_grants WHERE id=?", (grant_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such grant {grant_id}")
    with store.lock:
        store.conn.execute(
            "UPDATE connection_grants SET active=0, revoked_at=? WHERE id=?",
            (_now(), grant_id))
        store.conn.commit()
    # REQ-GRNT-01: revoke triggers server-side refresh-token rotation.
    if store.token_rotator is not None:
        try:
            store.token_rotator(row["connection_id"])
        except Exception:
            pass
    audit.append("grant_revoked", actor=actor, payload={
        "grant_id": grant_id, "connection_id": row["connection_id"],
        "grantee": row["grantee_id"]})


def transfer_ownership(store, audit, actor, target_user_id: str,
                       connection_id: str) -> int:
    """Ownership transfer flows are treated as grants and subject to the
    same self-grant rule (REQ-GRNT-02)."""
    if target_user_id == actor.user_id:
        raise SelfGrantError("self-directed ownership transfer forbidden")
    return create_grant(store, audit, actor, target_user_id,
                        connection_id, scope="full", oauth_scopes=[])


def grant_response(store, grant_id: int) -> dict:
    """Grant representation for API responses — `full` never exposes
    refresh tokens to the grantee (REQ-GRNT-01)."""
    row = store.conn.execute(
        "SELECT id, granter_id, grantee_id, connection_id, scope,"
        " oauth_scopes_json, policy_version, active, created"
        " FROM connection_grants WHERE id=?", (grant_id,)).fetchone()
    if row is None:
        raise KeyError(f"no such grant {grant_id}")
    d = dict(row)
    d["oauth_scopes"] = json.loads(d.pop("oauth_scopes_json"))
    # Deliberately no token material of any kind.
    return d


def has_active_grant(store, principal_id: str, connection_id: str) -> bool:
    row = store.conn.execute(
        "SELECT 1 FROM connection_grants WHERE grantee_id=? AND "
        "connection_id=? AND active=1 LIMIT 1",
        (principal_id, connection_id)).fetchone()
    return row is not None


def scope_diff_report(store) -> list[dict]:
    """Granted-vs-used OAuth scope diff per connector (REQ-GRNT-04)."""
    out = []
    rows = store.conn.execute(
        "SELECT connection_id, oauth_scopes_json FROM connection_grants "
        "WHERE active=1").fetchall()
    granted_by_conn: dict[str, set[str]] = {}
    for r in rows:
        granted_by_conn.setdefault(r["connection_id"], set()).update(
            json.loads(r["oauth_scopes_json"]))
    used_rows = store.conn.execute("SELECT * FROM used_scopes").fetchall()
    used_by_conn = {r["connection_id"]: set(json.loads(r["scopes_json"]))
                    for r in used_rows}
    for conn_id, granted in sorted(granted_by_conn.items()):
        used = used_by_conn.get(conn_id, set())
        out.append({
            "connection_id": conn_id,
            "granted": sorted(granted),
            "used": sorted(used),
            "unused_scopes": sorted(granted - used),
        })
    return out


def release_gate_check(report: list[dict]) -> None:
    violations = [r for r in report if r.get("unused_scopes")]
    if violations:
        raise ScopeHygieneError(
            "connectors hold unused granted scopes: "
            + "; ".join(f"{v['connection_id']}: {v['unused_scopes']}"
                        for v in violations))
