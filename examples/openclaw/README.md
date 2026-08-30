# OpenClaw + Anton

OpenClaw (this machine's `openclaw` at `~/.local/bin/openclaw`, state in
`~/.openclaw/openclaw.json`, gateway + ACP-native) manages MCP servers via
`openclaw mcp set`. Add Anton as a server:

## 1. Add the MCP server

```bash
# stdio (OpenClaw on the same host as the Anton dashboard — the default):
openclaw mcp set anton '{
  "command": "anton",
  "args": ["mcp"]
}'

# remote / via HTTP surface (different host):
openclaw mcp set anton '{
  "type": "http",
  "url": "http://<anton-host>:8877/mcp",
  "headers": { "Authorization": "Bearer <token>" }
}'
```

Verify:

```bash
openclaw mcp show anton
openclaw mcp list
```

## 2. What OpenClaw gets

The 9 Anton tools: `anton_status`, `anton_list_jobs`,
`anton_pending_approvals`, `anton_recent_runs`, `anton_usage`,
`anton_search_memory`, `anton_propose_work`, `anton_steer_job`,
`anton_decide_approval`. The same three rules (see
`../codex/AGENTS.md`):

1. Money/outbound → check `anton_pending_approvals` first; never auto-fire.
2. Memory → `anton_search_memory` over guessing.
3. Report only what happened.

## 3. Overlap note — OpenClaw has its own `approvals`

OpenClaw's `openclaw approvals` (exec approvals on the gateway/node host)
is its own synchronous approval model — the operator at the keyboard
approves an action before it runs. Anton's is durable/asynchronous: rows
parked for hours, answered from a phone when no session is open. For
**unattended, scheduled, or background OpenClaw work** (no gateway
approver watching), the Anton queue is the one that persists — route
money/outbound through `anton_pending_approvals` /
`anton_decide_approval` for exactly that case, and keep
`openclaw approvals` for interactive use. Both can coexist; the choice is
per-deployment.

## Verification (real client, real service)

1. `openclaw mcp show anton` → server present with 9 tools.
2. `openclaw agent` (or your regular prompt) ask it to call `anton_status`
   → real payload from the live dashboard.
3. Scheduled/background probe: an unattended OpenClaw run that hits
   money/outbound must consult Anton and stop at a parked approval, not
   auto-fire.