"""QuickBooks OAuth end-to-end (handoff #5).

Completes the wizard's OAuth flow: exchanges the authorization code at
Intuit's token endpoint, stores access/refresh tokens ONLY as encrypted
broker secrets, records the grant with its granted OAuth scopes, and wires
revocation-triggered refresh rotation. The HTTP transport is injectable so
CI never touches the network; production uses httpx.

Credentials come from env (QBO_CLIENT_ID / QBO_CLIENT_SECRET) or the
operator's secrets.env (~/secrets/harwell/secrets.env on the Mac,
/home/umbrel/secrets/harwell/secrets.env on Umbrel).
"""
from __future__ import annotations

import base64
import os

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SECRETS_ENV_CANDIDATES = (
    os.path.expanduser("~/secrets/harwell/secrets.env"),
    "/home/umbrel/secrets/harwell/secrets.env",
)
# Vendor-bundled defaults: each deployment persists its own copy of the TDH
# Labs Intuit app credentials at provision time (0600), so customer installs
# are self-contained after setup.
VENDOR_OAUTH_FILE = "authz/oauth.vendor.json"


def _http_post_form(url: str, client_id: str, client_secret: str,
                    form: dict) -> dict:
    import httpx
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    r = httpx.post(url, data=form,
                   headers={"Authorization": f"Basic {basic}",
                            "Accept": "application/json"},
                   timeout=30)
    r.raise_for_status()
    return r.json()


def exchange_code(client_id: str, client_secret: str, code: str,
                  redirect_uri: str, transport=None) -> dict:
    transport = transport or _http_post_form
    return transport(TOKEN_URL, client_id, client_secret, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    })


def refresh_tokens(client_id: str, client_secret: str, refresh_token: str,
                   transport=None) -> dict:
    transport = transport or _http_post_form
    return transport(TOKEN_URL, client_id, client_secret, {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    })


def load_qbo_credentials() -> tuple[str, str]:
    """env first, then the operator's 0600 secrets.env files."""
    cid = (os.environ.get("ANTON_QBO_CLIENT_ID")
           or os.environ.get("QBO_CLIENT_ID") or "")
    csec = (os.environ.get("ANTON_QBO_CLIENT_SECRET")
            or os.environ.get("QBO_CLIENT_SECRET") or "")
    if cid and csec:
        return cid, csec
    for path in SECRETS_ENV_CANDIDATES:
        if not os.path.exists(path):
            continue
        found = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    found[k.strip()] = v.strip().strip('"').strip("'")
        cid = cid or found.get("QBO_CLIENT_ID", "")
        csec = csec or found.get("QBO_CLIENT_SECRET", "")
        if cid and csec:
            return cid, csec
    return "", ""


def load_vendor_credentials(data_dir: str) -> tuple[str, str]:
    """Deployment-local copy of the vendor (TDH Labs) Intuit app
    credentials, persisted at provision time. Precedence after env:
    authz/oauth.vendor.json -> SECRETS_ENV_CANDIDATES files."""
    vendor_path = os.path.expanduser("~/.secrets/qbo_vendor.json")
    if os.path.exists(vendor_path):
        import json as _json
        with open(vendor_path, encoding="utf-8") as f:
            d = _json.load(f)
        if d.get("client_id") and d.get("client_secret"):
            return d["client_id"], d["client_secret"]
    path = os.path.join(data_dir, VENDOR_OAUTH_FILE)
    if os.path.exists(path):
        import json as _json
        with open(path, encoding="utf-8") as f:
            d = _json.load(f)
        if d.get("client_id") and d.get("client_secret"):
            return d["client_id"], d["client_secret"]
    for cand in SECRETS_ENV_CANDIDATES:
        if not os.path.exists(cand):
            continue
        found = {}
        with open(cand, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    found[k.strip()] = v.strip().strip('"').strip("'")
        if found.get("QBO_CLIENT_ID") and found.get("QBO_CLIENT_SECRET"):
            persist_vendor_credentials(data_dir,
                                       found["QBO_CLIENT_ID"],
                                       found["QBO_CLIENT_SECRET"])
            return found["QBO_CLIENT_ID"], found["QBO_CLIENT_SECRET"]
    return "", ""


def persist_vendor_credentials(data_dir: str, client_id: str,
                               client_secret: str) -> None:
    """Persist the vendor Intuit app credentials deployment-local (0600)."""
    from .authz.secrets import write_private_file
    import json as _json
    vendor_path = os.path.expanduser("~/.secrets/qbo_vendor.json")
    if os.path.exists(vendor_path):
        import json as _json
        with open(vendor_path, encoding="utf-8") as f:
            d = _json.load(f)
        if d.get("client_id") and d.get("client_secret"):
            return d["client_id"], d["client_secret"]
    path = os.path.join(data_dir, VENDOR_OAUTH_FILE)
    write_private_file(path, _json.dumps(
        {"client_id": client_id, "client_secret": client_secret}, indent=2))


def store_tokens(broker, store, audit, actor, provider: str,
                 tokens: dict, connection_id: str | None = None) -> None:
    """Access/refresh tokens live only in the broker's encrypted store.
    Connection ownership is implicit (privileged tier); granted OAuth
    scopes are recorded for the hygiene diff (REQ-GRNT-01/04)."""
    from .authz.grants import record_connection_scopes
    conn_id = connection_id or provider
    broker.register_secret(f"{conn_id}:access_token",
                           tokens["access_token"], connection_id=conn_id)
    broker.register_secret(f"{conn_id}:refresh_token",
                           tokens["refresh_token"], connection_id=conn_id)
    scopes = [s for s in str(tokens.get("scope", "")).split() if s]
    record_connection_scopes(store, conn_id, scopes)


def wire_rotation(store, client_id: str, client_secret: str,
                  transport=None, sink=None) -> None:
    """Grant revocation triggers server-side refresh-token rotation
    (REQ-GRNT-01): rotate at Intuit, hand the new token to `sink` for
    re-encryption into the broker."""
    def rotator(connection_id: str) -> None:
        stored, _ = broker_refresh_lookup(store, connection_id)
        tokens = refresh_tokens(client_id, client_secret, stored,
                                transport=transport)
        new_rt = tokens["refresh_token"]
        broker = getattr(store, "broker", None)
        if broker is not None:
            broker.register_secret(f"{connection_id}:access_token",
                                   tokens["access_token"],
                                   connection_id=connection_id)
            broker.register_secret(f"{connection_id}:refresh_token", new_rt,
                                   connection_id=connection_id)
        if sink is not None:
            sink(connection_id, new_rt)
    store.token_rotator = rotator


def broker_refresh_lookup(store, connection_id: str) -> tuple[str, str]:
    """The rotator needs the current refresh token; it reads it through the
    broker registered on the store when wired by the dashboard."""
    broker = getattr(store, "broker", None)
    if broker is None:
        raise RuntimeError("no credential broker wired to this store")
    return broker.get_secret(f"{connection_id}:refresh_token")[0], connection_id
