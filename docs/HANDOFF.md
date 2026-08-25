# NEXT SESSION — START HERE
Frozen spec: docs/AUTHZ-SPEC.md (v1.1, FROZEN — build against it, do not redesign).
Reviews (binding requirements): docs/AUTHZ-ADVERSARIAL-REVIEW{,-2,-3}.md
Convergence threshold: two consecutive independent PROCEED verdicts, zero BLOCKER/MAJOR.

## State (updated 2026-08-24 — COMMERCIAL PILOT READY)

Correction to the previous version of this note: authz is OFF by default on
a plain `anton setup` / the self-serve Docker/Umbrel/VPS installs README.md
walks a consumer through — it was never wired to enable itself there, and
`anton setup` never touches the `authz` key. Self-deploy provisioning
(auto-generated decision/webhook secrets, printed owner claim code) is real
and does fire wherever authz IS enabled, which today is exactly one place:
fleet/provision_client.py (the client-pilot kit), which sets
`authz.enabled: true` explicitly. Fleet kit in fleet/ (provision_client.py +
onboarding checklist). WORM anchor file live at every boot. Click-install
OAuth: Connect button -> Intuit login -> dashboard callback -> Finish;
vendor QBO credentials deployment-local via load_vendor_credentials.
Connector strategy documented (docs/INTEGRATION-STRATEGY.md): native QBO
flagship, Nango self-hosted for local breadth, Composio for fast cloud
breadth.

Fixed 2026-08-24: `cli.py::_build()` (backs `anton serve` and
`anton dashboard`, i.e. the actual CLI entrypoints, not just the FastAPI
app factory) read `config.yaml`'s `authz.decision_secret` directly and
raised at startup if it was empty — but fleet/provision_client.py deletes
that key on purpose, relying on the auto-provisioned
`data/authz/decision.secret` file that only `wire_authz()` used to know how
to read. Every fleet-provisioned client install crashed on the first
`anton dashboard` call its own onboarding printout told the operator to
run. `_build()` now provisions through the same `ensure_decision_secret()`
path `wire_authz()` uses, so both processes agree on the same secret. See
tests/test_cli.py::TestBuildAuthzDecisionSecret.

REMAINING FOR FULL COMMERCIAL LAUNCH:
1. TDH Labs Intuit developer app production review (worksheet:
   docs/QBO-APP-REGISTRATION.md) — external calendar dependency.
2. First real client pilot run (manufacturer) using the fleet kit.
3. Optional: Nango self-hosted spike when breadth is needed.

## Previous state (2026-08-22)
ALL FOUR build items are implemented, tested, and committed on main.
CONV-1 satisfied: rounds 15A+15B consecutive independent PROCEED verdicts
(zero BLOCKER/MAJOR) against HEAD 8b14463; full ledger in progress.md.
7 tracked MINOR/OBS items in progress.md OPEN list (genesis marker,
son-of-anton flag boundary, migration crash window, lease/mint audit rows,
approval freshness window, machine-token lease reach-through, webhook auth):
- 3f02481 #10 Phase 1 authZ spine (anton/authz/, tests/authz/ — suite written FIRST,
  CI-T-* ids map 1:1 to spec; 294 passed + 75 RBAC matrix subtests, zero legacy regressions)
- 2e7766d #12 secret refs op:// bw:// vault:// resolved inside the broker
- 10a7fb1 #11 egress channels (opt-in, tag gate, governor apply) + one-shot approvals
- 988fae1 #5 QBO OAuth end-to-end code (exchange/complete endpoint, encrypted storage,
  rotation). Remaining: interactive Intuit consent (operator browser step) + Umbrel deploy.
- 21605cd fixes for all 6 BLOCKER + 3 MAJOR from implementation-review run 1
- 4764e0e machine-token TTLs

## Convergence (CONV-1) status
- Run 1: NO-GO — 19 surviving findings (6 BLOCKER / 3 MAJOR / MINORs). All
  BLOCKER/MAJOR fixed + pinned by tests/authz/test_review_fixes.py.
- Run 2: launched against 21605cd+ (workflow adversarial-review-mt595mxv-punh45);
  record verdict here when done.
- SHIPPABLE only after two consecutive PROCEED verdicts, zero BLOCKER/MAJOR.

## Remaining build order (todo mirror)
1. ✅ #10 Phase 1 authZ spine
2. ✅ #12 Secrets vault + BYO password-manager adapters
3. ✅ #11 AgentPhone/Email spine (deployment still wires real senders as callbacks;
   AgentPhone MCP + SMTP sender implementations are the remaining glue)
4. ✅ #5 QBO OAuth code side; operator must complete browser consent against
   Intuit and verify Umbrel-side env (/home/umbrel/secrets/harwell/secrets.env)

## Deploy notes
- Umbrel app at ~/umbrel/app-data/anton has LOCAL overrides (app-proxy service,
  entrypoint mount, config-override.yaml) — upstream into repo compose/manifest.
- Image is amd64-only; deploy = docker compose pull && up -d --force-recreate
  (verify digest matches GHCR latest — stale-tag issues seen).
- authZ is OFF by default: set authz.enabled=true (+ mode) in config.yaml to flip.
  First Owner claim code is written to <data_dir>/authz/owner-claim at boot.

## Rules
- NEVER push secrets or PII. Adversarial tests must stay green before any "done".
