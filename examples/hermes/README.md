# Hermes Agent + Anton

Hermes (this machine's `hermes` at `~/.local/bin/hermes`, config in
`~/.hermes/config.yaml`) has first-class MCP support. Add Anton as an MCP
server two ways — stdio for local, HTTP/SSE for remote.

## 1. Add the MCP server

```bash
# stdio (Hermes on the same host as the Anton dashboard — the default):
hermes mcp add anton \
  --command anton --args mcp \
  --env ANTON_BASE_URL=http://127.0.0.1:8799

# remote / via HTTP surface (Hermes on a different host):
hermes mcp add anton \
  --url http://<anton-host>:8877/sse \
  --auth header
```

(`--auth header` prompts for the Authorization header; use the Anton
dashboard token. For stdio, set `ANTON_DASHBOARD_TOKEN` in the
environment when authz is enabled.)

Verify with:

```bash
hermes mcp test anton
hermes mcp list
```

## 2. What Hermes gets

The 9 Anton tools: `anton_status`, `anton_list_jobs`,
`anton_pending_approvals`, `anton_recent_runs`, `anton_usage`,
`anton_search_memory`, `anton_propose_work`, `anton_steer_job`,
`anton_decide_approval`. The same three rules as every other harness
(see `../codex/AGENTS.md`):

1. Money/outbound → check `anton_pending_approvals` first; never auto-fire.
2. Memory → `anton_search_memory` over guessing.
3. Report only what happened.

## 3. Overlap note — Hermes has its own governance surfaces

Hermes ships its own `approvals`, `egress`, `secrets`, `security`,
`portal`, and even a `claw` subcommand — its own permission/approval
model, separate from Anton's. That is **fine and complementary, not a
conflict**: the two approve/decide queues are independent, and the
decision about which one governs a given flow is the operator's, made per
deployment. The `anton_*` tools exist so work that MUST hit Anton's
durable durable approval queue (money/outbound, audited in Anton's
ledger) still can, from inside Hermes — and Anton's queue is the one
that persists rows you answer from a phone when no session is open.

## Verification (real client, real service)

1. `hermes mcp test anton` → connection ok, 9 tools discovered.
2. `hermes -z "call anton_status"` → real payload from the live dashboard.
3. Money/outbound probe: ask Hermes to approve a `anton_decide_approval`
   without a person asking — it must refuse per the three rules, and
   Anton's `/api/approvals` must show the parked row either way.