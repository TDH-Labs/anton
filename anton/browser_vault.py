"""Encrypted credential storage for the "stored login" Add-ons connection type
-- the fallback for a service with no OAuth, MCP, or API key, where Anton has
to sign in like a person would.

A real login password is a different risk class than an AI provider key or a
scoped API token (dashboard.py's secrets.yaml, plain-file-plus-0600): it can
open a real account, so it's encrypted at rest here with Fernet
(cryptography's standard, maintained symmetric-encryption recipe), not just
permission-protected. The vault key itself follows the exact generate-once,
0600-write pattern docker/auth-gate.mjs's readOrCreate already uses for the
session secret.

get_credential() is for internal use only -- the login step (browser_login.py)
reads it to fill a form directly; it must never be returned from an API
response or interpolated into a prompt string handed to a model.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

_KEY_FILENAME = "browser-vault.key"
_VAULT_DIRNAME = "browser-vault"


def _key_path(install_dir: str) -> str:
    return os.path.join(install_dir, _KEY_FILENAME)


def _load_or_create_vault_key(install_dir: str) -> bytes:
    path = _key_path(install_dir)
    try:
        with open(path, "rb") as f:
            existing = f.read().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    key = Fernet.generate_key()
    os.makedirs(install_dir, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "wb") as f:
        f.write(key)
    return key


def _credential_path(install_dir: str, service_id: str) -> str:
    return os.path.join(install_dir, _VAULT_DIRNAME, f"{service_id}.enc")


def store_credential(install_dir: str, service_id: str, username: str, password: str) -> None:
    key = _load_or_create_vault_key(install_dir)
    fernet = Fernet(key)
    payload = f"{username}\n{password}".encode("utf-8")
    token = fernet.encrypt(payload)
    path = _credential_path(install_dir, service_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "wb") as f:
        f.write(token)


def get_credential(install_dir: str, service_id: str) -> tuple[str, str] | None:
    """Returns (username, password), or None if nothing is stored, the vault
    key doesn't match (moved install / corrupted key file), or the stored
    file is corrupted. Never raises on a missing or unreadable credential --
    callers treat that as "not connected yet", not a crash."""
    path = _credential_path(install_dir, service_id)
    try:
        with open(path, "rb") as f:
            token = f.read()
    except FileNotFoundError:
        return None
    key = _load_or_create_vault_key(install_dir)
    fernet = Fernet(key)
    try:
        payload = fernet.decrypt(token)
    except InvalidToken:
        return None
    username, _, password = payload.decode("utf-8").partition("\n")
    return username, password


def has_credential(install_dir: str, service_id: str) -> bool:
    return os.path.exists(_credential_path(install_dir, service_id))


def delete_credential(install_dir: str, service_id: str) -> None:
    try:
        os.remove(_credential_path(install_dir, service_id))
    except FileNotFoundError:
        pass
