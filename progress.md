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

- Implementation review run 1: **NO-GO** — 15 surviving findings (6
  BLOCKER / 4 MAJOR / 4 MINOR / 1 OBSERVATION). Full report:
  docs/AUTHZ-IMPL-REVIEW-RUN1.md. Disposition:
  - F1–F10 (all BLOCKER/MAJOR): FIXED in 21605cd, each pinned by a
    regression test in tests/authz/test_review_fixes.py.
  - F12 (machine-token expiry), F13 (async lint gap), F14 (grant
    reactivation cycle edge): FIXED in 4764e0e / 21605cd.
  - F11, F15 (split-vote MINOR/OBSERVATION): documented design notes in
    code, 9caf799 — honest Phase-1 semantics, no behavior change.
- Run 2: launched against the fixed tree (workflow
  adversarial-review-mt595mxv-punh45); verdict recorded when done.
- SHIPPABLE only after two consecutive PROCEED verdicts with zero
  BLOCKER/MAJOR against running code.

Commits: 648f714, 5ebab33 (spec), 3f02481 (#10 spine), 2e7766d (#12),
10a7fb1 (#11), 988fae1 (#5).

## Review run 2 (2026-08-22)

- **0 BLOCKER / 5 MAJOR / 2 MINOR / 3 observations** survived; all nine
  round-1 fixes independently verified genuine
  (docs/AUTHZ-CONSENSUS-REVIEW-FINAL.md).
- All round-2 findings fixed in 82ba79c, pinned by regression tests:
  R2A-1 stub route, R2A-2 clock staircase, R2A-3 NULL-party grants,
  R2A-4 migration gate + baseline laundering, R2A-5 WebSocket scope gap,
  R2A-6 silent break-glass, R2A-7/O-* doc + hardening.
- Run 3 launched against 82ba79c — determines whether the CONV-1 PROCEED
  streak begins.
