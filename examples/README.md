# Anton — install kit for every harness

Anton is a governance + memory + initiative service. Its MCP server
(`anton mcp`) is the universal seam; each subfolder here is the thin
install for one harness. Every wrapper is deliberately small: it makes the
harness *reach* Anton when relevant — it does not wrap every prompt
through it, and it never reimplements Anton.

## Transports (decide which one your harness speaks)

| Transport | Command | Use when |
|---|---|---|
| `stdio` | `anton mcp` (default) | The harness runs on the same host as Anton's dashboard — Claude Code, Codex, opencode, Goose (local), pi path |
| `sse` | `anton mcp --transport sse --token <T>` | The harness cannot spawn a subprocess — n8n's MCP client node, Claude Desktop URL, remote Goose |
| `http` | `anton mcp --transport http --token <T>` | Streamable HTTP clients (newer n8n, some remote harnesses) |

HTTP transports **require a token** (`--token` or `ANTON_DASHBOARD_TOKEN`)
and bind loopback by default — `--host 0.0.0.0` only when network exposure
is a deliberate operator decision (put it behind TLS / an approved proxy).

The MCP server talks to the **running** dashboard (`--base-url
http://127.0.0.1:8799`, or `ANTON_BASE_URL`) rather than building its own
engine — same reason the webhook receiver, inbox, and scheduler all share
one process view. It serves 8 tools:

`anton_status`, `anton_list_jobs`, `anton_pending_approvals`,
`anton_recent_runs`, `anton_usage`, `anton_search_memory`,
`anton_steer_job`, `anton_decide_approval`.

## The installs

| Harness | Folder | Transport |
|---|---|---|
| Goose | `goose/` | stdio (local) / SSE (remote) |
| Claude Code | `claude-code/` | stdio |
| Codex CLI | `codex/` | stdio |
| opencode | `opencode/` | stdio |
| n8n | `n8n/` (MCP client node) | SSE |
| Claude Desktop | `claude-desktop/` | stdio command or URL |
| pi (executor, no MCP by design) | `pi/` | skill + executors |

## The one rule that matters everywhere

**Money/outbound never auto-fires.** Before calling `anton_decide_approval`
or proceeding past a `anton_pending_approvals` hit, a person must have
asked. Anton's approval queue is durable and asynchronous — it parks rows
you answer from a phone; a harness in `auto` mode does not get to bypass
it, because Anton's own gate refuses the dispatch.

## Verification status

- MCP server: driven end-to-end by a real MCP client against a live
  container (test suite). SSE transport smoke-tested live in this branch.
- n8n Gate + Auditor templates (`n8n/anton-gate.json`,
  `n8n/anton-auditor.json`): verified container-to-container against a
  real n8n.
- Goose recipe: written against the installed Goose schema (real Goose
  install on this machine); recipe itself needs a live run to call
  "verified".
- The rest: wiring files ready for a real-client check on your machine —
  see each folder's README for the exact verification command, per this
  repo's rule that "green locally" is not evidence.