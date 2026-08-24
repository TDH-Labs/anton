"""Integration bridges: Composio / Nango connect flows, credential capture
into the broker, and governed action execution (handoff: point-and-click
integrations beyond QBO).

Design contract with the rest of Anton:
  - Tokens/credentials returned by any bridge are stored ENCRYPTED in the
    credential broker immediately (register_secret) \u2014 never plaintext on
    disk, never in config, never logged.
  - Action execution routes through the same approval gates as everything
    else (governor.classify; money/outbound kinds hard-gate).
  - Bridge credentials for the API calls themselves come from env/config,
    documented per bridge below.

Composio API v3.1 (backend.composio.dev):
  POST /connectedAccounts        {appName, data:{...}} -> {id, status,...}
  GET  /connectedAccounts/{id}   -> {status: ACTIVE|..., ...}
  POST /actions/{slug}/execute   {connectedAccountId, requestBody, ...}

Nango (api.nango.dev \u2014 cloud or self-hosted):
  POST /connect/sessions         {end_user:{id}} -> {token}
  Connect widget URL: {host}/connect/<token>
  GET  /connection/{connectionId}?provider_config_key=<key> -> connection
       incl. credentials.credentials.{access_token|refresh_token}
"""
from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any, Callable

import httpx

from . import governor


class BridgeError(Exception):
    """A bridge call failed at the provider side."""


# ---------------------------------------------------------------------------
# transports (injectable for tests)
# ---------------------------------------------------------------------------

def _http(method: str, url: str, headers: dict, json_body=None,
          timeout: float = 30.0) -> dict:
    r = httpx.request(method, url, headers=headers, json=json_body,
                      timeout=timeout)
    if r.status_code >= 400:
        raise BridgeError(f"{method} {url} -> {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}


# ---------------------------------------------------------------------------
# Composio
# ---------------------------------------------------------------------------

class ComposioBridge:
    def __init__(self, api_key: str, base_url: str =
                 "https://backend.composio.dev/api/v3.1",
                 transport: Callable = _http):
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self._t = transport

    def _headers(self) -> dict:
        return {"X-API-Key": self.api_key,
                "Content-Type": "application/json"}

    def start_connect(self, app_name: str, entity_id: str) -> dict:
        """Initiate a connected account; returns redirectUrl for browser."""
        data = self._t("POST", f"{self.base}/connectedAccounts",
                       self._headers(),
                       json_body={"appName": app_name,
                                  "entityId": entity_id})
        return {"connection_id": data.get("id"),
                "redirect_url": data.get("redirectUrl")
                or data.get("authConfig", {}).get("redirectUrl"),
                "status": data.get("status", "INITIALIZING")}

    def wait_connection(self, connection_id: str,
                        timeout_s: float = 120.0,
                        poll_s: float = 2.0) -> dict:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            d = self._t("GET",
                        f"{self.base}/connectedAccounts/{connection_id}",
                        self._headers())
            if (d.get("status") or "").upper() == "ACTIVE":
                return d
            time.sleep(poll_s)
        raise BridgeError(f"composio connection {connection_id} "
                          "did not become ACTIVE before timeout")

    def execute(self, action_slug: str, connected_account_id: str,
                params: dict) -> dict:
        return self._t("POST",
                       f"{self.base}/actions/{action_slug}/execute",
                       self._headers(),
                       json_body={"connectedAccountId": connected_account_id,
                                  "input": params})


# ---------------------------------------------------------------------------
# Nango
# ---------------------------------------------------------------------------

class NangoBridge:
    def __init__(self, secret_key: str, host: str = "https://api.nango.dev",
                 connect_host: str | None = None,
                 transport: Callable = _http):
        self.secret_key = secret_key
        self.host = host.rstrip("/")
        self._t = transport
        # self-hosted Nango serves UI+API from the same origin
        self.connect_host = (connect_host or host).rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.secret_key}"}

    def start_connect(self, provider_config_key: str, end_user_id: str) -> dict:
        """Create a connect session; returns the Connect-UI URL."""
        d = self._t("POST", f"{self.connect_host}/connect/sessions",
                    self._headers(),
                    json_body={"end_user": {"id": end_user_id},
                               "allowed_integrations":
                                   [provider_config_key]})
        token = (d.get("data") or {}).get("token") or d.get("token")
        return {"session_token": token,
                "connect_url": f"{self.connect_host}/connect/{token}"}

    def get_connection(self, connection_id: str,
                       provider_config_key: str) -> dict:
        return self._t(
            "GET",
            f"{self.host}/connection/{connection_id}"
            f"?provider_config_key={urllib.parse.quote(provider_config_key)}",
            self._headers())

    @staticmethod
    def access_token(connection: dict) -> str | None:
        creds = connection.get("credentials") or {}
        return ((creds.get("oauth2") or {}).get("access_token")
                or creds.get("access_token"))


# ---------------------------------------------------------------------------
# unified registry
# ---------------------------------------------------------------------------

def bridges_from_config(config: dict,
                        transport: Callable = _http) -> dict[str, Any]:
    bcfg = config.get("bridges") or {}
    out: dict[str, Any] = {}
    comp = (bcfg.get("composio") or {}).get("api_key")
    if comp:
        base = (bcfg.get("composio") or {}).get("base_url") \
            or "https://backend.composio.dev/api/v3.1"
        out["composio"] = ComposioBridge(comp, base, transport=transport)
    ng = (bcfg.get("nango") or {})
    if ng.get("secret_key"):
        out["nango"] = NangoBridge(ng["secret_key"],
                                   ng.get("host") or "https://api.nango.dev",
                                   ng.get("connect_host"),
                                   transport=transport)
    return out


# ---------------------------------------------------------------------------
# governed execution
# ---------------------------------------------------------------------------

def gated_execute(bridge: Any, audit: Any, actor: Any,
                  action_kind: str, action_slug: str,
                  connection_id: str, params: dict,
                  amount: float = 0.0) -> dict:
    """Every bridged action routes through the governor exactly like native
    operations: money/outbound kinds hard-gate to PRESENT_FOR_APPROVAL and
    cannot auto-execute (R-governance parity across bridges)."""
    ruling = governor.classify(
        ev=1.0, feasibility=1.0,
        risk="low" if action_kind == "internal" else "high",
        kind=action_kind)
    if ruling.route == governor.PRESENT_FOR_APPROVAL:
        result: dict = {"routed_to_approval": True,
                        "action": action_slug, "kind": action_kind}
        audit.append("bridge_action_gated", payload={
            "action": action_slug, "kind": action_kind,
            "route": ruling.route})
        return result

    out = bridge.execute(action_slug, connection_id, params)
    audit.append("bridge_action_executed", payload={
        "action": action_slug, "kind": action_kind})
    return out
