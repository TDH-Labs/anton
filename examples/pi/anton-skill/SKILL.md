---
name: anton-integration
description: Use when the user's task involves Anton (the small-business automation agent) — checking what it's doing, its pending approvals, its memory, or steering its jobs. Teaches pi the Anton governance rules and HTTP surface.
---

# Anton Integration

Anton is a governance + memory + initiative service. It has no MCP client
in pi (pi deliberately has no MCP — skills and CLI tools instead), so
pi talks to Anton over its HTTP API (`ANTON_BASE_URL`, default
`http://127.0.0.1:8799`). Anton ships its own executors for pi; this skill
is the behavioral contract.

## The three rules (non-negotiable)

1. **Money/outbound never auto-fires.** Before moving money or sending an
   external message, check Anton's approvals. If a matching approval is
   pending, stop and report its approval id. Never proceed on your own.
2. **Memory comes from Anton.** Read the second brain
   (`GET /api/vault/note?slug=<slug>`) instead of reconstructing context
   from your own history.
3. **Report only what actually happened.** No fabricated "sent" / "done".
   If Anton refused, say why.

## The HTTP surface (the 8 MCP tools, as HTTP)

| Anton tool | HTTP |
|---|---|
| `anton_status` | `GET /api/agent/worklog` |
| `anton_list_jobs` | `GET /api/jobs/state` |
| `anton_pending_approvals` | `GET /api/approvals` |
| `anton_recent_runs` | `GET /api/ledger` |
| `anton_usage` | `GET /api/usage` |
| `anton_search_memory` | `GET /api/vault/note?slug=<slug>` |
| `anton_steer_job` | `POST /api/jobs/<id>/steer` body `{"action": "pause\|resume\|run-now\|skip-next"}` |
| `anton_decide_approval` | `POST /api/approvals/<id>` body `{"decision": "once\|always\|defer"}` |

If authz is enabled, send `Authorization: Bearer $ANTON_DASHBOARD_TOKEN`.

## Steering semantics

Steering lands at Anton's next poll tick (typically ~15s) and never
interrupts a run in progress. A paused job ignores run-now until resumed.
Say so in your output — do not imply instant effect.

## Deciding approvals

`anton_decide_approval` releases real money movement or outbound
messages. Only call it when the person asked you to. Confirm with the
person before calling; when they approve, prefer `once` unless they ask
for `always`. `defer` leaves it pending.

## Initiative

`GET /api/initiatives` — what Anton has surfaced as worth upskilling
toward. Ask before idle time; never substitute it for the task you were
given.