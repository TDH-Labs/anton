"""The deterministic login step for a stored-login Add-ons connection.

This is scripted, not agent-driven: browser_vault's stored password is read
here and typed directly into the page by Anton's own code, never handed to
an LLM. Only the resulting *authenticated session* (a persistent browser
profile directory) is ever meant to be used by a later, separate dispatch --
that dispatch gets a browser that's already logged in, never the password
itself. Follow-up task work on top of that session is explicitly out of
scope here (see the plan) -- this module only produces and verifies the
session.

No universal login form exists to detect safely, so the three selectors
(username field, password field, submit control) and one success signal
come from the operator at connect-time, the same "operator supplies the
last-mile detail" pattern already used for OAuth's client_id.
"""
from __future__ import annotations

import abc
import dataclasses
import os
from typing import Optional

from . import browser_vault

_SESSIONS_DIRNAME = "browser-sessions"


@dataclasses.dataclass
class LoginSelectors:
    username_selector: str
    password_selector: str
    submit_selector: str
    success_selector: str  # present only once actually logged in


@dataclasses.dataclass
class LoginResult:
    status: str  # "success" | "needs_human" | "no_credential" | "error"
    detail: str = ""


def session_dir(install_dir: str, service_id: str) -> str:
    return os.path.join(install_dir, _SESSIONS_DIRNAME, service_id)


class BrowserDriver(abc.ABC):
    """What perform_login needs from a real browser -- narrow on purpose so
    a test double can stand in without a real Playwright/Chromium install,
    the same shape PiExecutor/OIExecutor's Executor abstraction already
    takes for a real vs. fake backing tool."""

    @abc.abstractmethod
    def open_persistent_context(self, profile_dir: str) -> None: ...

    @abc.abstractmethod
    def goto(self, url: str) -> None: ...

    @abc.abstractmethod
    def fill(self, selector: str, value: str) -> bool:
        """Returns False if the selector matched nothing."""

    @abc.abstractmethod
    def click(self, selector: str) -> bool:
        """Returns False if the selector matched nothing."""

    @abc.abstractmethod
    def is_present(self, selector: str) -> bool: ...

    @abc.abstractmethod
    def close(self) -> None: ...


class PlaywrightDriver(BrowserDriver):
    """The real driver. Imports playwright lazily -- this module (and its
    tests) must not require a Playwright/Chromium install just to be
    imported, matching how OIExecutor only requires `interpreter` when
    actually run, not at import time."""

    def __init__(self) -> None:
        self._playwright = None
        self._context = None
        self._page = None

    def open_persistent_context(self, profile_dir: str) -> None:
        from playwright.sync_api import sync_playwright
        os.makedirs(profile_dir, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            profile_dir, headless=True)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def goto(self, url: str) -> None:
        self._page.goto(url, wait_until="networkidle")

    def fill(self, selector: str, value: str) -> bool:
        locator = self._page.locator(selector).first
        if locator.count() == 0:
            return False
        locator.fill(value)
        return True

    def click(self, selector: str) -> bool:
        locator = self._page.locator(selector).first
        if locator.count() == 0:
            return False
        locator.click()
        self._page.wait_for_load_state("networkidle")
        return True

    def is_present(self, selector: str) -> bool:
        return self._page.locator(selector).first.count() > 0

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()


def perform_login(install_dir: str, service_id: str, login_url: str,
                  selectors: LoginSelectors, *, driver: Optional[BrowserDriver] = None) -> LoginResult:
    credential = browser_vault.get_credential(install_dir, service_id)
    if credential is None:
        return LoginResult("no_credential", "no stored credential for this connection")
    username, password = credential

    driver = driver or PlaywrightDriver()
    profile_dir = session_dir(install_dir, service_id)
    try:
        driver.open_persistent_context(profile_dir)
        driver.goto(login_url)

        if driver.is_present(selectors.success_selector):
            return LoginResult("success", "already logged in (persisted session reused)")

        if not driver.fill(selectors.username_selector, username):
            return LoginResult("error", f"username field not found: {selectors.username_selector}")
        if not driver.fill(selectors.password_selector, password):
            return LoginResult("error", f"password field not found: {selectors.password_selector}")
        if not driver.click(selectors.submit_selector):
            return LoginResult("error", f"submit control not found: {selectors.submit_selector}")

        if driver.is_present(selectors.success_selector):
            return LoginResult("success", "logged in")

        # Not an error -- an MFA prompt or CAPTCHA is a real, expected
        # outcome for plenty of sites, not something to push through
        # silently or fabricate success for.
        return LoginResult("needs_human",
                           "login did not reach the success signal -- likely MFA, a "
                           "CAPTCHA, or the selectors need adjusting")
    finally:
        driver.close()
