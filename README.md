# harbor-sas — standalone Single-Agent System control plane

Greenfield product (M1–M7 complete). This repo is self-contained; it touches nothing
outside `~/harbor-sas/`. The reference fleet on this machine is the case study only —
its incidents became requirements R1–R9 in the product spec:
`~/second-brain/automation-outputs/devops/harbor-sas-product-spec_2026-08-18.md`.

## Status — all milestones built, tested, verified

| Milestone | Delivers | Status |
| --- | --- | --- |
| M1 | Data model (R9), ledger, isolation.db + vault.db + metering schemas, executor contract, routing | ✅ 54/54 tests pass |
| M2 | jobs.yaml engine, cron parser, scheduler, webhook receiver, expected-vs-actual canary | ✅ |
| M3 | Vault module (md + vault.db), delta sensor, graph synthesis, digest | ✅ |
| M4 | FastAPI dashboard (read-only pane) + approvals API (never executes) | ✅ |
| M5 | Ambition governor, sandbox gate, skill authoring (Vercel contract), playbooks, R1 gate enforcement | ✅ |
| M6 | `harbor setup`, install.sh, localhost OAuth callback server | ✅ |
| M7 | install.sh verified end-to-end; Dockerfile included (build on CI/VM — daemon not running here) | ✅ |

## Commands

```
harbor setup    --install-dir ~/.harbor      # provision a fresh install (vault, dbs, config)
harbor serve    --data-dir … [--port 8799]   # scheduler loop + webhook receiver + canary
harbor dashboard --data-dir … [--port 8799]  # read-only pane + approvals API
harbor jobs     --data-dir … [--run-id <id>] # list / run one job
harbor canary   --data-dir …                 # expected-vs-actual tripwires
harbor digest   --data-dir …                 # control-plane digest into the vault
harbor vault    --provision | scan           # second-brain provision / delta+graph
harbor governor --ev 0.8 --feasibility 0.9 --kind money   # ambition governor
harbor skills   --title "…" --golden 3       # author -> sandbox gate -> promote
harbor delta    --data-dir …                 # failures + canary -> initiative candidates
harbor run      --task "…" --executor fake   # one-off run into the ledger
harbor doctor   --data-dir …                 # read-only install diagnostics
harbor usage    --data-dir …                 # metering totals (cloud usage)
harbor oauth    --port 0 --timeout 120       # localhost OAuth callback server
harbor skills   --index --data-dir …         # index data/skills -> skill_dependencies
```

## Jobs (deterministic engine)

`jobs.yaml` is the manifest-as-executable-spec:

```yaml
- id: bill-email
  trigger: { type: webhook, path: /hooks/bill-email }
  recipe: bill-capture
  expected_cadence_min: 1440
- id: notify-client
  trigger: { type: webhook, path: /hooks/notify-client }
  recipe: notify-client
  gate: { outbound: true }        # R1: requires an approved nonce before it can run
```

- Triggers: cron (5-field), webhook (POST /hooks/<id>), delta.
- Verify: shell command with `<output>` token; non-zero -> exit 4 (`verify-fail`).
- Budgets: per-job and daily caps enforced; breach -> exit 3 (`budget-breach`).
- Gates: `money`/`outbound` jobs are blocked (exit 5, `gate-blocked`) until an approval
  exists in the `approvals` table (create/approve via the dashboard API).
- Canary: any job that misses `2× expected_cadence_min` trips a `fleet-canary` flag and
  flips the digest to ATTENTION.

## Data model (R9)

Every ledger row records: `ts, task, exit, flags, output, model, provider,
fallback_used, tokens_in, tokens_out, cost_usd, duration_ms, host, session_id, org_id,
token_accounting` — tokens/cost populated for cloud providers only.

## Install (primary packaging)

```bash
bash install.sh                 # -> $HARBOR_HOME (default ~/.harbor)
# or
HARBOR_HOME=/opt/harbor bash install.sh
```

Container (secondary): `docker build -t harbor-sas .` then run with `/data` mounted.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v   # 60 tests, zero external services
```
