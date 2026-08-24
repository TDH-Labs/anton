import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from anton import browser_vault


class TestBrowserVault(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "quickbooks", "alice", "hunter2")
            self.assertEqual(browser_vault.get_credential(install_dir, "quickbooks"),
                             ("alice", "hunter2"))

    def test_missing_credential_returns_none_not_a_crash(self):
        with tempfile.TemporaryDirectory() as install_dir:
            self.assertIsNone(browser_vault.get_credential(install_dir, "nope"))

    def test_vault_key_generated_once_and_reused(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "a", "u1", "p1")
            key_path = browser_vault._key_path(install_dir)
            first_key = open(key_path, "rb").read()
            browser_vault.store_credential(install_dir, "b", "u2", "p2")
            second_key = open(key_path, "rb").read()
            self.assertEqual(first_key, second_key)
            # both credentials still decrypt under the one reused key
            self.assertEqual(browser_vault.get_credential(install_dir, "a"), ("u1", "p1"))
            self.assertEqual(browser_vault.get_credential(install_dir, "b"), ("u2", "p2"))

    def test_key_file_and_credential_file_are_0600(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "svc", "u", "p")
            key_mode = stat.S_IMODE(os.stat(browser_vault._key_path(install_dir)).st_mode)
            cred_mode = stat.S_IMODE(
                os.stat(browser_vault._credential_path(install_dir, "svc")).st_mode)
            self.assertEqual(key_mode, stat.S_IRUSR | stat.S_IWUSR)
            self.assertEqual(cred_mode, stat.S_IRUSR | stat.S_IWUSR)

    def test_corrupted_credential_file_returns_none_not_a_crash(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "svc", "u", "p")
            path = browser_vault._credential_path(install_dir, "svc")
            with open(path, "wb") as f:
                f.write(b"not a valid fernet token")
            self.assertIsNone(browser_vault.get_credential(install_dir, "svc"))

    def test_wrong_key_cannot_decrypt_a_moved_vault(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "svc", "u", "p")
            # simulate a moved/regenerated key -- decrypt must fail closed, not crash
            key_path = browser_vault._key_path(install_dir)
            os.remove(key_path)
            # Isolate from the legacy parent fallback: the point here is that
            # a credential whose matching key is gone (regenerated/moved
            # install) fails closed even though SOME key can be created.
            with patch.object(browser_vault, "_legacy_base", return_value=None):
                self.assertIsNone(browser_vault.get_credential(install_dir, "svc"))

    def test_has_and_delete_credential(self):
        with tempfile.TemporaryDirectory() as install_dir:
            self.assertFalse(browser_vault.has_credential(install_dir, "svc"))
            browser_vault.store_credential(install_dir, "svc", "u", "p")
            self.assertTrue(browser_vault.has_credential(install_dir, "svc"))
            browser_vault.delete_credential(install_dir, "svc")
            self.assertFalse(browser_vault.has_credential(install_dir, "svc"))
            browser_vault.delete_credential(install_dir, "svc")  # must not raise twice

    def test_legacy_install_location_still_readable_after_storage_root_moves(self):
        """Umbrel fix: credentials used to be stored under dirname(data_dir)
        ("/" when ANTON_DATA_DIR=/data). New writes go inside the data dir,
        but pre-migration credentials -- and the legacy key file, which must
        be adopted rather than replaced -- stay readable through the new base."""
        with tempfile.TemporaryDirectory() as outer:
            data_dir = os.path.join(outer, "data")
            os.makedirs(data_dir)
            # Old-style install: vault lives next to the data dir.
            browser_vault.store_credential(outer, "svc", "alice", "hunter2")
            # The credential is readable through BOTH bases: at the legacy
            # location directly, and through the new data-dir base via the
            # legacy fallback.
            self.assertTrue(browser_vault.has_credential(outer, "svc"))
            self.assertTrue(browser_vault.has_credential(data_dir, "svc"))
            # Reading through the new data-dir base finds the legacy credential
            # and adopts the legacy key into the new location.
            self.assertEqual(browser_vault.get_credential(data_dir, "svc"),
                             ("alice", "hunter2"))
            self.assertEqual(
                open(browser_vault._key_path(data_dir), "rb").read(),
                open(browser_vault._key_path(outer), "rb").read())
            self.assertTrue(browser_vault.has_credential(data_dir, "svc"))

    def test_volume_root_base_has_no_parent_fallback(self):
        """ANTON_DATA_DIR=/data: base is a filesystem root (no parent), so
        there is no legacy location to fall back to and reads miss cleanly."""
        self.assertIsNone(browser_vault._legacy_base(os.sep))

    def test_service_ids_are_isolated(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "svc-a", "u1", "p1")
            browser_vault.store_credential(install_dir, "svc-b", "u2", "p2")
            self.assertEqual(browser_vault.get_credential(install_dir, "svc-a"), ("u1", "p1"))
            self.assertEqual(browser_vault.get_credential(install_dir, "svc-b"), ("u2", "p2"))


if __name__ == "__main__":
    unittest.main()
