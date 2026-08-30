# opencode + Anton

opencode is a local agent that already speaks MCP. Add Anton as a local
MCP server in `~/.config/opencode/opencode.json` (or your project's
`opencode.json`):

```json
{
  "mcp": {
    "anton": {
      "type": "local",
      "command": ["anton", "mcp"],
      "enabled": true,
      "environment": {
        "ANTON_BASE_URL": "http://127.0.0.1:8799"
      }
    }
  }
}
```

Add `ANTON_DASHBOARD_TOKEN` to `environment` only when the install has
authz enabled.

## What opencode gets

The 9 Anton tools: status, list jobs, pending approvals, recent runs,
usage, search memory, propose work, steer job, decide approval. The same
three rules as
every other harness apply (see `../codex/AGENTS.md` — the rules are
harness-agnostic):

1. Money/outbound → check `anton_pending_approvals` first, never auto-fire.
2. Memory → `anton_search_memory` over guessing.
3. Only report what happened.

## Verification

- `opencode` interactive → `/mcp` → `anton` listed with 9 tools.
- Ask it to `anton_status` → real output against the running dashboard.