#!/usr/bin/env python3
"""QBO Sandbox scaffold \u2014 OAuth 2.0 authorization_code flow + sandbox API calls.

Runnable companion to https://developer.intuit.com/app/developer/quickstart.
Secrets come from environment variables (QBO_CLIENT_ID / QBO_CLIENT_SECRET);
tokens persist to tokens.json (0600, gitignored) so each subcommand runs
standalone. Never hardcode the client secret anywhere.

Endpoints per Intuit docs:
  authorize: https://appcenter.intuit.com/connect/oauth2
  tokens:    https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer
  accounting:https://sandbox-quickbooks.api.intuit.com/v3/company/<realmId>/...
  openid:    https://sandbox-accounts.platform.intuit.com/v1/openid_connect/userinfo
  payments:  https://sandbox.api.intuit.com/quickbooks/v4/payments/charges
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.parse

import httpx

TOKENS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.json")
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
ACCOUNTING_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"
OPENID_USERINFO = "https://sandbox-accounts.platform.intuit.com/v1/openid_connect/userinfo"
PAYMENTS_CHARGES = "https://sandbox.api.intuit.com/quickbooks/v4/payments/charges"


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def creds() -> tuple[str, str]:
    cid = os.environ.get("QBO_CLIENT_ID", "")
    csec = os.environ.get("QBO_CLIENT_SECRET", "")
    if not (cid and csec):
        die("set QBO_CLIENT_ID and QBO_CLIENT_SECRET (see .env.example); "
            "never commit the secret")
    return cid, csec


def _basic(cid: str, csec: str) -> str:
    return "Basic " + base64.b64encode(f"{cid}:{csec}".encode()).decode()


def load_tokens() -> dict:
    try:
        with open(TOKENS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        die("no tokens.json \u2014 run `exchange` first")


def save_tokens(tokens: dict) -> None:
    tokens["stored_at"] = int(time.time())
    fd = os.open(TOKENS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"tokens saved to {TOKENS_FILE} (access expires in "
          f"{tokens.get('expires_in', '?')}s)")


def token_post(form: dict) -> dict:
    cid, csec = creds()
    r = httpx.post(TOKEN_URL, data=form,
                   headers={"Authorization": _basic(cid, csec),
                            "Content-Type": "application/x-www-form-urlencoded"},
                   timeout=30)
    if r.status_code != 200:
        die(f"token endpoint returned {r.status_code}: {r.text[:300]}")
    return r.json()


# ---------------------------------------------------------------- commands

def cmd_auth_url(args) -> None:
    redirect = args.redirect_uri or os.environ.get(
        "QBO_REDIRECT_URI", "https://developer.intuit.com/app/developer/quickstart")
    state = os.urandom(8).hex()
    q = urllib.parse.urlencode({
        "client_id": creds()[0],
        "scope": args.scope,
        "redirect_uri": redirect,
        "response_type": "code",
        "state": state,
    })
    url = f"{AUTH_URL}?{q}"
    print("Open this URL in a browser, sign in to your SANDBOX company, approve:\n")
    print(url)
    print("\nAfter approving you land on the Intuit QuickStart page \u2014 copy the "
          "`code=` value from its address bar, then run:\n")
    print(f"  python sandbox.py exchange --code PASTED_CODE")


def cmd_exchange(args) -> None:
    redirect = args.redirect_uri or os.environ.get(
        "QBO_REDIRECT_URI", "https://developer.intuit.com/app/developer/quickstart")
    tokens = token_post({
        "grant_type": "authorization_code",
        "code": args.code,
        "redirect_uri": redirect,
    })
    save_tokens(tokens)
    print(f"realmId: {tokens.get('realmId', '(none)')} \u2014 use it for --realmId steps")


def refresh_token_if_needed(tokens: dict) -> dict:
    age = time.time() - tokens.get("stored_at", 0)
    if age < int(tokens.get("expires_in", 1800)) - 60:
        return tokens
    print("access token stale \u2014 refreshing...")
    new = token_post({"grant_type": "refresh_token",
                      "refresh_token": tokens["refresh_token"]})
    new["realmId"] = tokens.get("realmId")
    save_tokens(new)
    return new


def authed_headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json"}


def cmd_companyinfo(args) -> None:
    if not args.realmId:
        die("--realmId required (printed by exchange, or your sandbox company id)")
    tokens = refresh_token_if_needed(load_tokens())
    url = f"{ACCOUNTING_BASE}/{args.realmId}/companyinfo/{args.realmId}"
    r = httpx.get(url, headers=authed_headers(tokens), timeout=30)
    print(json.dumps(r.json(), indent=2) if r.status_code == 200
          else die(f"{r.status_code}: {r.text[:300]}"))


def cmd_userinfo(args) -> None:
    tokens = refresh_token_if_needed(load_tokens())
    r = httpx.get(OPENID_USERINFO, headers=authed_headers(tokens), timeout=30)
    print(json.dumps(r.json(), indent=2) if r.status_code == 200
          else die(f"{r.status_code}: {r.text[:300]}"))


def cmd_charge(args) -> None:
    tokens = refresh_token_if_needed(load_tokens())
    realm = tokens.get("realmId") or die("no realmId on stored tokens")
    card = {
        "card": {"expMonth": "12", "expYear": "2026",
                 "number": "4111111111111111", "name": "Test User"},
        "amount": str(args.amount),
        "currency": "usd",
        "context": {"mobile": "false", "isEcommerce": "true"},
    }
    r = httpx.post(PAYMENTS_CHARGES, json=card, headers={
        **authed_headers(tokens),
        "Content-Type": "application/json",
        "Request-Id": f"sandbox-{int(time.time())}",
    }, timeout=30)
    print(json.dumps(r.json(), indent=2) if r.status_code in (200, 201)
          else die(f"{r.status_code}: {r.text[:400]}"))


def cmd_refresh(args) -> None:
    tokens = load_tokens()
    new = token_post({"grant_type": "refresh_token",
                      "refresh_token": tokens["refresh_token"]})
    new["realmId"] = tokens.get("realmId")
    save_tokens(new)


def main() -> None:
    p = argparse.ArgumentParser(prog="sandbox")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auth-url", help="print the authorize URL (step 1)")
    a.add_argument("--scope", default="com.intuit.quickbooks.accounting "
                                      "com.intuit.quickbooks.payment openid "
                                      "profile email phone address")
    a.add_argument("--redirect-uri", default=None)
    a.set_defaults(fn=cmd_auth_url)

    x = sub.add_parser("exchange", help="swap authorization code for tokens (step 2)")
    x.add_argument("--code", required=True)
    x.add_argument("--redirect-uri", default=None)
    x.set_defaults(fn=cmd_exchange)

    ci = sub.add_parser("companyinfo", help="GET sandbox company info (step 3a)")
    ci.add_argument("--realmId", required=True)
    ci.set_defaults(fn=cmd_companyinfo)

    ui = sub.add_parser("userinfo", help="GET OpenID user identity (step 3b)")
    ui.set_defaults(fn=cmd_userinfo)

    ch = sub.add_parser("charge", help="POST sandbox test charge (step 3c)")
    ch.add_argument("--amount", type=float, default=5.00)
    ch.set_defaults(fn=cmd_charge)

    rf = sub.add_parser("refresh", help="force token refresh (step 4)")
    rf.set_defaults(fn=cmd_refresh)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
