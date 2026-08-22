import os
import stat
import tempfile
import unittest

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
            self.assertIsNone(browser_vault.get_credential(install_dir, "svc"))

    def test_has_and_delete_credential(self):
        with tempfile.TemporaryDirectory() as install_dir:
            self.assertFalse(browser_vault.has_credential(install_dir, "svc"))
            browser_vault.store_credential(install_dir, "svc", "u", "p")
            self.assertTrue(browser_vault.has_credential(install_dir, "svc"))
            browser_vault.delete_credential(install_dir, "svc")
            self.assertFalse(browser_vault.has_credential(install_dir, "svc"))
            browser_vault.delete_credential(install_dir, "svc")  # must not raise twice

    def test_service_ids_are_isolated(self):
        with tempfile.TemporaryDirectory() as install_dir:
            browser_vault.store_credential(install_dir, "svc-a", "u1", "p1")
            browser_vault.store_credential(install_dir, "svc-b", "u2", "p2")
            self.assertEqual(browser_vault.get_credential(install_dir, "svc-a"), ("u1", "p1"))
            self.assertEqual(browser_vault.get_credential(install_dir, "svc-b"), ("u2", "p2"))


if __name__ == "__main__":
    unittest.main()
