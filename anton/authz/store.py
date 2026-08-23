"""Identity store: users, sessions, devices, machine tokens (§1).

Server-side sessions only — no bearer JWTs. Every request re-validates
session state (REQ-AUTH-02: no cached auth decisions). Machine tokens use
separate signing material and a distinct hash namespace from user sessions
(CI-T-AUTH-02).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets as pysecrets
import sqlite3
import threading
import uuid

from .principals import UserPrincipal
from .schema import ensure_schema, schema_signature

SESSION_TTL_HOURS = 12
LOCKOUT_WINDOW_S = 900
LOCKOUT_THRESHOLD = 5


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_hex, hash_hex = stored.split("$", 2)
    dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex),
                        n=2**14, r=8, p=1, dklen=32)
    return pysecrets.compare_digest(dk.hex(), hash_hex)


def _token_digest(namespace: str, token: str) -> str:
    # The namespace is part of the stored digest so session and machine
    # token material can never collide or be confused (CI-T-AUTH-02).
    return f"{namespace}:" + hashlib.sha256(
        f"anton-authz:{namespace}:{token}".encode()).hexdigest()


def open_store(path: str) -> "AuthzStore":
    return AuthzStore(path)



def _canonical_conn():
    """A scratch connection holding the EXACT canonical authz schema."""
    import sqlite3 as _s3
    from .schema import SCHEMA, TRIGGERS
    m = _s3.connect(":memory:")
    m.executescript(SCHEMA)
    m.executescript(TRIGGERS)
    return m

class AuthzStore:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.enabled_roles: list[str] | None = None
        self.token_rotator = None  # type: ignore
        self.decision_secret: str | None = None
        self.broker = None
        # R13-B1/R20-2: gate BEFORE heal. If the raw on-disk signature does
        # not match the recorded baseline, the DB drifted or was tampered
        # with while stopped — REFUSE with the file left byte-identical
        # (never heal-then-refuse: that persists a partial state and bricks
        # the install). Remediation (documented, pre-1.0): re-run anton
        # setup to rebuild authz.db; approval history lives in isolation.db.
        self.preheal_refusal = None
        has_kv = bool(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kv'"
        ).fetchone())
        if has_kv:
            baseline = self.kv_get("schema_hash")
            if baseline is not None:
                live = schema_signature(self.conn)
                if live != baseline:
                    self.preheal_refusal = (
                        f"authz schema drifted while stopped "
                        f"(recorded {baseline[:16]}…, on-disk {live[:16]}…) "
                        f"— re-run anton setup to rebuild the authz store.")
                    return  # live DB left byte-identical
        ensure_schema(self.conn)
        self._upgrade_approval_decision_columns()

    def _upgrade_approval_decision_columns(self) -> None:
        """Sanctioned ADDITIVE migration for pre-R9 authz.db files: add
        approval_decisions.evidence_hmac when missing, then refresh the
        recorded schema-hash baseline so boot_check accepts the upgraded DB
        (R10-1: without this, existing installs booted clean then crashed at
        approve())."""
        tbl = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='approval_decisions'").fetchone()
        if tbl is None:
            return
        cols = {r[1] for r in self.conn.execute(
            "PRAGMA table_info(approval_decisions)")}
        if "evidence_hmac" in cols:
            return
        # R11-3: only a TRUE pre-R9 DB (live signature == recorded baseline)
        # may take the sanctioned ALTER + refresh. Anything else is tampering
        # or drift — leave it for boot_check to refuse.
        from .schema import schema_signature
        old_sig = schema_signature(self.conn)
        baseline = self.kv_get("schema_hash")
        # R12-1: a genuine pre-R9 DB ALWAYS has a baseline (recorded since
        # the Phase-1 spine) equal to its live signature. baseline None or a
        # mismatch means tampering/botched restore — leave it for
        # boot_check's fail-closed refusals; never ALTER + re-baseline.
        if baseline is None or baseline != old_sig:
            return
        with self.lock:
            try:
                # single transaction: a crash between ALTER and baseline
                # refresh cannot strand the DB in permanent preheal refusal
                # (R15-B OBS)
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute(
                    "ALTER TABLE approval_decisions ADD COLUMN evidence_hmac TEXT")
                self.kv_set("schema_hash", schema_signature(self.conn))
                self.conn.commit()
            except sqlite3.OperationalError as e:
                try:
                    self.conn.execute("ROLLBACK")
                except Exception:
                    pass
                cols = {r[1] for r in self.conn.execute(
                    "PRAGMA table_info(approval_decisions)")}
                if "evidence_hmac" not in cols:
                    raise
            self.kv_set("schema_hash", schema_signature(self.conn))

    # -- users -----------------------------------------------------------
    def count_users(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_user(self, username: str, password: str,
                    kind: str = "user", human_id: str | None = None) -> dict:
        uid = uuid.uuid4().hex
        hid = human_id or uid
        with self.lock:
            self.conn.execute(
                "INSERT INTO users(id, username, kind, human_id, password_hash, created)"
                " VALUES(?,?,?,?,?,?)",
                (uid, username, kind, hid, _hash_password(password), _now()))
            self.conn.commit()
        return self.get_user(uid)

    def create_service_identity(self, name: str, owning_human_id: str) -> dict:
        return self.create_user(name, pysecrets.token_urlsafe(24),
                                kind="service", human_id=owning_human_id)

    def get_user(self, user_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE id=?",
                                (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE username=?",
                                (username,)).fetchone()
        return dict(row) if row else None

    def set_password(self, user_id: str, password: str) -> None:
        """Password reset revokes every outstanding session immediately."""
        with self.lock:
            self.conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                              (_hash_password(password), user_id))
            self.revoke_user_sessions(user_id)

    # -- roles -------------------------------------------------------------
    def assign_role(self, user_id: str, role: str, actor_id: str) -> None:
        if self.enabled_roles is not None and role not in self.enabled_roles:
            raise PermissionError(
                f"role {role!r} disabled in this deployment mode "
                f"(enabled: {self.enabled_roles})")
        with self.lock:
            try:
                self.conn.execute(
                    "INSERT INTO role_assignments(user_id, role, actor_id, ts)"
                    " VALUES(?,?,?,?)", (user_id, role, actor_id, _now()))
                self.conn.commit()
            except sqlite3.IntegrityError as e:
                raise PermissionError(str(e)) from e
        # Role change revocation is immediate (REQ-AUTH-02).
        self.revoke_user_sessions(user_id)

    def role_of(self, user_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT role FROM role_assignments WHERE user_id=? "
            "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        return row["role"] if row else None

    def principal_of(self, username: str) -> UserPrincipal:
        u = self.get_user_by_username(username)
        if u is None:
            raise KeyError(f"no such user: {username}")
        return UserPrincipal(user_id=u["id"], username=u["username"],
                             role=self.role_of(u["id"]), human_id=u["human_id"],
                             kind=u["kind"])

    def principal_of_service(self, name: str) -> UserPrincipal:
        return self.principal_of(name)

    def principal_by_id(self, user_id: str) -> UserPrincipal | None:
        u = self.get_user(user_id)
        if u is None:
            return None
        return UserPrincipal(user_id=u["id"], username=u["username"],
                             role=self.role_of(u["id"]), human_id=u["human_id"],
                             kind=u["kind"])

    # -- login rate limiting ----------------------------------------------
    def record_login_attempt(self, username: str, ok: bool) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO login_attempts(username, ok, ts) VALUES(?,?,?)",
                (username, 1 if ok else 0, _epoch()))
            self.conn.commit()

    def is_locked(self, username: str) -> bool:
        cutoff = _epoch() - LOCKOUT_WINDOW_S
        n = self.conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE username=? AND ok=0 "
            "AND ts > ?", (username, cutoff)).fetchone()[0]
        return n >= LOCKOUT_THRESHOLD

    def verify_login(self, username: str, password: str) -> dict | None:
        u = self.get_user_by_username(username)
        if u is None or u.get("disabled"):
            return None
        return u if _verify_password(password, u.get("password_hash")) else None

    # -- sessions / devices --------------------------------------------------
    def create_device(self, user_id: str, label: str) -> str:
        dev_id = uuid.uuid4().hex
        with self.lock:
            self.conn.execute(
                "INSERT INTO devices(id, user_id, label, first_seen) VALUES(?,?,?,?)",
                (dev_id, user_id, label, _now()))
            self.conn.commit()
        return dev_id

    def create_session(self, user_id: str, device_id: str,
                       ttl_hours: float = SESSION_TTL_HOURS) -> str:
        sid = uuid.uuid4().hex
        token = "ast_" + pysecrets.token_urlsafe(32)
        expires = _epoch() + ttl_hours * 3600
        with self.lock:
            self.conn.execute(
                "INSERT INTO sessions_authz(id, token_hash, user_id, device_id,"
                " created, expires) VALUES(?,?,?,?,?,?)",
                (sid, _token_digest("session", token), user_id, device_id,
                 _now(), expires))
            self.conn.commit()
        return token

    def resolve_session(self, token: str) -> UserPrincipal | None:
        digest = _token_digest("session", token)
        row = self.conn.execute(
            "SELECT s.id AS sid, s.expires, s.revoked, u.* "
            "FROM sessions_authz s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash=?", (digest,)).fetchone()
        if row is None or row["revoked"] or row["expires"] <= _epoch():
            return None
        if row["disabled"]:
            # A disabled user's outstanding sessions die immediately
            # (review O-3).
            return None
        return UserPrincipal(
            user_id=row["id"], username=row["username"],
            role=self.role_of(row["id"]), human_id=row["human_id"],
            kind=row["kind"], session_id=row["sid"])

    def session_active(self, session_id: str) -> bool:
        row = self.conn.execute(
            "SELECT revoked, expires FROM sessions_authz WHERE id=?",
            (session_id,)).fetchone()
        return bool(row and not row["revoked"] and row["expires"] > _epoch())

    def revoke_session(self, session_id: str, actor_id: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE sessions_authz SET revoked=1 WHERE id=?", (session_id,))
            self.conn.commit()

    def revoke_user_sessions(self, user_id: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE sessions_authz SET revoked=1 WHERE user_id=? AND revoked=0",
                (user_id,))
            self.conn.commit()

    def list_sessions(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT s.id, s.device_id, s.created, s.expires, s.revoked, d.label "
            "FROM sessions_authz s LEFT JOIN devices d ON d.id = s.device_id "
            "WHERE s.user_id=? ORDER BY s.created DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- machine tokens ----------------------------------------------------
    def mint_machine_token(self, service_user_id: str,
                           ttl_hours: float | None = None) -> tuple[str, str]:
        """Downtime-free rotation (REQ-AUTH-02): mint a replacement token,
        switch the executor over, then revoke the old jti — overlapping
        generations are supported by design. ttl_hours bounds lifetime."""
        jti = uuid.uuid4().hex
        token = "amt_" + pysecrets.token_urlsafe(32)
        expires = (_epoch() + ttl_hours * 3600) if ttl_hours else None
        with self.lock:
            self.conn.execute(
                "INSERT INTO machine_tokens(id, token_hash, service_user_id,"
                " created, expires) VALUES(?,?,?,?,?)",
                (jti, _token_digest("machine", token), service_user_id,
                 _now(), expires))
            self.conn.commit()
        return token, jti

    def resolve_machine_token(self, token: str) -> UserPrincipal | None:
        digest = _token_digest("machine", token)
        row = self.conn.execute(
            "SELECT m.id AS jti, m.revoked, m.expires, u.* FROM machine_tokens m "
            "JOIN users u ON u.id = m.service_user_id WHERE m.token_hash=?",
            (digest,)).fetchone()
        if row is None or row["revoked"]:
            return None
        if row["expires"] is not None and row["expires"] <= _epoch():
            return None
        if row["disabled"]:
            # a disabled service identity's tokens die with it (R12-3)
            return None
        # R9-fix: carry the machine-token jti as the credential binding so
        # broker lease/cap validation can re-check revocation live.
        return UserPrincipal(user_id=row["id"], username=row["username"],
                             role=None, human_id=row["human_id"], kind="service",
                             session_id=f"machine:{row['jti']}")

    def revoke_machine_token(self, jti: str) -> None:
        """Revoke a machine token by id (rotation's second half — R12-3)."""
        with self.lock:
            self.conn.execute(
                "UPDATE machine_tokens SET revoked=1 WHERE id=?", (jti,))
            self.conn.commit()

    def credential_alive(self, credential_ref: str) -> bool:
        """Broker-side liveness check for ANY credential binding carried in
        a lease's session_id field: 'machine:<jti>' re-checks token
        revocation/expiry AND owning-user disabled; anything else is a user
        session id (R9: revocation reaches live leases)."""
        if credential_ref.startswith("machine:"):
            jti = credential_ref[len("machine:"):]
            row = self.conn.execute(
                "SELECT m.revoked, m.expires, u.disabled FROM machine_tokens m"
                " JOIN users u ON u.id = m.service_user_id WHERE m.id=?",
                (jti,)).fetchone()
            if row is None or row["revoked"] or row["disabled"]:
                return False
            return not (row["expires"] is not None
                        and row["expires"] <= _epoch())
        return self.session_active(credential_ref)

    def resolve_any_token(self, token: str) -> UserPrincipal | None:
        """Resolve a bearer credential as either a user session or a
        machine token (broker lease/mint entry point — R9 reach-through)."""
        if token.startswith("amt_"):
            return self.resolve_machine_token(token)
        return self.resolve_session(token)

    # -- misc ----------------------------------------------------------------
    def add_alert(self, kind: str, detail: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO authz_alerts(kind, detail, ts) VALUES(?,?,?)",
                (kind, detail, _now()))
            self.conn.commit()

    def record_used_scopes(self, connection_id: str, scopes: list[str]) -> None:
        import json
        with self.lock:
            self.conn.execute(
                "INSERT INTO used_scopes(connection_id, scopes_json) VALUES(?,?) "
                "ON CONFLICT(connection_id) DO UPDATE SET scopes_json=excluded.scopes_json",
                (connection_id, json.dumps(sorted(scopes))))
            self.conn.commit()

    def kv_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?",
                                (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO kv(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
            # R16-B: inside a migration transaction the caller owns the
            # commit — an early commit here would break atomicity.
            if not getattr(self, "in_migration_txn", False):
                self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def _epoch() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()
