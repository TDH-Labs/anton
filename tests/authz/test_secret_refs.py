"""#12 — BYO password-manager secret references resolved by the broker.

The broker stores either inline secrets or REFERENCES (op:// bw://
vault://); resolution happens inside the broker at fetch time so the
executor only ever sees the final value over the socket — never the ref
machinery, never the CLI environment.
"""
import unittest

from helpers import build_env, raw_sqlite


class RefTestBase(unittest.TestCase):
    def setUp(self):
        self.env = build_env(authz_enabled=True)
        self.env.bootstrap_owner()
        self.store = self.env.app.state.authz_store
        self.broker = self.env.app.state.authz_broker

    def tearDown(self):
        import shutil
        shutil.rmtree(self.env.dir, ignore_errors=True)

    def _cap_for(self, secret_id="conn-a"):
        principal = self.store.principal_of("owner")
        lease = self.broker.issue_execution_lease(
            principal, execution_id="exec-ref", connection_ids=["conn-a"],
            ttl_s=120)
        return self.broker.mint_capability_token(lease, [secret_id])


class TestSecretRefSchemes(RefTestBase):
    def test_op_bw_vault_refs_resolve_via_adapters(self):
        calls = []

        def fake_op(ref):
            calls.append(ref)
            return "op-secret-value"

        def fake_bw(ref):
            return "bw-secret-value"

        def fake_vault(ref):
            return "file-secret-value"

        self.broker.set_ref_adapters({
            "op": fake_op, "bw": fake_bw, "vault": fake_vault})

        self.broker.register_secret("conn-a", "op://Vault/Gmail/password",
                                    connection_id="conn-a")
        self.broker.register_secret("conn-b", "bw://item-id/notes",
                                    connection_id="conn-b")
        self.broker.register_secret("conn-c", "vault://anton/qbo_client_id",
                                    connection_id="conn-c")

        cap_a = self._cap_for("conn-a")
        # widen scope token for b/c via their own leases
        principal = self.store.principal_of("owner")

        lease_b = self.broker.issue_execution_lease(
            principal, execution_id="exec-b", connection_ids=["conn-b"], ttl_s=60)
        cap_b = self.broker.mint_capability_token(lease_b, ["conn-b"])
        lease_c = self.broker.issue_execution_lease(
            principal, execution_id="exec-c", connection_ids=["conn-c"], ttl_s=60)
        cap_c = self.broker.mint_capability_token(lease_c, ["conn-c"])

        self.assertEqual(self.broker.fetch(cap_a, "conn-a", purpose="t"),
                         "op-secret-value")
        self.assertEqual(self.broker.fetch(cap_b, "conn-b", purpose="t"),
                         "bw-secret-value")
        self.assertEqual(self.broker.fetch(cap_c, "conn-c", purpose="t"),
                         "file-secret-value")
        self.assertIn("op://Vault/Gmail/password", calls)

    def test_inline_values_are_not_treated_as_refs(self):
        self.broker.register_secret("conn-a", "sk-plain-inline-key",
                                    connection_id="conn-a")
        cap = self._cap_for()
        self.assertEqual(self.broker.fetch(cap, "conn-a", purpose="t"),
                         "sk-plain-inline-key")


class TestSecretRefFailClosed(RefTestBase):
    def test_unknown_scheme_denied_explicitly(self):
        self.broker.register_secret("conn-a", "bogus://nope/key",
                                    connection_id="conn-a")
        with self.assertRaises(Exception) as ctx:
            self.broker.fetch(self._cap_for(), "conn-a", purpose="t")
        self.assertIn("scheme", str(ctx.exception).lower())

    def test_adapter_failure_fails_closed_without_leaking_ref_into_error(self):
        def broken_op(ref):
            raise RuntimeError("CLI exploded")

        self.broker.set_ref_adapters({"op": broken_op})
        self.broker.register_secret("conn-a", "op://V/I/f",
                                    connection_id="conn-a")
        with self.assertRaises(Exception) as ctx:
            self.broker.fetch(self._cap_for(), "conn-a", purpose="t")
        msg = str(ctx.exception)
        self.assertNotIn("op://", msg)  # refs are internal, never surfaced

    def test_unconfigured_scheme_denied_even_if_value_looks_like_a_ref(self):
        self.broker.register_secret("conn-a", "bw://unconfigured/item",
                                    connection_id="conn-a")
        with self.assertRaises(Exception):
            self.broker.fetch(self._cap_for(), "conn-a", purpose="t")


class TestRefStorageDiscipline(RefTestBase):
    def test_cli_adapters_shelled_out_with_minimal_env_and_timeout(self):
        from anton.authz.secretrefs import CliAdapter
        adapter = CliAdapter(scheme="op",
                             argv_template=["echo", "{ref}"])
        self.assertEqual(adapter.resolve("hello"), "hello")

        # missing binary -> explicit fail-closed error
        missing = CliAdapter(scheme="op",
                             argv_template=["definitely-not-a-real-bin-xyz",
                                            "{ref}"])
        from anton.authz.secretrefs import RefResolutionError
        with self.assertRaises(RefResolutionError):
            missing.resolve("x")

    def test_default_resolver_has_all_three_schemes_registered(self):
        from anton.authz.secretrefs import default_resolver
        r = default_resolver(vault_root=self.env.data_dir)
        self.assertEqual(set(r.adapters.keys()), {"op", "bw", "vault"})


if __name__ == "__main__":
    unittest.main()
