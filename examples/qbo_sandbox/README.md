# QBO Sandbox Scaffold (OAuth 2.0 authorization_code)

Runnable companion to Intuit's Developer QuickStart \u2014 four commands,
secrets loaded from environment variables, tokens cached to an untracked
tokens.json (0600) between steps.

## One-time setup

    cd examples/qbo_sandbox
    cp .env.example .env          # fill in your client id/secret
    set -a; source .env; set +a   # export into environment

## Flow

1. Authorize:      python sandbox.py auth-url     # open printed URL in browser,
                   # pick your SANDBOX company, approve; copy the ?code= value
2. Exchange:       python sandbox.py exchange --code PASTE_CODE_HERE
3. Company info:   python sandbox.py companyinfo --realmId YOUR_REALM_ID
4. User identity:  python sandbox.py userinfo
5. Test charge:    python sandbox.py charge --amount 5.00
6. Refresh:        python sandbox.py refresh

Tokens auto-refresh before expiry when you run any authenticated step.
