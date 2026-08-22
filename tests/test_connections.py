"""Tests for the layered connections system (anton/connections.py +
dashboard /api/connections/* endpoints)."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anton.connections import (BUNDLED, bridges_configured, bundled_catalog,
                               composio_apps, nango_integrations,
                               registry_servers)


class _Ctx(unittest.TestCase):
    def setUp(self):
        self.data_dir = "/tmp/anton-test-connections"
        os.makedirs(self.data_dir, exist_ok=True)
        # clean cached registry between tests
        cache = os.path.join(self.data_dir, "mcp-registry-cache.json")
        if os.path.exists(cache):
            os.remove(cache)

    def _app(self, config=None):
        from anton.dashboard import create_app
        from fastapi.testclient import TestClient
        from anton.db import init_db
        db = os.path.join(self.data_dir, "isolation.db")
        init_db(db)
        cfg = config or {}
        return TestClient(create_app(engine=mock.MagicMock(), data_dir=self.data_dir, config=cfg))


class TestCatalog(_Ctx):
    def test_bundled_has_core_entries_and_shape(self):
        cat = bundled_catalog()
        ids = {e["id"] for e in cat}
        for must in ("github", "notion", "filesystem", "playwright", "quickbooks"):
            self.assertIn(must, ids)
        for e in cat:
            self.assertIn(e["transport"], ("remote-http", "stdio", "bridge"))
            if e["transport"] == "remote-http":
                self.assertTrue(e["url"].startswith("https://"))
            if e["transport"] == "stdio":
                self.assertIsInstance(e["command"], list)

    def test_registry_sync_failure_degrades_to_empty_not_crash(self):
        with mock.patch("anton.connections._http_json", side_effect=OSError("net down")):
            self.assertEqual(registry_servers(self.data_dir), [])

    def test_registry_sync_caches_and_survives_network_loss(self):
        payload = {"servers": [{"server": {"name": "acme/thing",
                                           "description": "Does things",
                                           "remotes": [{"url": "https://x/mcp"}]}}]}
        with mock.patch("anton.connections._http_json", return_value=payload):
            servers = registry_servers(self.data_dir)
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["id"], "acme-thing")
        self.assertEqual(servers[0]["transport"], "remote-http")
        # second call: network dies, cache answers
        with mock.patch("anton.connections._http_json", side_effect=OSError):
            again = registry_servers(self.data_dir)
        self.assertEqual(again[0]["id"], "acme-thing")

    def test_bridges_configured(self):
        self.assertEqual(bridges_configured({}), {"composio": False, "nango": False})
        cfg = {"bridges": {"composio": {"api_key": "k"}, "nango": {}}}
        b = bridges_configured(cfg)
        self.assertTrue(b["composio"])
        self.assertFalse(b["nango"])

    def test_composio_apps_maps_fields(self):
        payload = [{"appName": "quickbooks", "logo": "l.png", "meta": {"displayName": "QuickBooks"}}]
        with mock.patch("anton.connections._http_json", return_value=payload):
            apps = composio_apps("key")
        self.assertEqual(apps[0]["id"], "composio:quickbooks")
        self.assertEqual(apps[0]["bridge"], "composio")

    def test_nango_integrations_maps_fields(self):
        payload = {"configs": [{"unique_key": "hubspot", "display_name": "HubSpot"}]}
        with mock.patch("anton.connections._http_json", return_value=payload):
            apps = nango_integrations("sk")
        self.assertEqual(apps[0]["id"], "nango:hubspot")
        self.assertEqual(apps[0]["bridge"], "nango")


class TestConnectionsEndpoints(_Ctx):
    def test_catalog_requires_token_when_token_set(self):
        client = self._app({"general": {"dashboard_token": "sekret"}})
        r = client.get("/api/connections/catalog")
        self.assertEqual(r.status_code, 401)
        r = client.get("/api/connections/catalog", headers={"Authorization": "Bearer sekret"})
        self.assertEqual(r.status_code, 200)

    def test_catalog_returns_bundled_without_network(self):
        with mock.patch("anton.connections._http_json", side_effect=OSError):
            client = self._app()
            r = client.get("/api/connections/catalog?registry=1")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body["connections"]), len(BUNDLED))
        self.assertIn("bridges", body)

    def test_catalog_includes_bridge_apps_when_configured(self):
        cfg = {"bridges": {"composio": {"api_key": "k"}, "nango": {"secret_key": "s"}}}
        with mock.patch("anton.dashboard.composio_apps", return_value=[
                {"id": "composio:quickbooks", "name": "QuickBooks", "category": "finance",
                 "transport": "bridge", "auth": "oauth", "what": "", "source": "composio"}]), \
             mock.patch("anton.dashboard.nango_integrations", return_value=[]):
            client = self._app(cfg)
            r = client.get("/api/connections/catalog?registry=0")
        body = r.json()
        self.assertTrue(body["bridges"]["composio"])
        self.assertTrue(any(c["id"] == "composio:quickbooks" for c in body["connections"]))

    def test_connect_persists_and_shows_in_mcp_list(self):
        client = self._app()
        r = client.post("/api/connections/connect", json={
            "id": "github", "name": "GitHub", "what": "Repos, PRs",
            "url": "https://api.githubcopilot.com/mcp", "auth": "oauth"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "connected")
        listed = client.get("/api/wizard/mcp").json()
        github = [m for m in listed if m["id"] == "github"]
        self.assertEqual(len(github), 1)
        perms = github[0]["permissions"]
        self.assertEqual(perms.get("url"), "https://api.githubcopilot.com/mcp")

    def test_connect_is_idempotent(self):
        client = self._app()
        body = {"id": "notion", "name": "Notion", "url": "https://mcp.notion.com/mcp"}
        self.assertEqual(client.post("/api/connections/connect", json=body).status_code, 200)
        self.assertEqual(client.post("/api/connections/connect", json=body).status_code, 200)
        listed = [m for m in client.get("/api/wizard/mcp").json() if m["id"] == "notion"]
        self.assertEqual(len(listed), 1)


if __name__ == "__main__":
    unittest.main()
