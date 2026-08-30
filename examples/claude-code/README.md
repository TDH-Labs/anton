# Claude Code + Anton

Wire Anton's MCP server into Claude Code as an `mcpServers` entry. Stdio
works because both run on the same host.

## 1. Add the MCP server

`claude mcp add anton -- stdio anton mcp`

Or via `.mcp.json` in the project:

```json
{
  "mcpServers": {
    "anton": {
      "command": "anton",
      "args": ["mcp"],
      "env": {
        "ANTON_BASE_URL": "http://127.0.0.1:8799",
        "ANTON_DASHBOARD_TOKEN": ""
      }
    }
  }
}
```

(`ANTON_DASHBOARD_TOKEN` is only needed when authz is enabled; leave blank
otherwise. Put the real value in the environment rather than the file when
secrets policy matters.)

## 2. What Claude Code gets

- `anton_pending_approvals` — the durable queue; consult before any
  money/outbound step you were asked to take.
- `anton_search_memory` — the second brain; trust it over your recall.
- `anton_steer_job` / `anton_decide_approval` — the operator's powers;
  treat `decide_approval` as releasing real money/outbound: only act when
  the person asked.
- `anton_propose_work` — what Anton thinks is worth doing next.
- `anton_status` / `anton_recent_runs` / `anton_usage` — what Anton is
  doing and what it cost.

## 3. The scheduling trap — read before relying on it

Claude Code's in-session `CronCreate` is **session-only, expires after 7
days, and fires only while the REPL is idle**. It is NOT a durable
scheduler and must never be presented as one. If this Claude Code install
is expected to run Anton's work on a cadence, use Claude's **durable
scheduled-agent path**, or system cron calling `anton serve` — never
in-session CronCreate for anything that must survive.

## 4. Skills (optional but recommended)

A tiny skill file teaching the "consult Anton first" posture:

`CLAUDE.md` in the project (or the equivalent in your skill dir):

```markdown
## Anton integration
This project uses Anton (MCP server "anton") for governance, memory, and
initiative.
- Before any action that moves money or sends an external message: call
  anton_pending_approvals. If a matching approval is pending, stop and
  report its id. Never auto-fire through a modal or CLI shortcut.
- For memory, prefer anton_search_memory over reconstructing context.
- Only report work that actually happened. No fabricated "sent" or "done".
```

## Verification

- `claude mcp list` → `anton` present.
- `claude` interactive → ask it to call `anton_status` → real output.
- Scheduled path: set the durable schedule, confirm it fires on its own
  cadence and calls Anton's tools — not just that it was created.