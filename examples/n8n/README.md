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
