# Progress — AUTHZ-SPEC build (harbor-sas)

## Implementation status

- **Phase 1 authZ spine (#10) — BUILT & TESTED.** Commit 3f02481.
  - `anton/authz/`: principals, rbac, schema (+ invariant triggers), store,
    audit hash chain, guards/middleware, datalayer, credential broker
    (unix socket), grants, approvals, break-glass/recovery, boot/migrations,
    router. Wired into `anton/dashboard.py` behind `authz.enabled`.
  - Adversarial CI suite written FIRST: `tests/authz/` maps CI-T-AUTH/DATA/
    CRED/GRNT/APPR/PRIN/AUDIT ids 1:1 to the frozen spec. Full suite green
    (285 passed + 75 matrix subtests); zero regressions in legacy tests.
- **#12 secrets vault / BYO password managers — BUILT.** Commit 2e7766d.
  Broker resolves `op://`, `bw://`, `vault://` refs at fetch time via
  pluggable adapters; fail-closed; refs never echoed.
- **#11 AgentPhone/Email opt-in connections — BUILT (spine).** Commit
  10a7fb1. `anton/authz/egress.py`: Approver-gated channel creation,
  explicit opt-in, tag-vs-clearance gate, governor outbound hard gate into
  approvals; approvals are one-shot (replay-proof). Deployment wires real
  senders (AgentPhone MCP / SMTP) as injected callbacks.
- **#5 QBO OAuth end-to-end (code side) — BUILT.** Commits 988fae1.
  `anton/qbo_oauth.py` + POST /api/wizard/oauth/complete: code exchange at
  Intuit (injectable transport), encrypted token storage via broker, scope
  recording, revocation-triggered refresh rotation. Credentials resolve
  from env or ~/secrets/harwell/secrets.env (Mac) /
  /home/umbrel/secrets/harwell/secrets.env (Umbrel). Remaining for full
  E2E: interactive browser consent against Intuit (operator step) and
  Umbrel-side deploy verification.

## Review record (spec phase)

- **Correct:** `docs/AUTHZ-SPEC.md` (v1.1) integrates all three adversarial
  reviews into 40 MUST/SHOULD requirements across 10 control domains, plus
  CONV-1 (two consecutive independent PROCEED verdicts) and CONV-2 mapping.
- Hostile self-critique pass found 5 issues, all fixed in v1.1.

## Convergence (CONV-1) tracker

- Implementation-phase adversarial review #1: RUNNING (workflow
  adversarial-review-mt57ea2q-1xibz3). Verdicts recorded here when done.
- Two consecutive PROCEED verdicts with zero BLOCKER/MAJOR required against
  running code before any "shippable" claim.

Commits: 648f714, 5ebab33 (spec), 3f02481 (#10 spine), 2e7766d (#12),
10a7fb1 (#11), 988fae1 (#5).
