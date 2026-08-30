# pi + Anton

pi is already Anton's default executor (`anton/executor/pi_executor.py`
invokes `pi -ne -ns --tools ...`), and pi **deliberately has no MCP**
(see the pi README: "No MCP. Build CLI tools with READMEs — Skills"). So
the pi install is not MCP wiring — it is a **skill** that teaches pi the
Anton surface, plus the executors that were already built.

## The skill

Drop `anton-skill/` into your pi skill directory. It teaches pi the three
rules and the eight tool equivalents over Anton's HTTP API, since pi has
no MCP client but does have read/bash (per its executor `tools` grant):

1. **Money/outbound** → GET `anton_pending_approvals` equivalent
   (`/api/approvals`) before acting; never auto-fire.
2. **Memory** → `/api/vault/note?slug=...` over guessing.
3. **Report only what happened**; no fabricated sends.

## The executors (already built)

`ANTON_EXECUTOR` selects what runs a task:

- `pi` (default) — read-only tools by default (`general.pi_tools`).
- `opencode` — multi-provider agent, MCP support, for browser-tool jobs.
- `n8n` — dispatch to a workflow in your own n8n (webhook).
- `oi`, `ssh`, `fake` — open-interpreter, remote host, test stub.

You don't install pi *into* Anton — Anton already drives pi. This folder
exists so a pi user knows they don't need anything else: the integration
ships in the product.

## Verification

- `anton run --task "say what you are doing" --executor pi` → a ledger row
  with real exit code/output, not a fake success.