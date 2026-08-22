import os
import tempfile
import unittest

from anton import browser_login, browser_vault
from anton.browser_login import BrowserDriver, LoginSelectors

SELECTORS = LoginSelectors(
    username_selector="#user", password_selector="#pass",
    submit_selector="#submit", success_selector="#logged-in-banner",
)


class FakeBrowserDriver(BrowserDriver):
    """Deterministic double: a tiny in-memory model of "is the success
    selector present", driven by scripted outcomes -- mirrors the
    WritingExecutor pattern already used for upskill.py's tests."""

    def __init__(self, *, fields_present=True, submit_present=True,
                logged_in_after_submit=True, already_logged_in=False):
        self.fields_present = fields_present
        self.submit_present = submit_present
        self.logged_in_after_submit = logged_in_after_submit
        self.already_logged_in = already_logged_in
        self.filled = {}
        self.clicked = []
        self.opened_profile_dir = None
        self.closed = False
        self._submitted = False

    def open_persistent_context(self, profile_dir: str) -> None:
        self.opened_profile_dir = profile_dir

    def goto(self, url: str) -> None:
        self.visited_url = url

    def fill(self, selector: str, value: str) -> bool:
        if not self.fields_present:
            return False
        self.filled[selector] = value
        return True

    def click(self, selector: str) -> bool:
        if not self.submit_present:
            return False
        self.clicked.append(selector)
        self._submitted = True
        return True

    def is_present(self, selector: str) -> bool:
        if selector == SELECTORS.success_selector:
            if self.already_logged_in:
                return True
            return self._submitted and self.logged_in_after_submit
        return False

    def close(self) -> None:
        self.closed = True


class BrowserLoginTestBase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.install_dir = self.dir.name

    def tearDown(self):
        self.dir.cleanup()


class TestPerformLogin(BrowserLoginTestBase):
    def test_no_credential_stored_is_not_a_crash(self):
        driver = FakeBrowserDriver()
        result = browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(result.status, "no_credential")
        # never even opened a browser for a connection with nothing stored
        self.assertIsNone(driver.opened_profile_dir)

    def test_successful_login_fills_real_stored_credentials(self):
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver()
        result = browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(result.status, "success")
        self.assertEqual(driver.filled["#user"], "alice")
        self.assertEqual(driver.filled["#pass"], "hunter2")
        self.assertTrue(driver.closed)  # driver always closed, even on success

    def test_uses_the_persistent_session_dir_for_this_service(self):
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver()
        browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(driver.opened_profile_dir,
                         browser_login.session_dir(self.install_dir, "quickbooks"))

    def test_already_logged_in_session_is_reused_without_resubmitting(self):
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver(already_logged_in=True)
        result = browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(result.status, "success")
        self.assertEqual(driver.filled, {})  # never touched the form
        self.assertEqual(driver.clicked, [])

    def test_mfa_or_captcha_reports_needs_human_not_a_fabricated_success(self):
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver(logged_in_after_submit=False)
        result = browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(result.status, "needs_human")
        self.assertTrue(driver.closed)

    def test_missing_username_field_reports_a_specific_error(self):
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver(fields_present=False)
        result = browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(result.status, "error")
        self.assertIn(SELECTORS.username_selector, result.detail)

    def test_missing_submit_control_reports_a_specific_error(self):
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver(submit_present=False)
        result = browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertEqual(result.status, "error")
        self.assertIn(SELECTORS.submit_selector, result.detail)

    def test_driver_is_always_closed_even_on_early_return(self):
        # no_credential path returns before open_persistent_context is even
        # called -- close() must still be safe to skip, not required, but
        # every path that DOES open a context must close it.
        browser_vault.store_credential(self.install_dir, "quickbooks", "alice", "hunter2")
        driver = FakeBrowserDriver(fields_present=False)
        browser_login.perform_login(
            self.install_dir, "quickbooks", "https://example.com/login", SELECTORS, driver=driver)
        self.assertTrue(driver.closed)


if __name__ == "__main__":
    unittest.main()
