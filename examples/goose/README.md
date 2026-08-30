# Goose + Anton

## What this gives you

A Goose recipe that pairs Goose (your execution surface) with Anton
(governance + memory + initiative). Goose keeps its own schedule, its own
tools, its own interface; Anton keeps the approval queue, the ledger, the
second brain, and the drive. The recipe makes Goose *consult* Anton before
the two things that must not auto-fire: money and outbound messages.

## Files

- `anton-recipe.yaml` — the recipe. Copy to `~/.config/goose/recipes/`
  (or your `GOOSE_RECIPES_DIR`).
- README (this file) — extension wiring + the SmartApprove question.

## 1. Wire the MCP extension

Add an entry under `extensions:` in `~/.config/goose/config.yaml`:

```yaml
extensions:
  anton:
    enabled: true
    type: stdio
    cmd: anton
    args:
      - mcp
    env_keys:
      - ANTON_BASE_URL
      # ANTON_DASHBOARD_TOKEN is read from the environment when authz is on
```

Environment (put in your shell profile or the service that launches
Goose):

```bash
export ANTON_BASE_URL="http://127.0.0.1:8799"   # running dashboard
export ANTON_DASHBOARD_TOKEN="<token>"          # only if install has authz
```

**Remote Goose** (Goose on a different host than Anton): use the SSE
surface instead of stdio, exactly like n8n:

```bash
# on the Anton host:
anton mcp --transport sse --port 8877 --token "$ANTON_DASHBOARD_TOKEN"
```

```yaml
extensions:
  anton:
    enabled: true
    type: streamable_http   # or sse, per your Goose version's support
    uri: http://<anton-host>:8877/sse
    timeout: 300
```

## 2. Run the recipe

```
goose recipe add anton-recipe.yaml   # or copy into recipes/ dir
goose run anton
```

The recipe's `instructions` are the contract: check
`anton_pending_approvals` before money/outbound; use
`anton_search_memory` for memory; propose rather than auto-send.

## 3. The SmartApprove question — status: unverified, do not claim

Goose has a real permission system (Chat/Auto/Approve/SmartApprove and a
stacked ToolInspectionManager). **But scheduled/headless runs set
`GOOSE_MODE=auto`, which auto-approves every tool call** — the gate exists
and is switched off exactly where Anton lives. Anton's approval is
durable/asynchronous (a row a person answers from their phone); Goose's is
synchronous/session-scoped (asks the person at the keyboard).

The ideal wiring: a Goose extension that participates in the inspector
chain and returns "requires approval" backed by Anton's approvals table,
so an unattended Goose run parks a decision instead of auto-approving.

**We have not verified Goose's extension API can hook that chain.** Until
a real Gooose install proves it, the recipe's fallback is the contract
that ships: call `anton_pending_approvals` before any money/outbound step,
and Anton refuses the dispatch until approved. The fallback is safe but
weaker — it cannot *prevent* Goose from acting on its own; it can only
make Anton's side refuse. Document any finding from a real test here.

## Verification (this repo's rule: real client, real service)

1. `goose extension list | grep anton` → shows the extension.
2. `goose` interactive → `/mcp` → click anton → tools listed.
3. Headless: schedule the recipe, `GOOSE_MODE=auto`, and confirm a money
   action parks an approval row instead of firing (fallback contract) —
   or, if the inspector-hook extension lands, that Goose asks Anton.