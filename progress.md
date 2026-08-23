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

## Review run 3 (2026-08-22) — DEFERRED, provider outage

- Run 3 launched against 82ba79c twice: the first (mt5aglx2-7b9kbu) was
  repeatedly 429-paused by the stealth/ox-alpha shared pool and died
  mid-refute ("no valid structured_output after repair"); the relaunch
  (mt5c2cb7-fguanb) failed at investigate launch (231 tokens). Provider
  outage confirmed during session.
- Nothing lost: investigation + early refutes cached on the dead run's
  files; rounds 1-2 dispositions remain valid and pinned by tests.
- Next session: resume mt5c2cb7-fguanb (or fresh relaunch) once the pool
  recovers, or reroute with an OpenRouter key (openrouter.ai/settings
  /integrations). CONV-1 streak does not start until this lands clean.

## Review (adversarial reviewer B — Phase 1 authZ, HEAD 82ba79c + a563267)

### What's correct
- Prior-round fixes on this angle verified genuine: INSERT-time human-collapse +
  both-parties-exist self-grant trigger (schema.py:138, R2A-3/F3), ux_decision_once
  unique index + IntegrityError→ApprovalRejected decision race close (R2A-4/F8),
  reactivation cycle re-check trigger (F14), CRITICAL_OBJECTS now covers the full
  set incl. ux_decision_once and migration gate refuses to re-baseline on failure
  (R2A-4), silent break-glass refused in the API path (R2A-6, test-verified).
  Full suite 88 passed + 75 subtests.
- No new double-decision or cycle race found: store.lock + single connection
  serialize INSERTs; the cycle CTE covers reactivation direction.

### Fixed: N/A (no in-tree code changed — review only, findings reported out)

### Note: findings (5, strongest first) — see review JSON
- MAJOR: approval_decisions/approval_executions are fully mutable (no UPDATE/DELETE
  triggers) — DB-layer approver≠initiator + decision finality bypassable, verified
  (flip 'rejected'→'approved' + rewrite approver_human, then execute_approved runs).
- MINOR: revoked-grant reactivation re-checks only cycles, not self-grant
  human-collapse/party-existence (verified: rebind human_id, reactivate → active
  self-grant).
- MINOR: request_breakglass rate-limit COUNT outside the lock — concurrent burst
  bypasses (1,3600) (verified, 2 events).
- MINOR: use_recovery_artifact read-modify-write of recovery_codes non-atomic —
  one-time code usable twice under concurrency, double master-key rotation.
- MINOR: elevation windows (trg_role_no_self_modify & expires) are pure host wall
  clock with no broker epoch/monotonic fallback/alarm — REQ-CRED-06 deviation;
  schema also honors fully-silent channels_ok=0 events (R2A-6 fix is API-layer only).

Observations: role_assignments self-modification trigger is trivially bypassable by
direct SQL (INSERT with actor≠user fires no trigger), but that matches documented
design (API-gated); pending_actions apply_ready double-apply is only cross-process
(relevant if schedulers ever run on >1 process); decision/execution rows also lack
append-only triggers that prior rounds added to audit_chain — same asymmetry.

## Review (adversarial-reviewer-C, run vs HEAD 82ba79c / a563267)

Angle: cryptography / secrets / credential broker / audit-chain integrity
(broker.py, secretrefs.py, audit.py, boot.py). Full suite green
(88 passed + 75 subtests) before probing.

- Verified genuine (prior fixes): fetch() peer-uid fail-closed
  (uid=None denied, control re-tested); epoch high-water mark — backward
  jumps and <threshold staircases never regress epoch_now (no TTL
  extension; alarms fire); audit _entry_hash covers sponsor_user/
  workspace/agent_instance/tool_credential (identity-column edits →
  ChainTampered); CRITICAL_OBJECTS gate blocks DROP of any critical
  trigger/index and never launders the baseline (R2A-4); fabricated
  grant parties aborted by trigger (R2A-3); WebSocket scopes denied +
  auditor flags them (R2A-5); break-glass with zero channels delivered
  refused (R2A-6). Chain-gap + append-only triggers present; verify()
  catches middle/tail truncation against kv.audit_head_seq (honest
  same-DB limit documented for R2A-7).
- Fixed: nothing (adversarial review only; findings reported to the
  coder via JSON).
- Note: full finding set returned as JSON (5 findings). Found two
  MAJORs on this angle (lease/mint peer-uid attestation gap; migration
  gate name-only check → same-name trigger weakening launders baseline),
  so CONV-1 streak remains unopened for run 3.

## Review (adversarial-reviewer-A, run vs HEAD 82ba79c / a563267 — authZ phase 1)

Angle: authentication bypass / fail-open / privilege escalation in anton/authz/
(guards.py, store.py, router.py, datalayer.py). Full suite green (88 passed +
75 matrix subtests) before probing; targeted probes via tests/authz/helpers.

- Verified genuine (prior fixes): default-deny fallback for unmapped mutating
  routes (Viewer 403 / Owner 404); machine-token allowlist exact-match + alert +
  audit on violation; session/role re-validation per request; legacy shared
  token rejected post-migration (authz_middleware_active); lockout (429 after 5);
  bootstrap single-use claim (409 after claim); deny-WeB socket scope; egress
  channel creation really writes rows; R2A-2..R2A-6 pins hold.
- Fixed: nothing (adversarial review only; findings returned as JSON).
- Note: two of the reported items (lease/mint peer-uid gap, migration
  baseline-laundering) were independently flagged by reviewer C in the deferred
  run 3; re-verified empirically here, still unfixed at this HEAD. Finding set
  returned as JSON (5 findings, 3 MAJOR + 2 MINOR) — CONV-1 streak stays closed.

## Review (adversarial-reviewer-B, run vs HEAD 0949e9f — run-3 fixes; angle:
schema invariants / TOCTOU / migrations)

Suite green before probing (97 passed + 75 subtests).

- Verified genuine: trg_approvals_no_self_approve does NOT break valid
  cross-user approvals (R3A1 test both directions); socket lease/mint/poll/
  fetch ops all peer-uid attested and mint enforces lease connection-set;
  weakened_critical_objects byte-compares trigger AND index SQL correctly;
  decision/execution DELETE triggers + decision UPDATE trigger live; login
  events in the audit chain; break-glass rate-limit check inside the store
  lock (3-thread burst → exactly 1 elevation); recovery consumption is
  atomic under RLock and rotates BEFORE consuming (no store⇄broker lock
  inversion — checked every audit.append call site for broker.lock-held
  store access; none exists → no deadlock); grant reactivation re-checks
  self-grant/cycle; boot_check fails closed on missing baseline; fetch
  hoists the grant check before decrypt/resolution.
- Fixed: nothing (adversarial review only; findings returned as JSON).
- Note: found 3 MAJOR (all in the migration/legacy-gate seams of the run-3
  fixes, each with a runnable repro) + 1 MINOR + 1 OBSERVATION. The R3A-3
  regression test is green but asserts a *different* trigger's behavior
  (role_assignments vs the weakened trg_grant_no_self), so the "rejected
  migration leaves weakened DDL committed" defect escapes CI. CONV-1 stays
  closed.

## Review (adversarial-reviewer-A, run vs HEAD 0949e9f — run-3 fixes; angle:
AUTH BYPASS + FAIL-OPEN)

Suite green before probing (97 passed + 75 subtests), then three empirical
repros (all committed as /tmp/repro_*.py) against the RUNNING gate and live
DB.

- Verified genuine: R3A-2 socket attestation gates every non-ping op (op-set
  complete: lease/mint/poll/fetch; unknown ops denied) and mint enforces the
  lease connection-set; R3C-4 fetch hoist re-checks the grant before decrypt/
  resolve; R3B-4 rate-limit check + consumption are serialized under the same
  RLock (3-thread burst → exactly one elevation); recovery consumption is
  atomic, rotate-before-consume; login events appended to the hash chain;
  boot_check fails closed on missing baseline; grant reactivation trigger
  set is complete.
- Fixed: nothing (adversarial review only; findings returned as JSON).
- Note: found 4 MAJOR + 1 MINOR. Three are repro-confirmed fail-open seams
  left by the run-3 fixes themselves: (1) the migration gate compares only
  trigger/index bodies — a DROP/CREATE of approval_decisions without the
  CHECK passes run_migration, is REBASELINED and accepted by boot_check,
  silently voiding R3A-4 (repro: forged decision INSERT succeeds, zero
  detection); (2) run_migration COMMITs hostile SQL before the gate check and
  raises WITHOUT rollback — a REJECTED migration leaves the weakened trigger
  durable and effective (self-grant INSERT allowed in the live DB) until
  reboot; (3) the legacy approver≠initiator trigger requires non-NULL
  initiator_human, and the scheduler's own creation sites (upskill.py:373,
  experience.py:157) still write NULL initiators — the exact scheduler gate
  R3A-1 claimed to fix remains self-approvable (repro: HTTP 200). Also:
  R3B-4 now holds the single store write lock across unbounded external
  channel I/O (global control-plane wedge incl. revocation + audit append).
  CONV-1 stays closed.

## Review (adversarial-reviewer-A, run vs HEAD 3ff567b — round-5 fixes; angle: AUTH BYPASS + FAIL-OPEN)

Suite green before probing (107 passed + 75 subtests). Round-5 fixes verified
genuine at API/trigger level: all-NULL two-step forge closed (decided
transitions require non-null approver != initiator; adoption is the sole
escape and is single-shot); fresh trigger names install on old DBs;
break-glass pre-check precedes delivery and rate_limited rows are audited;
refused migrations audited; consumed/denied terminal; _validate_lease and
_check_capability share the fail-closed session helper. The remaining
findings are round-5 seams:

- Fixed: nothing (adversarial review only; findings returned as JSON).
- Note: found 2 MAJOR + 1 MINOR + 2 OBSERVATION (JSON returned). R5-7's
  isolation.db gate runs only inside wire_authz (dashboard boot, authz-enabled),
  while every money-gate decision happens in `anton serve`/webhook — separate
  processes that never run the check; init_db's CREATE TRIGGER IF NOT EXISTS
  silently accepts a pre-existing weakened same-name trigger on the serve
  side, and the gate is exact-text + boot-only so a runtime trigger swap is
  never re-detected. R5-1's adoption path is dead on upgraded round-3/4-era
  DBs (surviving trg_approvals_no_self_approve_upd aborts every initiator
  mutation), and the R5-7 gate reports clean on those DBs — repro'd via the
  real init_db + isolation_approvals_integrity code. Approved is not terminal
  (approved→pending→approved replay allows re-running the money gate on one
  dated sign-off). CONV-1 stays closed.
