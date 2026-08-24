"""Real-browser E2E for Portal Connections' sidecar engine.

Skipped automatically when Playwright/Chromium is unavailable — everything
else in the suite runs on driver fakes; THIS module is the one place that
proves the real PlaywrightDriver works end-to-end: scripted stored-login
against a genuinely served website (a local fake portal), then a live
session-health check through the persisted profile.

No third-party sites, no real credentials: the "portal" is localhost.
"""
import http.server
import json
import os
import shutil
import tempfile
import threading
import unittest

LOGIN_PAGE = """<!doctype html><html><body>
<form id="f" method="GET" action="/dashboard.html">
  <input id="user" name="u"><input id="pass" name="p">
  <button id="go" type="submit">Sign in</button>
</form></body></html>"""

DASHBOARD_PAGE = """<!doctype html><html><body>
<div id="dashboard">Welcome back</div></body></html>"""


def _handler(root):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=root, **kw)

        def log_message(self, *a):  # keep test output clean
            pass
    return H


class _Site:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="portal-site-")
        with open(os.path.join(self.root, "login.html"), "w") as f:
            f.write(LOGIN_PAGE)
        with open(os.path.join(self.root, "dashboard.html"), "w") as f:
            f.write(DASHBOARD_PAGE)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                      _handler(self.root))
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.root, ignore_errors=True)


def _chromium_available() -> bool:
    try:
        from anton.browser_login import PlaywrightDriver
    except Exception:
        return False
    driver = PlaywrightDriver()
    try:
        driver.open_persistent_context(tempfile.mkdtemp(prefix="pw-probe-"))
        driver.goto("about:blank")
        return True
    except Exception:
        return False
    finally:
        try:
            driver.close()
        except Exception:
            pass


@unittest.skipUnless(_chromium_available(),
                     "playwright + chromium not installed")
class TestRealBrowserPortalEngine(unittest.TestCase):
    def setUp(self):
        self.site = _Site()
        self.install_dir = tempfile.mkdtemp(prefix="portal-e2e-install-")

    def tearDown(self):
        self.site.stop()
        shutil.rmtree(self.install_dir, ignore_errors=True)

    def _portal_row(self):
        return {
            "name": "fakeportal",
            "base_url": self.site.base + "/dashboard.html",
            "login_url": self.site.base + "/login.html",
            "selectors_json": json.dumps({"success_selector": "#dashboard"}),
        }

    def test_scripted_login_produces_a_live_session_the_guardian_confirms(self):
        from anton import browser_vault
        from anton.browser_login import LoginSelectors, perform_login
        from anton.authz.portal import check_session_health

        browser_vault.store_credential(self.install_dir, "fakeportal",
                                       "alice", "hunter2")
        result = perform_login(
            self.install_dir, "fakeportal", self._portal_row()["login_url"],
            LoginSelectors(username_selector="#user",
                           password_selector="#pass",
                           submit_selector="#go",
                           success_selector="#dashboard"))
        self.assertEqual(result.status, "success", result.detail)

        # guardian: same persistent profile, real driver, must see the
        # authenticated session still alive
        health = check_session_health(self.install_dir, self._portal_row())
        self.assertTrue(health["healthy"], health["detail"])
        self.assertFalse(health["needs_reauth"])

    def test_guardian_fails_closed_when_no_session_was_ever_established(self):
        from anton.authz.portal import check_session_health

        # nothing was ever stored for this portal (no credential, no
        # profile): the check must report stale/needs_reauth — never fake OK
        health = check_session_health(self.install_dir, self._portal_row())
        self.assertFalse(health["healthy"])
        self.assertIn(health["status"], ("stale",))


if __name__ == "__main__":
    unittest.main()
