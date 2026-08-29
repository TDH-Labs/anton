# Build prompt: Anton as a governance layer for any harness

Paste everything below the line into a fresh session working in this repo.
It is written to be self-contained — it assumes no memory of the work that
produced it.

---

You are working in `/Users/ai/harbor-sas`, a git repo tracking
`github.com/TDH-Labs/anton`. Anton is a self-contained AI agent product for
small businesses, deployed by its owner on a real Umbrel NAS.

Your task is to make Anton usable **from inside any agent harness the
customer already runs** — Goose, Claude Code, Codex, n8n — instead of being
an invisible service they must adopt in place of their existing tools.

## The architecture you are implementing

Three layers. The line between them is **whether the capability needs a real
runtime**, and it is not negotiable — it was established by testing, not
preference.

**Layer 1 — Anton core: governance and memory.** A Python service. Owns the
approval gate, the ledger, budgets, the second brain, self-upskilling, the
opportunity scanner, and RBAC. Exposed to the outside world over MCP.

**Layer 2 — the harness: execution, scheduling, and the surface the user
already knows.** Goose / Claude Code / Codex / n8n supply cron and the UI.
Anton does **not** duplicate them; it keeps its own scheduler only as the
fallback for a headless install with no harness.

**Layer 3 — n8n: the user's own visual, deterministic workflows.** Distinct
from Anton's meta-workflows. The customer builds their business automations
there visually; Anton dispatches to them and gates them.

### Why capabilities land where they do

- **Scheduling → harness.** The entire point is that work shows up as cron
  jobs in a tool the user already opens.
- **Upskilling → core, cannot distribute.** `anton/upskill.py`'s
  `verify_research` counts files actually on disk precisely so it never
  trusts the dispatched agent's own claim, and `anton/sandbox.py`'s
  `run_sandbox_gate` copies the generated script to a temp dir, runs
  `py_compile` in a clean environment, then executes it against a golden
  payload in a clean-env subprocess. Neither survives as a recipe or a
  workflow node.
- **Initiative → core proposes, harness executes.** `anton/opportunity.py`
  needs the second brain to know what is worth doing; running the result
  belongs to the harness.
- **Second brain → core**, surfaced as MCP tools so every harness inherits
  memory.
- **User workflows → n8n**, gated by the Gate workflow in `examples/n8n/`.

## What already exists — verified, do not rebuild

- `anton/mcp_server.py` — `anton mcp` serves 8 tools over stdio
  (`anton_status`, `anton_list_jobs`, `anton_pending_approvals`,
  `anton_recent_runs`, `anton_usage`, `anton_search_memory`,
  `anton_steer_job`, `anton_decide_approval`). It calls Anton's HTTP surface
  rather than importing `JobEngine`, deliberately: the dashboard process owns
  the DB connections and the authz middleware, and a second in-process engine
  would hold a private view of state the real scheduler cannot see. Driven
  end-to-end by a real MCP client against a live container.
- `anton/job_state.py` — durable in-flight state (`running_jobs`) and
  operator steering (`job_state`): pause / resume / run-now / skip-next,
  consulted by `JobEngine.due_jobs`.
- `anton/governor.py` — `HARD_GATE_KINDS = {"money", "outbound"}`.
- `anton/scheduler.py` — `_is_approved` consumes an HMAC-signed approval
  once, inside `BEGIN IMMEDIATE`; `enforce_budget` returns a breach reason
  that blocks dispatch; `_provider_block` gates on
  `Executor.requires_model_provider`.
- `anton/executor/n8n_executor.py` — dispatches a job to an n8n workflow
  webhook. Verified container-to-container against a real n8n.
- `examples/n8n/anton-gate.json` and `anton-auditor.json` — a working
  approval gate (money/outbound never auto-clear) and an hourly auditor that
  deactivates workflows which skip it.
- `anton/web/` — Anton's own React Ops Center, served by `dashboard.py`.
- `tests/conftest.py` — suite-wide environment neutralization. Read it
  before writing tests.

## What to build, in order

### 1. Harden the MCP server as the single integration seam

It is currently stdio-only and assumes a reachable dashboard.

- Add the second brain write path. `anton_search_memory` reads one note by
  slug; add search across the vault and a gated write. A harness with no
  memory is the main thing this whole design is meant to fix.
- Add `anton_propose_work`: surface what `opportunity.py` has found, so a
  harness can ask "what should I be doing?" and get Anton's answer.
- Decide and document whether to add an HTTP/SSE transport alongside stdio.
  Goose extensions and n8n's MCP client node may not both speak stdio to a
  container. **Check this before designing around it.**
- Ship an `.mcpb` bundle so Claude Desktop installs it by double-click. A
  small-business owner will not edit JSON.

### 2. The Goose integration

Goose is Rust, Apache 2.0, under the Linux Foundation's Agentic AI
Foundation. **Do not fork it.** This repo just finished deleting a 234-package
vendored fork of another harness and the debt that came with it; a Rust fork
of a foundation-governed project would be a harder version of the same
mistake.

Build instead:

- **A Goose Recipe** (`examples/goose/anton.yaml`). The recipe format is
  `version, title, description, instructions, prompt, activities, parameters,
  extensions, settings, response, retry, sub_recipes`. Wire Anton's MCP
  server in `extensions`. Verify the field names against Goose's current
  reference before writing — do not trust this list blindly.
- **The SmartApprove redirect.** This is the interesting part. Goose has a
  real permission system — modes Chat/Auto/Approve/SmartApprove and a stacked
  `ToolInspectionManager` (Security → Egress → Adversary → Permission →
  Repetition). But **scheduled and headless Goose runs set `GOOSE_MODE=auto`,
  which auto-approves everything**, because there is nobody at the keyboard.
  That is precisely the gap Anton fills: its approval is asynchronous and
  durable, answered hours later from a phone.

  Investigate whether a Goose extension can participate in that inspector
  chain and return "requires approval" backed by Anton's approvals table,
  turning an unattended Goose run into one that parks a decision instead of
  auto-approving it. **If Goose's extension API cannot do this, say so
  plainly and fall back** to: the recipe calls `anton_pending_approvals`
  before acting on anything money/outbound, and Anton refuses the dispatch
  until approved. Do not claim the redirect works without proving it.

### 3. Claude Code, Codex, n8n

- **Claude Code**: a plugin or skill wiring the MCP server, plus scheduled
  agents. **Trap:** Claude Code's in-session `CronCreate` is session-only,
  expires after 7 days, and fires only while the REPL is idle — it cannot be
  Anton's scheduler. Use the durable scheduled-agent path.
- **Codex**: `AGENTS.md` guidance plus an Automation. Scheduling exists in
  Codex cloud, not the CLI; the CLI needs system cron.
- **n8n**: an MCP client node pointed at Anton, so a visual workflow can ask
  for an approval or read the second brain.

### 4. Meta-skills stay in the core, and are reachable from every harness

Do not reimplement self-upskilling or the opportunity scan as recipes or
workflows. Expose them:

- `anton_propose_work` — what initiative has surfaced
- an MCP tool to start an upskill run and one to report its stage
- keep every enforcement step (research verification, sandbox gate, governor
  ruling) inside the Python service where it can actually be enforced

## Constraints established by testing — do not re-litigate

- **Do not fork any harness.** See above.
- **MCP cannot be the only door.** It is pull-only; nothing in it notifies
  anyone. A money gate nobody opens a client to see is a stalled automation.
  Anton's own approval-queue UI stays.
- **The Executor contract is one blocking `run()` call.** No executor emits
  tokens incrementally. `/api/chat/stream` streams progress, not tokens. Do
  not present anything as token streaming.
- **Steering lands at the next poll tick and never interrupts a running
  job** — `cmd_serve` dispatches synchronously. Say so in any UI you build.
- **Anton is a Single Agent System.** One coherent agent that remembers, not
  a pile of workflows. n8n is reached through an executor; its editor is
  never presented as Anton's own.

## Verification required

Local test passes are not sufficient evidence; this project has been bitten
twice by exactly that.

- Every integration must be driven by a **real client against a real
  service** — a real Goose install, a real MCP client, a real n8n container —
  the way `examples/n8n/` was verified.
- Run the suite under CI conditions, not just yours:
  `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m pytest tests/ -q`.
  `tests/test_environment_isolation.py` is the canary for that protection.
- A test that branches on ambient state and asserts something true of
  whichever branch it observed is not a test. Two of those were removed from
  this repo; do not add more. Force the condition with `patch`, or use a
  visible `skipUnless`.
- CI runs only on `main` and PRs targeting `main`. A branch push runs
  nothing.

## Deliverable

A PR that leaves `main` deployable at every commit, with each integration
verified against the real thing and the honest limits of each stated
plainly — including any part of the SmartApprove redirect that turns out not
to be possible.

---

# Part 2 — the meta-skills, the four installs, and the n8n visual layer

This half of the prompt is the build-out spec. Part 1 fixed the architecture
and the seam (MCP). This part turns the three meta-skills and the four
harness installs from intentions into files, each verified against the real
thing.

## 5. The three meta-skills: one answer, not three features

The customer asked a real question: *is this a governance layer, or
meta-skills and recipes installed into every harness?* The answer is the one
established in Part 1 — split by whether it needs a runtime — applied to the
three skills concretely:

| Meta-skill | Lives in | Why | Surface |
|---|---|---|---|
| **Self-running** | The harness (cron/automation), Anton fallback scheduler for headless installs | Work must be visible as cron in the tool the operator already opens; Anton's `cmd_serve` stays as fallback only | `anton_list_jobs` + `anton_steer_job` (pause/resume/run-now/skip-next) so *any* harness can manage what it runs; the n8n auditor deactivates workflows that stop reporting |
| **Self-learning / self-skilling** | Anton core — it cannot distribute | `verify_research` counts real files on disk and `run_sandbox_gate` does `py_compile` in a clean-env subprocess; neither survives as a recipe or node | Two MCP tools: `anton_start_upskill` + `anton_upskill_status` (wrap `upskill.py`'s research→distill→sandbox-gate→promote pipeline) |
| **Take initiative** | Core proposes, harness executes | `opportunity.py` needs the second brain to judge what is worth doing; firing the action belongs to the harness where gates/UI already live | MCP tool `anton_propose_work` returning `Opportunity` rows (worth/risk/first-step); harness or operator dispatches, Anton gates money/outbound |

All three skills stay reachable from every harness through the MCP seam —
they are not reimplemented per harness. Schedules and recipes are the only
part that ships *into* each harness, and they are thin: they call the same
MCP tools.

## 6. The Goose install (recipe + SmartApprove redirect)

`examples/goose/anton.yaml` — a recipe, never a fork. Verify every field
below against Goose's current recipe reference before writing; the format
evoles.

```yaml
version: 1
title: Anton — governance, memory, and initiative
description: >
  Route money/outbound actions through Anton's durable approval queue,
  consult the second brain, and surface what Anton thinks is worth doing.
instructions: |
  You are paired with Anton, a governance + memory service, over MCP.
  Before acting on anything that moves money or sends external messages:
  1) call anton_pending_approvals
  2) if a relevant approval is pending, stop and report the approval id
  3) otherwise proceed, then record the run with anton_recent_runs
  For memory, use anton_search_memory instead of guessing.
  For initiative, call anton_propose_work before idle time.
activities:
  - name: ask-anton
    instructions: discussion and memory over MCP
    tools:
      - anton_search_memory
      - anton_propose_work
      - anton_status
      - anton_recent_runs
  - name: act-under-governance
    instructions: any money/outbound step requires a durable approval first
    tools:
      - anton_pending_approvals
      - anton_decide_approval
      - anton_steer_job
      - anton_recent_runs
extensions:
  # wire the MCP server per Goose's extension config (verify shape)
  - name: anton-mcp
    type: mcp
    transport: "stdio"
    command: "anton"
    args: ["mcp"]
    environment: { ANTON_MCP_URL: "${ANTON_MCP_URL}" }
settings:
  # verify: does a recipe set GOOSE_MODE? the redirect below is separate
retry: { policy: "exponential", max_attempts: 3 }
response: { mode: "structured" }
```

### The SmartApprove redirect — specify, then prove

Goose gates are *session-scoped and synchronous* (they ask the person at the
keyboard); scheduled/headless runs set `GOOSE_MODE=auto` and approve
everything. Anton's are *durable and asynchronous* (a row a phone answers at
9am). The redirect is the one place this design genuinely extends Goose
instead of wrapping it — so it gets an explicit falsifiable step:

1. **Investigate** Goose's extension API for the `ToolInspectionManager`
   chain (Security → Egress → Adversary → Permission → Repetition): can an
extension/recipe participate in the permission decision and return
"requires approval" backed by `anton_pending_approvals`?
2. **If yes**: implement it; verify with a real Goose install, headless
   (`GOOSE_MODE=auto`), where a money action must park an approval instead
   of auto-firing.
3. **If no** (the API cannot hook the chain): say so plainly in the PR and
   ship the fallback already in the recipe — `anton_pending_approvals`
   before every money/outbound step, and Anton refusing the dispatch until
   approved. The fallback is safe, it just cannot *prevent* Goose from
   acting on its own; it can only make Anton's side refuse.

Do not claim the redirect works without the real-install proof.

## 7. Claude Code, Codex, n8n installs

### Claude Code

- Ship `examples/claude-code/` with a skill or plugin that points at Anton's
  MCP server (`anton mcp` stdio) and documents the tools.
- **Trap (state it in the README):** in-session `CronCreate` is
  session-only, expires after 7 days, and fires only while the REPL is
  idle — it is not Anton's scheduler. Use Claude's durable scheduled-agent
  path or system cron for anything that must survive.

### Codex

- `examples/codex/AGENTS.md` guidance + an Automation that runs Anton's
  pending-approvals check on a cadence.
- **Trap:** scheduling lives in Codex cloud, not the CLI; the CLI install
  needs system cron. The prompt must make that explicit.

### n8n

Two distinct intents, shipped in `examples/n8n/`:

1. **Anton's Gate + Auditor** (already built and verified): the
   money/outbound approval gate and the hourly auditor that deactivates
   silent workflows.
2. **The visual, deterministic layer for the customer's own automations**
   — explicitly *not* Anton's meta-workflows: an **MCP client node**
   pointing at Anton (`anton_pending_approvals`, `anton_search_memory`)
   inside ordinary user workflows, so their own business automations
   inherit memory and approval without embedding Anton internals.

Add a `examples/n8n/README.md` section titled **"Your workflows vs Anton's
meta-workflows"** stating: Anton owns governance/memory/meta-skills; the
customer's n8n editor is their own deterministic layer; Anton reaches it
through the N8NExecutor webhook dispatch and gates money/outbound at the
edge.

## 8. Second brain openness

- `anton_search_memory` is read-one-by-slug today. Add vault-wide search and
a **gated write** (`POST /api/vault/note` is read-only today — writing must
ride an approval or an explicit trust tier, never an unattended
auto-approve).
- Every harness gets memory for free once these land; that is the stated
purpose of the whole seam, and it is the easiest capability to verify
wrongly — test with a real client writing then reading a real vault.

## 9. Delivery order and the gates that prove each step

| Step | Build | Proven by |
|---|---|---|
| 1 | MCP hardening: vault search + gated write, `anton_propose_work`, `anton_start_upskill`/`anton_upskill_status`, transport decision (stdio vs HTTP/SSE) | Real MCP client (like the existing `test_mcp_server.py` drives) against a live container; write→read→search round-trip on a real vault |
| 2 | Goose recipe + SmartApprove investigation | Real Goose install, headless, money action parks approval (or the documented fallback) |
| 3 | Claude Code + Codex installs | Real clients, real schedule firing — not `print` assertions |
| 4 | n8n MCP client node + README | Real workflow calls Anton's approval tool in-container |
| 5 | `.mcpb` bundle | Double-click install on a clean Claude Desktop |

Final gate, unchanged from Part 1: the suite must pass under CI shape —
`env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY python3 -m pytest tests/ -q`
with `tests/test_environment_isolation.py` green — and each integration must
have been driven by a real client against a real service, or the honest
limit stated in the PR. The customer has been burned by locally-green
suites twice; that is a constraint, not a suggestion.
