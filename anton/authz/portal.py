"""Portal Connections — first-class management of legacy-website browser
sessions inside Anton (handoff: ProCare, Gusto, WatchMeGrow).

Each portal connection represents a website that requires human browser
authentication (no API available). A persistent Chrome profile maintains
the session; declarative YAML operations turn site interactions into
agent-callable tools; a session guardian monitors cookie health and
alerts before expiry.

Architecture:
  - Portal connections live as registered entries in Anton's authZ store
    (the `portals` table — sanctioned additive migration in store.py)
  - The Playwright engine + MCP server run as a SIDECAR (separate process);
    this module owns identity, governance, and fleet visibility only
  - Registration/deregistration require `connections.connect`
    (Approver tier and above) and are WORM-audited
  - The session guardian fails closed: no stored credential, missing
    success selector, or driver error is reported as needing re-auth,
    never silently swallowed
  - Guardian alerts land in authz_alerts + the audit chain; Telegram
    routing is deployment wiring (same shape as egress senders)

Credentials and persistent profiles reuse the stored-login Add-ons
machinery (browser_vault / browser_login): the password never leaves the
encrypted vault, and only the resulting authenticated session is ever used.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import time

from . import rbac

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_MIN_GUARDIAN_INTERVAL_S = 60


class PortalError(Exception):
    pass


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_capability(actor, capability: str, store, audit, what: str) -> None:
    """Same fail-closed gate as egress.require_capability: unknown/roleless
    actors are denied and the denial is audit-chained."""
    if not rbac.can(getattr(actor, "role", None), capability):
        audit.append("authorization_denied", actor=actor, payload={
            "reason": "missing_capability", "capability": capability,
            "what": what})
        raise PermissionError(f"{what} requires capability {capability}")


def _validate(name: str, base_url: str, login_url: str,
              guardian_interval_s: int, selectors: dict | None,
              cookie_domains: list[str] | None,
              operations_file: str | None) -> tuple[dict, list[str], dict]:
    """Input validation shared by register + re-register. Returns the
    normalized selectors/domains. Raises PortalError on any violation."""
    if not _NAME_RE.match(name or ""):
        raise PortalError(
            f"invalid portal name {name!r}: lowercase letters, digits and "
            f"dashes only (must start alphanumeric)")
    for label, url in (("base_url", base_url), ("login_url", login_url)):
        if url and not url.startswith(("http://", "https://")):
            raise PortalError(f"{label} must be an http(s) URL")
    if not base_url:
        raise PortalError("base_url is required")
    if int(guardian_interval_s) < _MIN_GUARDIAN_INTERVAL_S:
        raise PortalError(
            f"guardian_interval_s must be >= {_MIN_GUARDIAN_INTERVAL_S}")
    selectors = selectors or {}
    if not isinstance(selectors, dict):
        raise PortalError("selectors must be a mapping")
    cookie_domains = cookie_domains or []
    if not isinstance(cookie_domains, list) or \
            not all(isinstance(d, str) for d in cookie_domains):
        raise PortalError("cookie_domains must be a list of strings")
    ops = load_operations(operations_file) if operations_file else []
    return selectors, cookie_domains, {"operations": ops}


# ---------------------------------------------------------------------------
# Registration & lifecycle
# ---------------------------------------------------------------------------

def register_portal(store, audit, actor, name: str, base_url: str,
                    login_url: str = "", selectors: dict | None = None,
                    cookie_domains: list[str] | None = None,
                    guardian_interval_s: int = 3600,
                    operations_file: str | None = None) -> dict:
    """Register (or re-register) a portal connection. Requires
    connections.connect. Re-registration updates configuration in place
    and reactivates; every write is audit-chained."""
    _require_capability(actor, "connections.connect", store, audit,
                        "portal.register")
    selectors_n, domains_n, _ops = _validate(
        name, base_url, login_url, guardian_interval_s, selectors,
        cookie_domains, operations_file)
    with store.lock:
        store.conn.execute(
            "INSERT INTO portals(name, base_url, login_url, selectors_json,"
            " cookie_domains_json, guardian_interval_s, operations_file,"
            " registered_by, created, active)"
            " VALUES(?,?,?,?,?,?,?,?,?,1)"
            " ON CONFLICT(name) DO UPDATE SET base_url=excluded.base_url,"
            " login_url=excluded.login_url,"
            " selectors_json=excluded.selectors_json,"
            " cookie_domains_json=excluded.cookie_domains_json,"
            " guardian_interval_s=excluded.guardian_interval_s,"
            " operations_file=excluded.operations_file,"
            " registered_by=excluded.registered_by, active=1",
            (name, base_url, login_url, json.dumps(selectors_n),
             json.dumps(domains_n), int(guardian_interval_s),
             operations_file, actor.principal_id, _now()))
        store.conn.commit()
    audit.append("portal_registered", actor=actor,
                 payload={"name": name, "url": base_url})
    return get_portal(store, name)


def deregister_portal(store, audit, actor, name: str) -> None:
    """Deactivate a portal connection. Requires connections.connect.
    Soft-deactivation (active=0), not deletion: registration history stays
    queryable and the audit chain stays truthful."""
    _require_capability(actor, "connections.connect", store, audit,
                        "portal.deregister")
    row = get_portal(store, name)
    if row is None:
        raise KeyError(f"no such portal {name}")
    with store.lock:
        store.conn.execute(
            "UPDATE portals SET active=0 WHERE name=?", (name,))
        store.conn.commit()
    audit.append("portal_deregistered", actor=actor, payload={"name": name})


def get_portal(store, name: str) -> dict | None:
    row = store.conn.execute(
        "SELECT * FROM portals WHERE name=?", (name,)).fetchone()
    return dict(row) if row else None


def list_portals(store, active_only: bool = True) -> list[dict]:
    try:
        rows = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='portals'").fetchone()
        if not rows:
            return []
        sql = "SELECT * FROM portals"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY name"
        return [dict(r) for r in store.conn.execute(sql)]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Declarative YAML operations
# ---------------------------------------------------------------------------

def load_operations(operations_file: str | None) -> list[dict]:
    """Parse a portal's declarative operations file. Each operation is
    `{name, description?, steps: [...]}`; names must be slugs. The sidecar
    MCP server turns these into agent-callable tools; here we only validate
    that the file parses and is shaped sanely (fail-closed at registration,
    not at first use)."""
    if not operations_file:
        return []
    if not os.path.exists(operations_file):
        raise PortalError(f"operations file not found: {operations_file}")
    import yaml
    try:
        with open(operations_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PortalError(f"operations file is not valid YAML: {e}") from e
    ops = data.get("operations") if isinstance(data, dict) else data
    if ops is None:
        ops = []
    if not isinstance(ops, list):
        raise PortalError("operations file must contain a list of operations")
    seen: set[str] = set()
    for op in ops:
        if not isinstance(op, dict) or not op.get("name"):
            raise PortalError("every operation needs a name")
        opname = str(op["name"])
        if not _NAME_RE.match(opname):
            raise PortalError(f"invalid operation name {opname!r}")
        if opname in seen:
            raise PortalError(f"duplicate operation name {opname!r}")
        seen.add(opname)
        steps = op.get("steps")
        if not isinstance(steps, list) or not steps:
            raise PortalError(f"operation {opname!r} needs non-empty steps")
    return ops


# ---------------------------------------------------------------------------
# Session health / guardian
# ---------------------------------------------------------------------------

def check_session_health(install_dir: str, portal: dict, *,
                         driver=None) -> dict:
    """Check whether the portal's persisted session is still alive.

    Fail-closed contract: anything other than positive proof of a live
    session reports healthy=False. `needs_reauth` distinguishes "the
    session/credential is gone — a human must log in again" from a
    transient check error (`status="error"`).
    """
    from .. import browser_login, browser_vault
    name = portal["name"]
    credential = browser_vault.get_credential(install_dir, name)
    if credential is None:
        return {"healthy": False, "needs_reauth": True,
                "detail": "no stored credential for this portal",
                "status": "stale"}
    selectors = json.loads(portal.get("selectors_json") or "{}")
    success_selector = selectors.get("success_selector")
    if not success_selector:
        return {"healthy": False, "needs_reauth": True,
                "detail": "no success_selector registered for this portal",
                "status": "stale"}
    own_driver = driver is None
    if driver is None:
        driver = browser_login.PlaywrightDriver()
    try:
        driver.open_persistent_context(browser_login.session_dir(install_dir, name))
        driver.goto(portal["base_url"])
        alive = driver.is_present(success_selector)
    except Exception as e:  # transient network/browser failure is NOT proof of expiry
        return {"healthy": False, "needs_reauth": False,
                "detail": f"health check failed: {type(e).__name__}",
                "status": "error"}
    finally:
        if own_driver:
            try:
                driver.close()
            except Exception:
                pass
    return {"healthy": bool(alive), "needs_reauth": not alive,
            "detail": "" if alive else "success signal absent — session expired",
            "status": "healthy" if alive else "stale"}


def record_health_result(store, audit, portal_name: str, result: dict) -> None:
    """Persist a health-check outcome and alert on expiry. Alerts land in
    both authz_alerts (fleet visibility) and the WORM chain."""
    with store.lock:
        store.conn.execute(
            "UPDATE portals SET last_health_status=?, last_health_ts=? "
            "WHERE name=?",
            (result.get("status"), _now(), portal_name))
        store.conn.commit()
    if result.get("needs_reauth"):
        store.add_alert("portal_reauth_needed",
                        f"{portal_name}: {result.get('detail', '')}")
        audit.append("portal_session_stale", payload={
            "portal": portal_name, "detail": result.get("detail", "")})


def run_guardian_sweep(store, audit, install_dir: str, *, now=None,
                       driver_factory=None) -> list[dict]:
    """One guardian pass over every ACTIVE portal whose check interval has
    elapsed (portals never checked are immediately due). Returns one result
    dict per checked portal. Deployment wires this into the scheduler /
    a periodic job; it deliberately does NOT self-schedule."""
    checked: list[dict] = []
    now = now if now is not None else time.time()
    for portal in list_portals(store, active_only=True):
        last_ts = portal.get("last_health_ts")
        if last_ts:
            try:
                last_epoch = dt.datetime.strptime(
                    last_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=dt.timezone.utc).timestamp()
            except ValueError:
                last_epoch = 0.0
            if now - last_epoch < portal["guardian_interval_s"]:
                continue  # not due yet
        driver = driver_factory() if driver_factory else None
        try:
            result = check_session_health(install_dir, portal, driver=driver)
        finally:
            if driver is not None:
                try:
                    driver.close()
                except Exception:
                    pass
        record_health_result(store, audit, portal["name"], result)
        checked.append({"portal": portal["name"], **result})
    return checked
