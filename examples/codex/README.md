# Codex + Anton

Codex (OpenAI's CLI/cloud agent) reaches Anton the same way every local
harness does: a stdio MCP server.

## Files

- `AGENTS.md` — drop into the repo Claude Code-style guidance is also read
  by Codex (it honors AGENTS.md) teaching the "consult Anton first" rule.
- README (this file) — wiring + the two scheduling traps.

## 1. MCP wiring

Codex CLI reads MCP servers from `~/.codex/config.toml`:

```toml
[mcp_servers.anton]
command = "anton"
args = ["mcp"]
env = { "ANTON_BASE_URL" = "http://127.0.0.1:8799" }
```

(`ANTON_DASHBOARD_TOKEN` in env only when authz is on.)

## 2. `AGENTS.md`

```markdown
## Anton
This repo integrates Anton (MCP server "anton"): governance, memory,
initiative.

- Before moving money or sending an external message: call
  anton_pending_approvals. Pending match -> stop, report the approval id.
  Never auto-fire.
- Memory: anton_search_memory over guessing.
- Initiative: anton_propose_work when idle.
- Report only what happened. No fabricated sends/completions.
```

## 3. Scheduling — the trap

- **Codex cloud** has durable scheduled tasks (Automations). Use those if
  you want Codex itself driving cadence: create an Automation that runs
  the "check anton_pending_approvals / do what's due" prompt on a
  schedule.
- **Codex CLI has no scheduler.** On a CLI-only install, schedule via
  **system cron** calling `codex exec` (or `anton serve` directly). Do not
  claim the CLI schedules anything.

## Verification

- `codex exec "mcp.anton.status()"` → real status (or whatever your
  version's tool-call syntax is).
- Automation: create one, watch it fire on cadence and reach Anton's
  tools.
- CLI+cron: `crontab -l` shows the job; the ledger shows real runs.