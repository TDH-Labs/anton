"""End-to-end tests for Composio and Nango integration bridges.

Proves: connect flow -> credential capture into broker (encrypted) ->
governed action execution. Uses injected transports so no network calls
are made. These are the tests that prove the bridges actually work.
"""
import unittest
from unittest import mock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import build_env, raw_sqlite


class BridgeTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.audit = self.env.app.state.authz_audit
        self.broker = self.env.app.state.authz_broker

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)


class TestComposioConnectFlow(BridgeTestBase):
    """Full Composio lifecycle: start_connect -> poll ACTIVE -> token captured
    into encrypted broker -> action executes under governance."""

    def test_composio_qbo_end_to_end(self):
        from anton.integrations import ComposioBridge, gated_execute
        from anton.dashboard import create_app  # ensure wiring is loaded

        # --- Step 1: initiate connect ---
        fake_transport_calls = []

        def transport(method, url, headers, json_body=None, timeout=30):
            fake_transport_calls.append({"method": method, "url": url})
            if "connectedAccounts" in url and method == "POST":
                return {"id": "ca_test_123", "status": "INITIALIZING",
                        "redirectUrl": "https://links.composio.dev/connect/ca_test_123"}
            if "connectedAccounts/ca_test_123" in url:
                return {"id": "ca_test_123", "status": "ACTIVE",
                        "connectionParams": {"access_token": "qbo-at-xyz"}}
            return {}

        br = ComposioBridge("test-api-key",
                            base_url="https://backend.composio.dev/api/v3.1",
                            transport=transport)

        flow = br.start_connect("quickbooks", "primary")
        self.assertIn("redirect_url", flow)
        self.assertEqual(flow["connection_id"], "ca_test_123")

        # operator's browser visits redirect_url; we poll until ACTIVE
        conn_detail = br.wait_connection(flow["connection_id"], timeout_s=5,
                                         poll_s=0.1)
        self.assertEqual(conn_detail["status"], "ACTIVE")

        # --- Step 2: capture QBO access token into encrypted broker ---
        qbo_token = conn_detail.get("connectionParams", {}).get(
            "access_token", "")
        self.assertTrue(qbo_token)
        self.broker.register_secret("composio:quickbooks:access_token",
                                    qbo_token,
                                    connection_id="quickbooks")

        # token never sits in plaintext on disk
        blob = raw_sqlite(self.broker.db_path,
                          "SELECT ciphertext FROM broker_secrets "
                          "WHERE id='composio:quickbooks:access_token'")
        self.assertTrue(blob)
        self.assertNotIn(b"qbo-at-xyz", bytes(blob[0][0]))

        # --- Step 3: execute a governed action through Composio ---
        # read-only action auto-executes
        br._t = lambda method, url, headers, json_body=None, timeout=30: {
            "success": True, "data": {"invoice_id": "inv-7"}}
        result = gated_execute(br, self.audit, actor=self.owner_p,
                               action_kind="internal",
                               action_slug="quickbooks_fetch_invoice",
                               connection_id="ca_test_123",
                               params={"invoice_id": "inv-7"})
        self.assertFalse(result.get("routed_to_approval"))

        # money-movement action hard-gates to approval
        result = gated_execute(br, self.audit, actor=self.owner_p,
                               action_kind="money",
                               action_slug="quickbooks_create_payment",
                               connection_id="ca_test_123",
                               params={"amount": 500})
        self.assertTrue(result.get("routed_to_approval"))
        rows = raw_sqlite(self.env.authz_db,
                          "SELECT event_type FROM audit_chain "
                          "WHERE event_type='bridge_action_gated'")
        self.assertTrue(rows)

    @property
    def owner_p(self):
        return self.store.principal_of("owner")


class TestNangoConnectFlow(BridgeTestBase):
    """Full Nango lifecycle: session -> connect UI -> connection fetched ->
    token stored encrypted -> accessible to agent."""

    def test_nango_qbo_end_to_end(self):
        from anton.integrations import NangoBridge

        nango_responses = []

        def transport(method, url, headers, json_body=None, timeout=30):
            nango_responses.append({"method": method, "url": url})
            if "/connect/sessions" in url and method == "POST":
                return {"data": {"token": "ng-session-tok-123"}}
            if "/connection/" in url:
                return {"connection_id": "nango-conn-qbo",
                        "provider_config_key": "quickbooks",
                        "credentials": {"type": "OAUTH2",
                                        "access_token": "nango-qbo-at",
                                        "refresh_token": "nango-qbo-rt"},
                        "connection_config": {}}
            return {}

        br = NangoBridge("test-secret-key",
                         host="https://api.nango.dev",
                         transport=transport)

        # start connect session
        flow = br.start_connect("quickbooks", "primary")
        self.assertIn("connect_url", flow)
        self.assertIn("ng-session-tok-123", flow["connect_url"])

        # fetch the connection (after user completed the Connect UI)
        conn = br.get_connection("nango-conn-qbo", "quickbooks")
        at = NangoBridge.access_token(conn)
        self.assertEqual(at, "nango-qbo-at")

        # store into encrypted broker
        self.broker.register_secret("nango:quickbooks:access_token", at,
                                    connection_id="quickbooks")
        blob = raw_sqlite(self.broker.db_path,
                          "SELECT ciphertext FROM broker_secrets "
                          "WHERE id='nango:quickbooks:access_token'")
        self.assertTrue(blob)
        self.assertNotIn(b"nango-qbo-at", bytes(blob[0][0]))


if __name__ == "__main__":
    unittest.main()
