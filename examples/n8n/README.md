# n8n workflow templates

Two workflows that give an n8n instance Anton's own safety posture. Import
them through n8n's editor (**Workflows → Import from File**) or its REST API,
then activate.

They are the n8n-side mirror of `anton/governor.py` and the `approvals`
table: Anton enforces those rules for work it dispatches itself, and these
enforce the same rules for work n8n runs on its own.

## anton-gate.json

A webhook other workflows call before doing anything that moves money or
sends something outward.

`POST` body:

```json
{
  "kind": "money" | "outbound" | "other",
  "risk": "low" | "medium" | "high",
  "title": "Pay invoice 4471",
  "description": "£1,240 to Northwind Supplies, due today",
  "notify_url": "https://hooks.slack.com/..."
}
```

It responds `{"approved": true|false, "reason": "..."}`.

Money and outbound are a **hard gate**: they never auto-clear regardless of
risk score, matching `HARD_GATE_KINDS` in the real product. Anything else at
`risk: low` auto-clears. Everything else pauses on a Wait node until a person
hits the approve or reject link sent to `ANTON_GATE_NOTIFY_URL`.

Set `ANTON_GATE_NOTIFY_URL` as an n8n environment variable before activating.
The notify node is the routing point: swap that one node for "the bookkeeper
under £500, the owner above it" without touching anything else.

The Wait node has no timeout by default. Add one through the node's own
options so a forgotten approval cannot hold a workflow open forever — the
right value depends on what is being gated, so it is left to the operator.

## anton-auditor.json

Hourly. Reads the instance's own workflow list through n8n's REST API and
checks that every workflow tagged `anton-managed` **and** tagged `money` or
`outbound` actually contains an HTTP node calling the gate. Non-compliant
workflows are **deactivated**, not merely flagged, and the operator is
notified.

That is what makes the gate structural rather than a convention someone has
to remember. It is a structural check, not a semantic one: it verifies the
gate call exists upstream, not that the workflow's business logic is right.

Requires an n8n API key (**Settings → API**) exposed to the workflow as
`N8N_API_KEY`, plus `N8N_API_BASE_URL` if the instance is not at
`http://localhost:5678/api/v1`.

## Tagging

The auditor only inspects workflows tagged `anton-managed`. Tag any workflow
that touches money or outbound messages with `money` or `outbound` as well,
and it will be held to the gate. The gate and auditor tag themselves
(`anton-gate`, `anton-auditor`) and are skipped.

## Connecting Anton to the instance

Point Anton at n8n in **Settings → n8n**, or set `ANTON_N8N_BASE_URL`. On the
same Docker host, use the container name — `http://n8n_server_1:5678`. A job
then dispatches to a workflow with:

```yaml
- id: reconcile-payments
  trigger: { type: cron, expr: "0 7 * * *" }
  recipe: "Reconcile yesterday's payments"
  model_route: cloud
  executor:
    name: n8n
    webhook_url: http://n8n_server_1:5678/webhook/reconcile-payments
```

The workflow's Respond to Webhook node returns
`{"output": str, "exit_code": int, "error": str?}` — the minimal contract in
`anton/executor/n8n_executor.py`, so a workflow needs no Anton-specific
knowledge to be dispatchable.

## anton-mcp-client.json — Anton's MCP tools as n8n nodes

n8n's own **MCP Client** node can call Anton directly (no webhook glue).
This workflow is the minimal proof: a manual trigger → one MCP call to
`anton_status`.

**Prerequisite — Anton's HTTP transport:** n8n cannot spawn a stdio MCP
subprocess, so Anton must expose its SSE/HTTP surface as a separate sidecar
process, reachable from n8n by container name:

```bash
# n8n reaches Anton by container name, not loopback -- this needs
# --host 0.0.0.0, and the SDK's DNS-rebinding protection (which otherwise
# rejects any request whose Host header isn't 127.0.0.1/localhost with a
# 421) explicitly disabled. Real per-request auth still comes from the
# bearer token below -- that's the actual security boundary here, not the
# DNS-rebinding check, which is a browser threat model that doesn't apply
# to a server-to-server call.
anton mcp --transport http --host 0.0.0.0 --port 8877 --token "$ANTON_DASHBOARD_TOKEN"
```

Two other doors do **not** work for this: Anton's webhook server
(`/hooks/*`, port 8798) binds container-loopback only and is unreachable
from a sibling container even on the same network, and the public
auth-gate (port 3080) is a cookie-session login page — it returns its own
login HTML to any request, bearer header or not. The MCP HTTP surface
above, with real per-request bearer auth, is the only reachable
machine-to-machine door.

**Import + wire:**

1. Import `anton-mcp-client.json` (**Workflows → Import from File**).
2. Edit each **MCP Client** node:
   - `Endpoint URL`: `http://<anton-host>:8877/mcp`
   - `Authentication`: **Header Auth**; create a credential with header
     `Authorization: Bearer <token>`.
   - `Tool`: pick any of the 9 (`anton_status`, `anton_pending_approvals`,
     `anton_search_memory`, `anton_report_failure`, …).
   - **Passing arguments:** this node has no field-by-field parameter map.
     Set `Input Mode` to **JSON** and put the argument object directly in
     `jsonInput`, e.g. `={{ { "path": "index" } }}` for
     `anton_search_memory`. A zero-argument tool like `anton_status` just
     takes `{}`. (An earlier version of this doc described a `Manual
     parameters` field with per-argument inputs — that field doesn't exist
     on this node; assuming it silently sends an empty argument object and
     any parameterized call fails.)
3. Run it. The node returns Anton's JSON.

**Usage pattern:** put the MCP Client node *before* the Gate workflow in
any pipeline that touches money/outbound — ask `anton_pending_approvals`,
and branch: approved → proceed, pending → Wait for the person. That gives
your visual workflows Anton's exact governance without inventing it a
second time.

**Verification:** run the workflow; both nodes must return real payloads
from the live dashboard (not an error) — confirmed container-to-container
against a real n8n and a real Anton instance, including the parameterized
`anton_search_memory` call. `anton-gate.json` and `anton-auditor.json` have
been verified the same way.

## anton-notify-on-failure.json — n8n reports its own failures to Anton

n8n's native **Error Trigger** node, wired to call Anton's
`anton_report_failure` MCP tool, so a workflow that breaks — a connector
going unreachable, an API starting to reject calls — shows up in Anton's
own inbox loop instead of failing silently.

**Prerequisites:**

- The same MCP HTTP sidecar and Header Auth credential as
  `anton-mcp-client.json` above.
- Any workflow you want covered must set **Settings → Error Workflow** to
  this workflow (**Anton Notify on Failure**).
- **Both** workflows must be active — the failing workflow and this one.
  n8n does not fire an inactive error workflow; a workflow with the
  setting configured but not itself activated silently never triggers it
  (confirmed live via n8n's own container logs:
  `Calling Error Workflow for 'X'. Workflow 'Y' is not active and cannot
  be executed`).

**Import + wire:**

1. Import `anton-notify-on-failure.json`.
2. Edit the **Tell Anton** node's Header Auth credential the same way as
   above.
3. Activate this workflow.
4. On each workflow you want covered, open **Settings → Error Workflow**
   and select **Anton Notify on Failure**, then make sure that workflow is
   itself active.

`anton_report_failure` files through the same inbox loop
`/api/inbox/messages` uses. The `ACTION REQUIRED: ...` subject text this
workflow sends is what earns `kind=flag` in Anton's classifier — ungated,
synchronous, visible at the Ops Center's "What went wrong" screen. It can
never trigger an outbound send: nothing here asks Anton to reply to
anyone, so the outbound gate never engages. This tool is for surfacing a
failure to a person, never for silently attempting a fix — an expired
credential or a broken integration is something a human should see, not
something to auto-resolve.

**Verification:** confirmed live against a real n8n container — a
deliberately-failing test workflow with its Error Workflow set to this one
produced a real new flagged message in Anton's inbox, visible via Anton's
own API, on a clean import of the shipped file (no debug modifications).
