"""Credential broker daemon (AUTHZ-SPEC §3, REQ-CRED-01..06).

Holds all connector secrets encrypted at rest (AES-GCM) with its master
key outside any path readable by the executor or app process. Executors
obtain secrets only via the broker over a unix socket, using short-TTL
capability tokens that are secret-granular, time-boxed to the execution,
and attested by a broker-issued execution lease plus a socket-level
peer-uid check. The broker's issuance epoch is the single time authority
(REQ-CRED-06); worker clock jumps raise alarms but never extend windows.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac as hmac_mod
import json
import os
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .secretrefs import RefResolutionError, SecretRefResolver, _split_ref  # noqa: F401


def default_resolver(vault_root: str | None = None):
    from . import secretrefs
    return secretrefs.default_resolver(vault_root)


BROKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_secrets (
    id TEXT PRIMARY KEY, connection_id TEXT NOT NULL,
    ciphertext BLOB NOT NULL, key_version INTEGER NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS broker_kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS kill_switch (
    scope TEXT PRIMARY KEY, state INTEGER NOT NULL, ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issued_tokens (
    jti TEXT PRIMARY KEY, lease_id TEXT NOT NULL, principal_id TEXT NOT NULL,
    session_id TEXT, execution_id TEXT, expires REAL NOT NULL,
    key_version INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
"""

SKEW_THRESHOLD_S = 300


class BrokerDenied(Exception):
    """Request refused (attestation, scope, grant)."""


class TokenExpired(BrokerDenied):
    pass


class RevokedState(BrokerDenied):
    """Explicit kill-switch state — never a silent retry loop (REQ-CRED-04)."""


class LeaseInvalid(BrokerDenied):
    pass


class BrokerDegraded(Exception):
    """Broker unreachable — executors fail closed with this state
    (REQ-CRED-05)."""


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def b64d(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


@dataclass
class ExecutionLease:
    lease_id: str
    execution_id: str
    principal_id: str
    session_id: str
    connection_ids: list[str]
    expires: float  # broker epoch seconds
    token: str = ""


# --------------------------------------------------------------------------
# peer credentials (SO_PEERCRED on Linux, LOCAL_PEERCRED/getpeereid on macOS)
# --------------------------------------------------------------------------

def _peer_uid(conn: socket.socket) -> int | None:
    try:
        data = conn.getsockopt(socket.SOL_SOCKET, 17, struct.calcsize("3i"))  # SO_PEERCRED
        if len(data) == struct.calcsize("3i"):
            return struct.unpack("3i", data)[1]
    except OSError:
        pass
    try:
        LOCAL_PEERCRED = 0x002  # macOS
        data = conn.getsockopt(socket.SOL_SOCKET, LOCAL_PEERCRED, 12)
        if len(data) >= 8:
            version, uid = struct.unpack("Ii", data[:8])
            if version == 0:  # XUCRED_VERSION
                return uid
    except OSError:
        pass
    # last resort: libc getpeereid
    try:
        import ctypes
        uid = ctypes.c_uint(0)
        gid = ctypes.c_uint(0)
        libc = ctypes.CDLL("libc.so.6") if os.uname().sysname != "Darwin" \
            else ctypes.CDLL("libSystem.B.dylib")
        if libc.getpeereid(conn.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return uid.value
    except Exception:
        pass
    return None  # fail closed: unknown peer => unauthenticated


# --------------------------------------------------------------------------

# In-process callers are the broker itself (trusted); socket requests must
# present a resolvable peer uid.
_INPROCESS = object()


class CredentialBroker:
    def __init__(self, db_path: str, keys_dir: str, socket_path: str,
                 audit=None, allowed_uids: list[int] | None = None,
                 skew_threshold_s: int = SKEW_THRESHOLD_S):
        import sqlite3
        self.db_path = db_path
        self.keys_dir = keys_dir
        self.socket_path = socket_path
        self.audit = audit
        self.skew_threshold_s = skew_threshold_s
        self.allowed_uids = allowed_uids or [os.getuid()]
        self.session_validator = None   # callable(session_id) -> bool
        self.grant_checker = None       # callable(principal_id, connection_id) -> bool
        self.principal_validator = None  # callable(session_token) -> principal | None
        self._resolver = None           # SecretRefResolver (lazy default)
        self._mono_anchor = None        # (monotonic_at_start, wall_at_start)
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        os.makedirs(keys_dir, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.executescript(BROKER_SCHEMA)
        self.conn.commit()
        self._keys: dict[int, bytes] = {}
        self._init_keys()
        base = self.kv_get("epoch_base_wall")
        if base is None:
            self.kv_set("epoch_base_wall", repr(time.time()))
        self._server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    # -- keys / kv -------------------------------------------------------
    def _key_path(self, version: int) -> str:
        return os.path.join(self.keys_dir, f"broker.key.v{version}")

    def _init_keys(self) -> None:
        ver = int(self.kv_get("key_version") or "0")
        if ver == 0:
            ver = 1
            with open(self._key_path(ver), "wb") as f:
                f.write(os.urandom(32))
            os.chmod(self._key_path(ver), 0o600)
            self.kv_set("key_version", str(ver))
        self._load_key(ver)
        self.current_key_version = ver

    def _load_key(self, version: int) -> None:
        if version not in self._keys:
            with open(self._key_path(version), "rb") as f:
                self._keys[version] = f.read()

    @property
    def key_version(self) -> int:
        return self.current_key_version

    def kv_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM broker_kv WHERE key=?",
                                (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO broker_kv(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
            self.conn.commit()

    # -- time authority (REQ-CRED-06) --------------------------------------
    def epoch_now(self) -> float:
        """Seconds since the signed issuance epoch. Wall-clock based, but a
        BACKWARD jump on the broker host is detected against the last
        observed wall time and replaced by the monotonic projection —
        windows can never be extended by clock regression. Alarms on jump."""
        wall = time.time()
        mono = time.monotonic()
        if self._mono_anchor is None:
            last = self.kv_get("last_wall")
            self._mono_anchor = (mono, max(wall, float(last) if last else wall))
        anchor_mono, anchor_wall = self._mono_anchor
        prev_wall = float(self.kv_get("last_wall") or wall)
        if wall < prev_wall - self.skew_threshold_s:
            if self.audit is not None:
                self.audit.append("clock_skew_alarm", payload={
                    "kind": "broker_host_backward_jump",
                    "drift_s": round(prev_wall - wall, 1)})
            projected = anchor_wall + (mono - anchor_mono)
        else:
            # High-water mark: last_wall NEVER moves down, so a staircase
            # of sub-threshold backward steps cannot walk epoch_now back to
            # extend TTLs (review R2A-2). Cumulative regression alarms.
            projected = max(wall, prev_wall)
            self.kv_set("last_wall", repr(projected))
            if wall < prev_wall:
                debt = float(self.kv_get("skew_debt") or 0) + (prev_wall - wall)
                self.kv_set("skew_debt", repr(debt))
                if debt > self.skew_threshold_s and self.audit is not None:
                    self.audit.append("clock_skew_alarm", payload={
                        "kind": "staircase_regression",
                        "cumulative_drift_s": round(debt, 1)})
                    self.kv_set("skew_debt", "0")
            else:
                self.kv_set("skew_debt", "0")
        return projected - float(self.kv_get("epoch_base_wall"))

    def check_client_clock(self, reported_time: float | None) -> None:
        if reported_time is None:
            return
        drift = abs(reported_time - time.time())
        if drift > self.skew_threshold_s and self.audit is not None:
            self.audit.append("clock_skew_alarm",
                              payload={"drift_s": round(drift, 1),
                                       "reported": reported_time})

    # -- secrets ------------------------------------------------------------
    def set_ref_adapters(self, adapters: dict) -> None:
        """BYO password-manager adapters (handoff #12): map of scheme ->
        callable(ref) or SecretAdapter. Replaces the default op://bw://
        vault:// set wholesale."""
        from .secretrefs import CallableAdapter, SecretAdapter, SecretRefResolver
        normalized = {}
        for scheme, a in (adapters or {}).items():
            if isinstance(a, SecretAdapter):
                normalized[scheme] = a
            else:
                normalized[scheme] = CallableAdapter(scheme, a)
        self._resolver = SecretRefResolver(normalized)

    def register_secret(self, secret_id: str, plaintext_or_ref: str,
                        connection_id: str) -> None:
        nonce = os.urandom(12)
        ct = AESGCM(self._keys[self.current_key_version]).encrypt(
            nonce, plaintext_or_ref.encode(), secret_id.encode())
        blob = nonce + ct
        with self.lock:
            self.conn.execute(
                "INSERT INTO broker_secrets(id, connection_id, ciphertext,"
                " key_version, updated) VALUES(?,?,?,?,datetime('now')) "
                "ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext,"
                " key_version=excluded.key_version, updated=excluded.updated",
                (secret_id, connection_id, blob, self.current_key_version))
            self.conn.commit()

    def get_secret(self, secret_id: str) -> tuple[str, str]:
        row = self.conn.execute(
            "SELECT connection_id, ciphertext, key_version FROM broker_secrets "
            "WHERE id=?", (secret_id,)).fetchone()
        if row is None:
            raise BrokerDenied(f"unknown secret {secret_id}")
        self._load_key(row["key_version"])
        stored = AESGCM(self._keys[row["key_version"]]).decrypt(
            bytes(row["ciphertext"][:12]), bytes(row["ciphertext"][12:]),
            secret_id.encode()).decode()
        return self._materialize(secret_id, stored), row["connection_id"]

    def _stored_value(self, secret_id: str) -> tuple[str, str]:
        """Raw stored material (inline secret OR reference text) without
        resolving references — used for grant checks at mint time."""
        row = self.conn.execute(
            "SELECT connection_id, ciphertext, key_version FROM broker_secrets "
            "WHERE id=?", (secret_id,)).fetchone()
        if row is None:
            raise BrokerDenied(f"unknown secret {secret_id}")
        self._load_key(row["key_version"])
        stored = AESGCM(self._keys[row["key_version"]]).decrypt(
            bytes(row["ciphertext"][:12]), bytes(row["ciphertext"][12:]),
            secret_id.encode()).decode()
        return stored, row["connection_id"]

    def _materialize(self, secret_id: str, stored: str) -> str:
        """Inline secrets pass through; references resolve here inside the
        broker — resolution errors surface as an explicit degraded denial
        and never echo the reference text back to the caller."""
        from .secretrefs import RefResolutionError, SecretRefResolver, \
            _split_ref
        try:
            scheme, _ = _split_ref(stored)
        except RefResolutionError:
            return stored  # not a reference: inline secret material
        if self._resolver is None:
            self._resolver = default_resolver()
        if scheme not in self._resolver.adapters:
            # Name the failure class without echoing the scheme value.
            if self.audit is not None:
                self.audit.append("secret_ref_degraded", payload={
                    "secret_id": secret_id, "reason": "unknown_scheme"})
            raise BrokerDenied(
                f"secret {secret_id} unavailable: unsupported reference scheme")
        try:
            return self._resolver.resolve(stored)
        except RefResolutionError:
            if self.audit is not None:
                self.audit.append("secret_ref_degraded", payload={
                    "secret_id": secret_id, "scheme": scheme})
            raise BrokerDenied(
                f"secret {secret_id} unavailable: reference could not be "
                f"resolved")

    def rotate_master_key(self) -> int:
        """Master-key rotation: new key version, full re-encryption. Tokens
        signed under prior versions fail signature verification (REQ-APPR-04
        re-key semantics)."""
        with self.lock:
            new_ver = self.current_key_version + 1
            with open(self._key_path(new_ver), "wb") as f:
                f.write(os.urandom(32))
            os.chmod(self._key_path(new_ver), 0o600)
            self._load_key(new_ver)
            for row in self.conn.execute(
                    "SELECT id, ciphertext, key_version FROM broker_secrets"):
                self._load_key(row["key_version"])
                pt = AESGCM(self._keys[row["key_version"]]).decrypt(
                    bytes(row["ciphertext"][:12]),
                    bytes(row["ciphertext"][12:]), row["id"].encode())
                nonce = os.urandom(12)
                ct = AESGCM(self._keys[new_ver]).encrypt(
                    nonce, pt, row["id"].encode())
                self.conn.execute(
                    "UPDATE broker_secrets SET ciphertext=?, key_version=? "
                    "WHERE id=?", (nonce + ct, new_ver, row["id"]))
            self.kv_set("key_version", str(new_ver))
            self.current_key_version = new_ver
            self.conn.commit()
        return new_ver

    # -- leases & capability tokens -----------------------------------------
    def issue_execution_lease(self, principal, execution_id: str,
                              connection_ids: list[str],
                              ttl_s: int = 300) -> ExecutionLease:
        lease_id = uuid.uuid4().hex
        payload = {
            "typ": "lease", "lid": lease_id, "exec": execution_id,
            "pid": getattr(principal, "principal_id", str(principal)),
            "sid": getattr(principal, "session_id", "") or "",
            "conns": list(connection_ids),
            "exp": round(self.epoch_now() + ttl_s, 3),
        }
        lease = ExecutionLease(
            lease_id=lease_id, execution_id=execution_id,
            principal_id=payload["pid"], session_id=payload["sid"],
            connection_ids=list(connection_ids), expires=payload["exp"])
        lease.token = b64e(json.dumps(payload, sort_keys=True).encode()) + \
            "." + self._sign(payload)
        return lease

    def _sign(self, payload: dict) -> str:
        basis = json.dumps(payload, sort_keys=True).encode()
        return hmac_mod.new(self._hmac_key(), basis, hashlib.sha256).hexdigest()

    def _hmac_key(self) -> bytes:
        return hmac_mod.new(b"anton-broker-hmac-v1",
                            self._keys[self.current_key_version],
                            hashlib.sha256).digest()

    def mint_capability_token(self, lease: ExecutionLease,
                              secret_ids: list[str]) -> str:
        """Secret-granular, time-boxed token bound to the lease. Re-checks
        grants at mint time so revocation between job start and tool call
        is caught (REQ-DATA-02)."""
        self._validate_lease(lease)
        for sid in secret_ids:
            _, connection_id = self._stored_value(sid)
            # REQ-CRED-02: minted secrets must lie within the lease's
            # permitted connection set (R3A-2).
            if connection_id not in lease.connection_ids:
                if self.audit is not None:
                    self.audit.append("authorization_denied", payload={
                        "reason": "connection_outside_lease",
                        "connection_id": connection_id,
                        "lease": lease.execution_id})
                raise BrokerDenied(
                    f"secret {sid} names connection {connection_id!r} outside "
                    "the lease's permitted set")
            if not self._grant_allowed(lease.principal_id, connection_id):
                if self.audit is not None:
                    self.audit.append(
                        "authorization_denied", payload={
                            "reason": "grant_missing_or_revoked",
                            "principal": lease.principal_id,
                            "connection_id": connection_id})
                raise BrokerDenied(
                    f"no active grant for {lease.principal_id} on {connection_id}")
        jti = uuid.uuid4().hex
        payload = {
            "typ": "cap", "jti": jti, "lid": lease.lease_id,
            "exec": lease.execution_id, "pid": lease.principal_id,
            "sid": lease.session_id, "secrets": list(secret_ids),
            "exp": round(min(lease.expires,
                             self.epoch_now() + 600), 3),
            "kv": self.current_key_version,
        }
        with self.lock:
            self.conn.execute(
                "INSERT INTO issued_tokens(jti, lease_id, principal_id,"
                " session_id, execution_id, expires, key_version, created)"
                " VALUES(?,?,?,?,?,?,?,datetime('now'))",
                (jti, lease.lease_id, lease.principal_id, lease.session_id,
                 lease.execution_id, payload["exp"], self.current_key_version))
            self.conn.commit()
        return b64e(json.dumps(payload, sort_keys=True).encode()) + \
            "." + self._sign(payload)

    def _validate_lease(self, lease: ExecutionLease) -> None:
        if lease.expires < self.epoch_now():
            raise LeaseInvalid("execution lease expired")
        if self._revoked(execution_id=lease.execution_id,
                         principal_id=lease.principal_id):
            raise RevokedState("revoked")
        # Fail-closed session binding (R5-6): same helper as check_capability,
        # so lease and mint cannot diverge from fetch when the validator is
        # unwired.
        if self._session_dead(lease.session_id):
            raise LeaseInvalid("issuing session no longer valid")

    # -- validation -----------------------------------------------------------
    def _parse_token(self, token: str) -> dict:
        try:
            body_b64, sig = token.rsplit(".", 1)
            payload = json.loads(b64d(body_b64))
        except Exception as e:
            raise BrokerDenied("malformed token") from e
        basis = json.dumps(payload, sort_keys=True).encode()
        expect = hmac_mod.new(self._hmac_key(), basis,
                              hashlib.sha256).hexdigest()
        if not hmac_mod.compare_digest(sig, expect):
            raise BrokerDenied("invalid token signature")
        return payload

    def _revoked(self, execution_id: str | None = None,
                 principal_id: str | None = None) -> bool:
        for scope, state in self.conn.execute(
                "SELECT scope, state FROM kill_switch WHERE state=1"):
            if scope == "global":
                return True
            if principal_id and scope == f"principal:{principal_id}":
                return True
            if execution_id and scope == f"execution:{execution_id}":
                return True
        return False

    def _token_revoked_row(self, jti: str) -> bool:
        row = self.conn.execute(
            "SELECT revoked FROM issued_tokens WHERE jti=?", (jti,)).fetchone()
        return bool(row and row["revoked"])

    def _session_dead(self, session_id: str) -> bool:
        # ED-2: with no session validator wired, any claimed session binding
        # is unverifiable => treat as dead (fail closed), never trust the
        # token body (R4-5).
        if not session_id:
            return False
        if self.session_validator is None:
            return True
        return not self.session_validator(session_id)

    def _grant_allowed(self, principal_id: str, connection_id: str) -> bool:
        # ED-2: an unwired grant checker is a DENY (R4-5).
        if self.grant_checker is None:
            return False
        return bool(self.grant_checker(principal_id, connection_id))

    def _check_capability(self, cap_payload: dict) -> None:
        if cap_payload.get("kv") != self.current_key_version:
            raise BrokerDenied("token issued under a retired key")
        if cap_payload["exp"] < self.epoch_now():
            raise TokenExpired("capability token expired")
        if self._token_revoked_row(cap_payload["jti"]) or \
                self._revoked(execution_id=cap_payload.get("exec"),
                              principal_id=cap_payload.get("pid")):
            raise RevokedState("revoked")
        if self._session_dead(cap_payload.get("sid", "")):
            raise RevokedState("revoked")

    def check_capability(self, token: str) -> dict:
        try:
            payload = self._parse_token(token)
            if payload.get("typ") != "cap":
                raise BrokerDenied("not a capability token")
            self._check_capability(payload)
            return {"valid": True}
        except BrokerDenied as e:
            return {"valid": False, "reason": str(e)}

    def fetch(self, token: str, secret_id: str, purpose: str,
              reported_time: float | None = None,
              peer_uid=_INPROCESS) -> str:
        """Validate attestation chain, then release one secret. Exactly one
        audit row per successful fetch (REQ-CRED-02)."""
        if peer_uid is not _INPROCESS:
            # Fail closed: an unresolvable peer (None) is unauthenticated.
            if peer_uid is None or peer_uid not in self.allowed_uids:
                if self.audit is not None:
                    self.audit.append("authorization_denied",
                                      payload={"reason": "peer_uid_rejected"})
                raise BrokerDenied("unattested peer")
        self.check_client_clock(reported_time)
        payload = self._parse_token(token)
        if payload.get("typ") != "cap":
            raise BrokerDenied("not a capability token")
        self._check_capability(payload)
        if secret_id not in payload["secrets"]:
            if self.audit is not None:
                self.audit.append("authorization_denied", payload={
                    "reason": "scope_escape", "secret_id": secret_id,
                    "principal": payload.get("pid")})
            raise BrokerDenied(
                f"token does not name secret {secret_id}")
        # Grant re-check BEFORE any decryption/resolution: a revoked
        # principal must never drive the external password-manager adapter
        # (R3C-4).
        row = self.conn.execute(
            "SELECT connection_id FROM broker_secrets WHERE id=?",
            (secret_id,)).fetchone()
        if row is None:
            raise BrokerDenied(f"unknown secret {secret_id}")
        connection_id = row["connection_id"]
        if not self._grant_allowed(payload.get("pid", ""), connection_id):
            if self.audit is not None:
                self.audit.append("authorization_denied", payload={
                    "reason": "grant_missing_or_revoked",
                    "principal": payload.get("pid"),
                    "connection_id": connection_id})
            raise BrokerDenied(
                f"no active grant for {payload.get('pid')} on {connection_id}")
        plaintext, connection_id = self.get_secret(secret_id)
        if self.audit is not None:
            self.audit.append("secret_fetch", payload={
                "requester": payload.get("pid"), "secret_id": secret_id,
                "purpose": purpose, "execution": payload.get("exec"),
                "jti": payload.get("jti")})
        return plaintext

    # -- kill switch ------------------------------------------------------
    def set_kill_switch(self, scope: str, state: bool) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO kill_switch(scope, state, ts) VALUES(?,?,datetime('now'))"
                " ON CONFLICT(scope) DO UPDATE SET state=excluded.state,"
                " ts=excluded.ts", (scope, 1 if state else 0))
            self.conn.commit()

    def check_kill_switch(self, execution_id: str,
                          principal_id: str | None = None) -> dict:
        if self._revoked(execution_id=execution_id, principal_id=principal_id):
            return {"revoked": True, "reason": "revoked"}
        return {"revoked": False, "reason": ""}

    # -- socket server ------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.socket_path)
        os.chmod(self.socket_path, 0o660)
        srv.listen(8)
        self._server_sock = srv
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="authz-broker")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._server_sock.accept()
            except OSError:
                break
            with conn:
                try:
                    conn.settimeout(5)
                    buf = b""
                    while b"\n" not in buf:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                    if not buf.strip():
                        continue
                    req = json.loads(buf.decode())
                    try:
                        resp = self._dispatch(req, _peer_uid(conn))
                    except BrokerDenied as e:
                        resp = {"ok": False, "error": type(e).__name__,
                                "detail": str(e)}
                    except Exception:
                        # never leak internals (paths, crypto details) over
                        # the socket — callers get a generic denial
                        resp = {"ok": False, "error": "BrokerDenied",
                                "detail": "request refused"}
                except Exception:
                    resp = {"ok": False, "error": "malformed_request"}
                try:
                    conn.sendall((json.dumps(resp) + "\n").encode())
                except OSError:
                    pass

    def _dispatch(self, req: dict, peer_uid: int | None) -> dict:
        op = req.get("op")
        # Every socket op is peer-attested: an unresolvable or non-allowed
        # OS peer cannot lease, mint, or poll — REQ-CRED-02 (R3A-2).
        if op in ("lease", "mint", "poll", "fetch") and \
                (peer_uid is None or peer_uid not in self.allowed_uids):
            if self.audit is not None:
                self.audit.append("authorization_denied",
                                  payload={"reason": "peer_uid_rejected",
                                           "op": op})
            return {"ok": False, "error": "BrokerDenied",
                    "detail": "unattested peer"}
        if op == "ping":
            return {"ok": True, "epoch": round(self.epoch_now(), 3)}
        if op == "poll":
            self.check_client_clock(req.get("reported_time"))
            status = self.check_kill_switch(req.get("execution_id", ""),
                                            req.get("principal_id"))
            return {"ok": True, **status}
        if op == "fetch":
            try:
                value = self.fetch(req.get("token", ""),
                                   req.get("secret_id", ""),
                                   req.get("purpose", ""),
                                   reported_time=req.get("reported_time"),
                                   peer_uid=peer_uid)
                return {"ok": True, "value": value}
            except BrokerDenied as e:
                return {"ok": False, "error": type(e).__name__, "detail": str(e)}
        if op == "lease":
            # Full socket flow (REQ-CRED-02): the caller presents a live
            # session token; the broker binds the lease to that principal
            # and session. No master-key material leaves the broker.
            try:
                principal = self._require_principal(req.get("token", ""))
                lease = self.issue_execution_lease(
                    principal, execution_id=req.get("execution_id", ""),
                    connection_ids=list(req.get("connection_ids") or []),
                    ttl_s=int(req.get("ttl_s", 300)))
                return {"ok": True, "lease": lease.token}
            except BrokerDenied as e:
                return {"ok": False, "error": type(e).__name__, "detail": str(e)}
        if op == "mint":
            try:
                lease = self._parse_lease(req.get("lease", ""))
                self._validate_lease(lease)
                token = self.mint_capability_token(lease,
                                                   list(req.get("secret_ids") or []))
                return {"ok": True, "token": token}
            except BrokerDenied as e:
                return {"ok": False, "error": type(e).__name__, "detail": str(e)}
        return {"ok": False, "error": "unknown_op"}

    def _require_principal(self, session_token: str):
        if self.principal_validator is None:
            raise BrokerDenied("no principal validation configured")
        principal = self.principal_validator(session_token)
        if principal is None:
            raise BrokerDenied("invalid principal token")
        return principal

    def _parse_lease(self, lease_token: str) -> ExecutionLease:
        try:
            body_b64, sig = lease_token.rsplit(".", 1)
            payload = json.loads(b64d(body_b64))
        except Exception as e:
            raise LeaseInvalid("malformed lease") from e
        basis = json.dumps(payload, sort_keys=True).encode()
        expect = hmac_mod.new(self._hmac_key(), basis,
                              hashlib.sha256).hexdigest()
        if not hmac_mod.compare_digest(sig, expect):
            raise LeaseInvalid("invalid lease signature")
        if payload.get("typ") != "lease":
            raise LeaseInvalid("not a lease")
        return ExecutionLease(
            lease_id=payload["lid"], execution_id=payload["exec"],
            principal_id=payload["pid"], session_id=payload.get("sid", ""),
            connection_ids=list(payload.get("conns") or []),
            expires=payload["exp"])

    def serve_forever(self) -> None:
        """Blocking variant for `python -m anton.authz.broker serve`."""
        self.start()
        try:
            while True:
                time.sleep(3600)
        finally:
            self.stop()


# --------------------------------------------------------------------------

class BrokerClient:
    """Executor-side client. Fails closed: an unreachable broker raises
    BrokerDegraded('broker unavailable: ...') immediately — callers surface
    the degraded state instead of silently retrying (REQ-CRED-05)."""

    def __init__(self, socket_path: str, time_source=time.time):
        self.socket_path = socket_path
        self.time_source = time_source

    def call(self, obj: dict, timeout: float = 5.0) -> dict:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(self.socket_path)
        except (ConnectionRefusedError, FileNotFoundError, socket.timeout) as e:
            raise BrokerDegraded(f"broker unavailable: {e}") from e
        with s:
            s.sendall((json.dumps(obj) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        if not buf.strip():
            raise BrokerDegraded("broker unavailable: empty response")
        try:
            resp = json.loads(buf.decode())
        except (ValueError, UnicodeDecodeError) as e:
            # Fail closed with the degraded class, not a raw decode error
            # (review O-3).
            raise BrokerDegraded("broker unavailable: malformed response") from e
        if not resp.get("ok", False):
            err = resp.get("error", "")
            detail = resp.get("detail", "")
            if err == "TokenExpired":
                raise TokenExpired(detail or "expired")
            if err == "RevokedState":
                raise RevokedState(detail or "revoked")
            raise BrokerDenied(detail or err or "denied")
        return resp

    def ping(self) -> dict:
        return self.call({"op": "ping", "reported_time": self.time_source()})

    def fetch(self, token: str, secret_id: str, purpose: str) -> str:
        resp = self.call({"op": "fetch", "token": token,
                          "secret_id": secret_id, "purpose": purpose,
                          "reported_time": self.time_source()})
        return resp["value"]

    def poll_kill_switch(self, execution_id: str,
                         principal_id: str | None = None) -> dict:
        resp = self.call({"op": "poll", "execution_id": execution_id,
                          "principal_id": principal_id,
                          "reported_time": self.time_source()})
        return {"revoked": resp.get("revoked", False),
                "reason": resp.get("reason", "")}

    def issue_lease(self, session_token: str, execution_id: str,
                    connection_ids: list[str], ttl_s: int = 300) -> str:
        resp = self.call({"op": "lease", "token": session_token,
                          "execution_id": execution_id,
                          "connection_ids": connection_ids, "ttl_s": ttl_s})
        return resp["lease"]

    def mint(self, lease_token: str, secret_ids: list[str]) -> str:
        resp = self.call({"op": "mint", "lease": lease_token,
                          "secret_ids": secret_ids})
        return resp["token"]


def main() -> None:
    ap = argparse.ArgumentParser(prog="anton.authz.broker")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--db", required=True)
    serve.add_argument("--keys", required=True)
    serve.add_argument("--sock", required=True)
    serve.add_argument("--uid", action="append", type=int, default=None)
    args = ap.parse_args()
    if args.cmd == "serve":
        if not args.uid:
            # The broker can only attest executors it shares OS-identity
            # machinery with; a watchdog without wiring is a security
            # misconfiguration, not a deployment. Refuse to start rather
            # than serve actors with no grant/session validation (R5-7).
            print("refusing to start: broker serve requires --uid "
                  "(explicit executor OS identity); wire grant/session "
                  "validators in the application, not via standalone serve.",
                  file=sys.stderr)
            raise SystemExit(2)
        broker = CredentialBroker(args.db, args.keys, args.sock,
                                  allowed_uids=args.uid)
        print(f"broker serving on {args.sock}", flush=True)
        broker.serve_forever()


if __name__ == "__main__":
    main()
