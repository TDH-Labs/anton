"""Connections catalog: bundled entries, MCP registry sync, hosted-OAuth
bridges (Composio, Nango).

Goal: an abundant, Claude-style connection list. Three sources merge into
one catalog:
  1. BUNDLED -- curated, ships with Anton (always available offline).
  2. REGISTRY -- live sync from registry.modelcontextprotocol.io (the
     official MCP registry); cached to the data dir with a TTL so a dead
     network never breaks the UI.
  3. BRIDGES -- Composio / Nango hosted-OAuth app catalogs. One API key
     unlocks their whole SaaS tail (including QuickBooks) without us
     operating per-app OAuth registrations.
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers?limit=100"
CACHE_TTL_S = 6 * 3600
LAST_REGISTRY_ERROR = None

# transport: "remote-http" (URL + optional auth header) | "stdio" (command)
# auth: "oauth" (remote server handles it via browser) | "key" (user supplies
# a token we send as Authorization header) | "none"
BUNDLED: list[dict[str, Any]] = [
    {"id": "github", "name": "GitHub", "category": "developer", "transport": "remote-http",
     "url": "https://api.githubcopilot.com/mcp", "auth": "oauth",
     "what": "Repos, issues, PRs, CI runs"},
    {"id": "notion", "name": "Notion", "category": "productivity", "transport": "remote-http",
     "url": "https://mcp.notion.com/mcp", "auth": "oauth",
     "what": "Pages, databases, search"},
    {"id": "linear", "name": "Linear", "category": "developer", "transport": "remote-http",
     "url": "https://mcp.linear.app/sse", "auth": "oauth",
     "what": "Issues, projects, cycles"},
    {"id": "atlassian", "name": "Jira + Confluence", "category": "developer", "transport": "remote-http",
     "url": "https://mcp.atlassian.com/v1/sse", "auth": "oauth",
     "what": "Jira issues and Confluence spaces"},
    {"id": "sentry", "name": "Sentry", "category": "developer", "transport": "remote-http",
     "url": "https://mcp.sentry.dev/mcp", "auth": "oauth",
     "what": "Errors, releases, performance"},
    {"id": "cloudflare", "name": "Cloudflare", "category": "infrastructure", "transport": "remote-http",
     "url": "https://docs.mcp.cloudflare.com/sse", "auth": "oauth",
     "what": "Workers, DNS, zones documentation"},
    {"id": "filesystem", "name": "Filesystem", "category": "core", "transport": "stdio",
     "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."], "auth": "none",
     "what": "Read/write local files"},
    {"id": "playwright", "name": "Browser (Playwright)", "category": "core", "transport": "stdio",
     "command": ["npx", "-y", "@playwright/mcp@latest"], "auth": "none",
     "what": "Drive a real browser: click, fill, screenshot"},
    {"id": "postgres", "name": "PostgreSQL", "category": "data", "transport": "stdio",
     "command": ["npx", "-y", "@modelcontextprotocol/server-postgres"], "auth": "key",
     "keyHint": "postgresql://connection-string", "envKey": "DATABASE_URL",
     "what": "Read-only SQL against your database"},
    {"id": "sqlite", "name": "SQLite", "category": "data", "transport": "stdio",
     "command": ["uvx", "mcp-server-sqlite", "--db-path", "data.db"], "auth": "none",
     "what": "Query and update a SQLite file"},
    {"id": "slack-mcp", "name": "Slack", "category": "communication", "transport": "bridge",
     "bridge": "composio", "auth": "oauth",
     "what": "Channels, messages, reactions"},
    {"id": "gmail-mcp", "name": "Gmail", "category": "communication", "transport": "bridge",
     "bridge": "composio", "auth": "oauth",
     "what": "Send, search, label email"},
    {"id": "gcal-mcp", "name": "Google Calendar", "category": "productivity", "transport": "bridge",
     "bridge": "composio", "auth": "oauth",
     "what": "Events, scheduling, availability"},
    {"id": "gdrive-mcp", "name": "Google Drive", "category": "productivity", "transport": "bridge",
     "bridge": "composio", "auth": "oauth",
     "what": "Files, folders, sharing"},
    {"id": "quickbooks", "name": "QuickBooks", "category": "finance", "transport": "bridge",
     "bridge": "composio", "auth": "oauth",
     "what": "Invoices, bills, payments, chart of accounts"},
    {"id": "stripe", "name": "Stripe", "category": "finance", "transport": "bridge",
     "bridge": "composio", "auth": "oauth",
     "what": "Payments, customers, invoices"},
]


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> Any:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def bundled_catalog() -> list[dict[str, Any]]:
    return [dict(e) for e in BUNDLED]


def registry_servers(data_dir: str, force: bool = False) -> list[dict[str, Any]]:
    """Sync the official MCP registry. Cached to <data_dir>/mcp-registry-cache.json
    with a TTL; returns [] on any failure (network down must never break UI)."""
    cache_path = os.path.join(data_dir, "mcp-registry-cache.json")
    try:
        if not force and os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            if time.time() - cache.get("ts", 0) < CACHE_TTL_S:
                return cache.get("servers", [])
    except Exception:
        pass
    try:
        data = _http_json(REGISTRY_URL)
        servers = []
        for s in data.get("servers", []):
            entry = s.get("server") or s
            name = entry.get("name") or ""
            if not name:
                continue
            remote = (entry.get("remotes") or [{}])
            url = remote[0].get("url") if remote else None
            servers.append({
                "id": name.replace("/", "-").lower(),
                "name": name.split("/")[-1],
                "category": "registry",
                "transport": "remote-http" if url else "stdio",
                "url": url,
                "auth": "none",
                "what": (entry.get("description") or "")[:140],
                "source": "registry",
            })
        if servers:  # never cache an empty result -- a boot-time DNS failure
            tmp = cache_path + ".tmp"   # would poison the catalog for 6h
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "servers": servers}, f)
            os.replace(tmp, cache_path)
        return servers
    except Exception as e:
        global LAST_REGISTRY_ERROR
        LAST_REGISTRY_ERROR = f"{type(e).__name__}: {e}"
        # stale cache is better than nothing
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f).get("servers", [])
        except Exception:
            return []


def composio_apps(api_key: str, base_url: str = "https://backend.composio.dev/v1") -> list[dict[str, Any]]:
    """List Composio's app catalog (hundreds of SaaS, each becomes a connect card)."""
    data = _http_json(f"{base_url}/apps", {"X-API-Key": api_key})
    apps = data if isinstance(data, list) else data.get("items", [])
    out = []
    for a in apps[:400]:
        out.append({
            "id": f"composio:{a.get('appName') or a.get('name')}",
            "name": (a.get("meta", {}) or {}).get("displayName") or a.get("appName") or a.get("name"),
            "category": "saas",
            "transport": "bridge",
            "bridge": "composio",
            "auth": "oauth",
            "logo": (a.get("logo") or ""),
            "what": f"Connect {a.get('name')} via Composio hosted OAuth",
            "source": "composio",
        })
    return out


def nango_integrations(secret_key: str, base_url: str = "https://api.nango.dev") -> list[dict[str, Any]]:
    """List Nango integrations configured in the user's Nango account."""
    data = _http_json(f"{base_url}/config", {"Authorization": f"Bearer {secret_key}"})
    configs = data.get("configs", []) if isinstance(data, dict) else []
    out = []
    for c in configs:
        pid = c.get("unique_key") or c.get("provider")
        out.append({
            "id": f"nango:{pid}",
            "name": (c.get("display_name") or pid or "").title(),
            "category": "saas",
            "transport": "bridge",
            "bridge": "nango",
            "auth": "oauth",
            "what": f"Connect {pid} via Nango hosted OAuth",
            "source": "nango",
        })
    return out


def bridges_configured(config: dict) -> dict[str, bool]:
    bridges = config.get("bridges") or {}
    return {
        "composio": bool((bridges.get("composio") or {}).get("api_key")),
        "nango": bool((bridges.get("nango") or {}).get("secret_key")),
    }
