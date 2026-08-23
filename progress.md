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

## CONV-1 CONVERGENCE RECORD (2026-08-23)

Implementation-phase adversarial verification ran 15 rounds (2 independent
reviewers per round from round 3, deepseek-v4-flash via the working
provider route after stealth/ox-alpha outage). Every BLOCKER/MAJOR found
was fixed and pinned by regression tests in tests/authz/test_review_fixes_r3.py:

| Round | Blocking findings | Fix commit |
|---|---|---|
| 1 | 6 BLOCKER + 4 MAJOR | 21605cd |
| 2 | 5 MAJOR | 82ba79c |
| 3 | 4 MAJOR (+8 minor) | 0949e9f |
| 4 | 4 MAJOR + 1 MINOR | 1d902ee |
| 5 | 3 MAJOR + 3 MINOR | 3ff567b |
| 6 | 2 MAJOR + minors | c923c4d |
| 7 | 2 MAJOR + minors | 15f0f3e |
| 8 | 2 MAJOR + 2 MINOR | 8e7fcea |
| 9 | 1 BLOCKER + 3 MAJOR | bf5670e |
| 10 | 2 MAJOR + 2 MINOR | 3a59d18 |
| 11 | **0 blocking** (3 MINOR/OBS) | 01737b7 |
| 12 | 1 MAJOR (baseline-None laundering) | cd16448 |
| 13 | 2 MAJOR (boot-order heal/launder) | 137fa63 |
| 14 | 1 MAJOR (first_boot canonical gate) | e1787b6 |
| 15 | **PROCEED both reviewers** (2 MINOR + OBS) | 0e5844d / 8b14463 |

**CONV-1 satisfied**: rounds 15-A and 15-B are two consecutive independent
adversarial reviews issuing PROCEED verdicts with zero BLOCKER/MAJOR
against running code (HEAD 8b14463). Suite at convergence: 354 passed +
75 RBAC matrix subtests; all prior-round regression pins still green.

### Open tracked items (MINOR/OBS, non-blocking per CONV-1)
1. Out-of-DB genesis marker for the kv-drop launder (audit-chain table-drop
   shape heals before first_boot gate) — needs a file-based seeding marker;
   design decision for Adam.
2. Son-of-anton flag is raw-writable in isolation.db — operator-only trust
   boundary; consider keyed HMAC on the flag row.
3. run_migration applies DDL then re-baselines in separate transactions
   (crash window; test-only path today).
4. Broker lease/mint issuance not audit-chained (fetch is).
5. Approval freshness window (no expiry on approved-but-unconsumed rows).
6. Machine-token revocation reach-through into live broker leases (TTL-bounded).
7. Webhook trigger endpoints unauthenticated by design (documented).

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

## Review (adversarial-reviewer-B, round 7, run vs HEAD c923c4d; angle: SCHEMA INVARIANTS + TOCTOU + MIGRATIONS + UPGRADE PATHS)

Suite green before probing: 327 passed + 75 matrix subtests. Round-6 fixes
verified genuine: pending->consumed and approved->pending refused (live
repro + pinned tests); scheduler consume (approved->consumed) unaffected;
son-of-anton INSERT-consumed still allowed (its INSERT is outside the
UPDATE-only guard); adopt_legacy_approval's single-statement rewrite is
consumed by the adoption-exemption clause atomically (no re-trigger of the
immutability clause; second adoption fails via rowcount 0); fresh-boot
false-positive risk is nil — _assert_isolation_trigger_integrity returns
early on a missing isolation.db and every caller (init_db, _build,
cmd_vault) creates it first; per-decision sqlite_master lookup is one
indexed sys-table read (negligible). One new MAJOR (upgrade-convergence),
one MINOR (approved->denied reopen), three OBSERVATIONs.

- Fixed: nothing (adversarial review only; findings returned as JSON).
- Note: r5->r6 migration is bricked by the new boot gate: a DB created by
  round-5 code carries trg_approvals_transition_guard under the SAME
  canonical name with the pre-R6-3 body; round-6 init_db's CREATE TRIGGER IF
  NOT EXISTS keeps the old body, isolation_approvals_integrity exact-string
  compare flags it `weakened`, and the new boot assertion hard-refuses
  serve/dashboard/vault — repro: build DB from 3ff567b SCHEMA, run round-6
  init_db + _assert_isolation_trigger_integrity -> RuntimeError, and 2x
  re-run init_db per the error message's own remedy leaves the drift
  unchanged. Also found: approved->denied re-decision (walk-back of a dated
  sign-off with a new approver stamp) is not covered by the R6-3b closure.
  CONV-1 stays closed.

## Review (adversarial-reviewer-A, round 7, run vs HEAD c923c4d; angle: AUTH BYPASS + FAIL-OPEN, scheduler money/outbound gate end-to-end)

Suite green before probing: 111 passed + 75 subtests (tests/authz -q). Round-6
fixes verified genuine where claimed: the serve-path boot gate really runs
before any decision in the real topology (entrypoint.sh -> `anton serve` ->
cmd_serve -> _build -> init_db + _assert_isolation_trigger_integrity, then
the serve loop; the webhook is hosted in the SAME serve process, so it is
covered too); the boot gate's body compare really detects weakened triggers
(repro: `trg_approvals_pending_only_insert` recreated with a WHEN(0) body ->
boot drift `['trg_approvals_pending_only_insert:weakened']`); init_db drops
superseded names + ALTER-ADDs identity columns idempotently (pinned R6-2);
the webhook cannot bypass the money gate (POST /hooks -> run_job -> _is_approved
still applies for gate.money/outbound jobs); son-of-anton toggle API is
token-gated (dashboard `_require_token`).

- Fixed: nothing (adversarial review only; findings returned as JSON).
- Note: two MAJOR fail-open seams on the LIVE gate, both repro'd. (1) The
  round-6 per-decision re-verify in _is_approved checks trigger NAMES only
  (sqlite_master subset test), never bodies nor the extra-trigger drift rule,
  even though isolation_approvals_integrity() — the exact check the boot path
  uses — already exists in the same module: a mid-run DROP+recreate of
  trg_approvals_pending_only_insert with a no-op body passes the names check
  and a forged status='approved' INSERT is then consumed by the gate. (2) The
  transition guard covers status/initiator only; `action`/`amount`/`recipient`
  are mutable after sign-off, so with INTACT canonical triggers and pure DML
  an attacker retargets any real approved row to a money-gated job's action;
  the same DML-only attacker can stage a full two-identity forge (INSERT
  pending{alice}, approve{mallory}) since the trigger cannot attest identity
  provenance — approver!=initiator holds syntactically with attacker-chosen
  names. Also: son-of-anton remains the cheapest bypass (one unprotected DML
  upsert on app_settings; gate integrity verification is skipped entirely
  while on — designed permissionless mode, but the toggle itself is
  DB-unprotected), and R6-4's adopt_legacy_approval is audit-after-commit
  and not wired into any production call site (grep: tests only), so live
  adoptions are still un-audited raw SQL. Out-of-scope observation:
  dashboard decision="always" writes a `kind` column that isolation.db's
  approvals table does not have (OperationalError -> 500, fail-closed).
  CONV-1 stays closed for these; 2 MAJOR findings returned.

## Review

Round 9 adversarial verification (HEAD 7a3d16d) — angle: AUTH BYPASS / FAIL-OPEN on the
scheduler money/outbound gate + hmac/replay + adoption/legacy abuse. All 120 tests pass
(`tests/authz -q`). Probes run with real committed code paths.

### Verified genuine (round-8/9 fixes hold)
- R8-1 authentic: with `engine._decision_secret` set, a raw-SQL forged approved row
  (INSERT pending{initiator} -> UPDATE approved{distinct approver}, no hmac) is refused
  by `_is_approved` with `unverified_hmac`; the check->select->consume path is one
  BEGIN IMMEDIATE transaction.
- Replay closed: a legit-hmac approved row is one-shot (2nd consume -> `no_approval`);
  explicit-id INSERT reuse conflicts on PK; DELETE refused (R9-1 `trg_approvals_no_delete`);
  adopt endpoint pinned to `approvals.decide`; decision/execution tables append-only.

### New findings (returned as JSON)
1. BLOCKER — `upskill.approve_pending_promotion` (upskill.py:399) consumes
   `status='approved'` rows with NO hmac verification, NO `isolation_approvals_integrity`
   drift check, no transaction. Repro: authz mode + secret set, forged two-step
   `upskill_promote:{slug}` row -> scheduler refuses the same table, this consumer
   CONSUMES it and promotes the staged code into data/skills/. The forge is codified
   by tests/test_upskill.py:200.
2. MAJOR — authz-enabled without `decision_secret` silently runs the legacy fail-open
   branch (`_is_approved` falsy-secret path); nothing enforces secret presence;
   `decision_secret` appears nowhere in docs/AUTHZ-SPEC.md — the "documented boundary"
   is a scheduler code comment only. Repro: authz on, secret empty -> forged row consumed.
3. MAJOR — canonical authz approvals spine (egress outbound gate,
   `anton/authz/approvals.py` + `egress.submit_send/execute_send`) has NO shared-key
   authenticity evidence: raw-SQL fabricated approval+decision triple (distinct fake
   humans) passes `execute_approved` and the sender fires; R8-1's hmac standard was
   applied only to the isolation scheduler table. `approve()` lacks an Approver-role
   check at the data layer.
4. MINOR — hmac scheme: plain `sha256("decision:{secret}:{id}")`, unkeyed, no
   nonce/salt, sequential id -> offline dictionary crack of weak secrets from one
   stored (id,hmac); no freshness bound (approved-but-unconsumed rows spendable
   indefinitely); secret mode consumes most-recent (DESC) vs legacy oldest (ASC).
5. MINOR — field-level immutability gaps: INSERT trigger allows preset `hmac`
   (contradicts its own comment); transition guard omits `ts`/`hmac`/`org_id`/`nonce`
   -> timeline/evidence laundering on "historical" rows (R9-1 covers DELETE only).
   Repro: consumed row ts backdated, nonce/org_id/hmac rewritten.

## Review (adversarial round 10, reviewer B — schema invariants / TOCTOU / upgrade paths)

Verified round-9 fixes genuine: `consume_verified_approval` shared by scheduler
`_is_approved` and upskill `approve_pending_promotion` (drift + keyed hmac + one-shot
consume inside BEGIN IMMEDIATE); wire_authz/cli._build refuse authz-enabled without
decision_secret; evidence_hmac stamped at approve(), verified at execute_approved;
INSERT guard reserves hmac (marker excepted) and refuses raw consumed inserts.
Suite green: 126 passed + 75 matrix subtests (tests/authz).

Probed (all try/except wrapped):
- Son-of-anton still works with the tightened INSERT guard (`_is_approved` -> True,
  marker row (`consumed`, `son_of_anton_bypass`) inserted; raw consumed INSERT without
  the marker still refused).
- Concurrent BEGIN IMMEDIATE consumers: 4-way race on one approved row -> exactly one
  consumes, three fail closed "no_approval", no deadlock.
- UPGRADE PATH (new): a pre-R9 authz.db (approval_decisions without evidence_hmac)
  boots fine (schema_signature is self-referential vs the recorded kv baseline; DDL
  unchanged by CREATE TABLE IF NOT EXISTS) but `approve()` crashes with uncaught
  `sqlite3.OperationalError: table approval_decisions has no column named
  evidence_hmac`; `execute_approved()` likewise. There is NO production migration for
  the new column: `run_migration`/`MigrationPrincipal` have zero production callers
  (test-only), and even a manual `ALTER TABLE` would then trip the boot gate
  (signature != baseline) with no sanctioned re-baseline path. Authz test suite has no
  upgrade-from-old-authz.db test (R6/R7 pin isolation.db upgrades only).
- TOCTOU (new, minor): in `_is_approved` and `approve_pending_promotion` the
  `BEGIN IMMEDIATE` statement sits OUTSIDE the `except sqlite3.OperationalError`
  recovery. With a write lock held >10 s, the raw "database is locked" escapes
  (verified: 20.9 s uncaught) — contradicting the code's own "fails closed as
  'gate_locked' instead of killing the scheduler process" intent; cmd_serve's poll
  loop has no try/except around run_job, so a transient lock kills the process.
- OBSERVATION: the son-of-anton bypass switch (`app_settings.son_of_anton_mode`) and
  the public bypass marker are raw-writable in the DB layer; a raw-DB writer (the
  exact adversary the keyed-hmac countermeasures model) can set the flag and nullify
  the whole money/outbound gate.

## Review (adversarial round 10, reviewer A — auth bypass / fail-open on all approval consumers)

Verified round-9 fixes genuine (code + probes, all probes try/except-wrapped):
`consume_verified_approval` is shared by scheduler `_is_approved` AND upskill
`approve_pending_promotion` (drift check + keyed decision-hmac + one-shot consume,
BEGIN IMMEDIATE); wire_authz and cli._build both refuse authz-enabled without a
non-empty decision_secret; evidence_hmac = HMAC(decision_secret, approval_id|payload_hash)
stamped at approve() and verified at execute_approved; INSERT trigger reserves hmac
(son_of_anton_bypass excepted) and refuses raw consumed inserts; ts/nonce/org_id
immutable; _decision_hmac is keyed HMAC. Suite green: 126 passed + 75 matrix
subtests (tests/authz) + 216 legacy tests; live E2E dashboard decide -> scheduler
consume works with the keyed hmac.

Probed against all three consumers (scheduler, upskill, egress execute_send):
- Forged-row matrix with decision_secret set — preset hmac 'son_of_anton_bypass',
  empty-string hmac, NULL hmac, cross-id hmac copy, adoption+forge combos: ALL
  refused (unverified_hmac) by every consumer. Trigger level: preset hmac/approver
  at INSERT refused; approved rows with empty/NULL/marker hmac blocked at consume.
- Evidence-hmac cross-approval replay: two approvals with the SAME payload_hash;
  copying approval A's decision row (incl. evidence) onto B — execute_approved(B)
  refused (evidence binds approval_id). No replay. ux_decision_once + executions
  PK hold one-shot.
- decision_secret requirement: no legit legacy flow broken (full 342-test matrix +
  live egress/upskill paths). Legacy (authz-off) mode documented boundary intact.

New findings: (1) MAJOR upgrade break — existing multi-user authz.db (pre-R9) has
approval_decisions WITHOUT evidence_hmac; ensure_schema's CREATE TABLE IF NOT EXISTS
never alters; NO migration exists and a manual ALTER would trip boot_check's
schema-hash gate (run_migration is test-only) -> first approve() after upgrade raises
uncaught OperationalError (reproduced). (2) MAJOR — the R9 "fails closed as
'gate_locked'" claim is false for the actual lock point: BEGIN IMMEDIATE sits outside
the except sqlite3.OperationalError (scheduler.py:204, upskill.py:412); a held write
lock surfaced uncaught OperationalError 'database is locked' after 20.9s in a live
_is_approved call; cmd_serve's poll loop has no try around run_job -> transient lock
kills the scheduler process. (3) MINOR — split-brain trust point: decision_secret
configured while authz.enabled=false makes the dashboard write empty-key hmacs
(_set_hmac_secret only in wire_authz) while the scheduler verifies with the config
key -> every legit approval permanently unconsumable, no boot error. (4) MINOR —
consume picks ORDER BY id DESC LIMIT 1; one planted max-id approved junk row (NULL
hmac; triggers permit hmac-less approve writes) permanently parks all legit
approvals behind unverified_hmac (reproduced). (5) OBSERVATION — approvals.id is not
in the transition-guard immutability list; row renumbering invalidates keyed hmacs
(DoS / tamper-evidence) — add NEW.id IS NOT OLD.id.

## Review — round 12 (adversarial reviewer B, verification round 12, HEAD 01737b7)

### What's correct
- R11-1 (whitespace): genuine. All three write-side trust points normalize —
  `create_app`/`_set_hmac_secret` (dashboard.py:217-220), `wire_authz`
  (authz/__init__.py:42), `cli._build` (cli.py:118) all `.strip()`. All four
  verify-side consumers read the already-normalized value (`store.decision_secret`,
  `engine._decision_secret`); no config-raw reader remains. Grep-confirmed.
- R11-2 (NULL-hmac consumed INSERT): genuine. `COALESCE(NEW.hmac,'') !=
  'son_of_anton_bypass'` in db.py:85 correctly aborts NULL/empty-hmac consumed
  INSERTs while the documented bypass marker still passes; cannon reset matches
  via `isolation_approvals_integrity`. R11 tests pass (3/3).
- R11-3 (upgrade baseline guard), baseline-PRESENT branch: genuine — a drifted DB
  with an intact kv baseline is NOT rebaselined by open_store; boot_check refuses
  (pinned test). Covered below: the None branch is not.

### Fixed
- (none from this round — see MAJOR finding; fix already applied by review)
  Actually: none were applied; the MAJOR below remains open.

### Note
- MAJOR finding 1 (R11-3 incomplete) blocks PROCEED per prior round convention;
  see JSON. Failed-closed alternative is available and does not break the
  sanctioned pre-R9 upgrade path (every DB that ever passed wire_authz/boot_check
  or run_migration has a recorded baseline since the Phase-1 spine; evidence_hmac
  arrived only in R9, so a genuine pre-R9 DB always has baseline == old_sig).

## Review — adversarial round 12 (AUTH BYPASS + FAIL-OPEN sweep; HEAD 01737b7)

- Verified round-11 fixes are genuine (code + probes + pinned tests in
  tests/authz/test_review_fixes_r3.py):
  - R11-1 whitespace: strip() at all three write-side trust points
    (dashboard.py:220, cli.py:118, authz/__init__.py:42); verifiers read the
    normalized store/engine value. R11WhitespaceSplitBrain passes.
  - R11-2 NULL-hmac consumed-INSERT: COALESCE(NEW.hmac,'') in the isolation
    pending-only trigger (db.py:85); probed end-to-end — NULL-hmac consumed
    INSERT raises IntegrityError; legit approved row with keyed hmac still
    consumes. R11NullHmacConsumedInsertRefused passes.
  - R11-3 sanctioned upgrade requires baseline==live (store.py:92-93);
    R11UpgradeBaselineGuard passes.
- Swept all approval consumers (scheduler `_is_approved`, upskill
  `approve_pending_promotion`, egress submit/execute, authz
  approve/execute_approved) and the broker (lease/mint/fetch/poll, grant +
  session + key-version rechecks). No BLOCKER/MAJOR. Fail-closed confirmed:
  lock contention → 'gate_locked', drift → block, unverified hmac → block,
  unwired grant/session validators → deny, broker unavailable → BrokerDegraded.
- Fixed: nothing required.
- Findings:
  - MINOR: R11-3 incomplete for baseline==None — a tampered/restored authz.db
    (evidence_hmac column dropped AND kv.schema_hash deleted) is auto-healed
    and re-baselined by open_store, so boot_check's baseline_missing refusal
    never fires. Genuine pre-R9 DBs always carry a baseline (schema_hash since
    3f02481, evidence_hmac since bf5670e), so baseline==None is never a
    legitimate upgrade target. (store.py:93; probed.)
  - OBSERVATION: upskill default _PROMOTION_RISK_PROFILE routes
    AUTO_EXECUTE (score 0.81 ≥ 0.7, low risk), so the R9-hardened approval
    consumer is unreachable under default config — promotion lands in the
    live skill pool unattended. (upskill.py:54/365-367)
  - OBSERVATION: machine tokens ignore the user's `disabled` flag
    (resolve_machine_token JOIN has no u.disabled=0 check, unlike
    resolve_session) — a disabled service identity's token still passes the
    /api/exec/result allowlist (static echo response only). (store.py:285-289)

## Review — adversarial round 13 (AUTH BYPASS + FAIL-OPEN final sweep; HEAD cd16448)

- Round-12 fixes verified GENUINE (code read + pinned tests pass 2/2):
  - R12-1: `_upgrade_approval_decision_columns` ALTERs/re-baselines ONLY when
    baseline is non-None AND equals the live signature; a tampered DB
    (column dropped + kv schema_hash deleted) stays un-healed and
    boot_check's `baseline_missing` refusal fires (store.py:92-95, boot.py:25-34).
    Race tolerance via PRAGMA column re-check under lock is correct.
  - R12-3: `resolve_machine_token` now honors `users.disabled` (u.* join),
    `revoke_machine_token()` present (store.py:307-320); machine_tokens.revoked
    has DEFAULT 0 so the revoke UPDATE cannot fail on old rows (schema.py:38-43).
- Final sweep — approval consumers (scheduler `_is_approved`, upskill
  `approve_pending_promotion`, egress submit/execute, approvals
  approve/execute) and broker (lease/mint/fetch/poll): no BLOCKER/MAJOR.
  Shared `consume_verified_approval` = drift check + keyed-hmac verify +
  one-shot consume under BEGIN IMMEDIATE; lock contention → 'gate_locked';
  broker peer-uid attestation on every socket op, unwired
  grant/session/principal validators deny, lease sig checks, kv-vs-current
  key-version check, epoch high-water mark — all fail closed.
- Findings: 1 OBSERVATION (machine-token revocation not enforced against
  already-issued leases/cap tokens — bounded ≤ lease TTL window).

## OBSERVATION (bounded): R12-3 "tokens die with it" only at resolve time — outstanding broker leases/cap tokens outlive a machine-token revoke
- mechanism: `lease` op resolves the machine token once via
  `principal_validator`; leases for service principals bind no session_id
  (store.py resolve returns session_id=None → broker embeds sid=""). At
  `mint`/`fetch`, `_session_dead("")` returns False and `revoke_machine_token`
  /`users.disabled` are never re-checked — only `grant_checker`,
  kill_switch, and short TTLs (lease ≤300s, cap ≤600s) bound the window.
- evidence: mint cap token → resolve_machine_token → set users.disabled=1 /
  revoke jti → fetch still returns the secret until cap exp.
- fix: embed the machine-token jti in leases for service principals and
  re-validate it in `_validate_lease`/`_check_capability` (broker already
  has `_token_revoked_row`), or have the grant/session validators consulted
  at fetch time for sid-less principals.

## Review — Round 13 (adversarial B: schema invariants / TOCTOU / migrations / upgrades)

- Correct: R12-1 strict baseline==live-signature guard is genuine — tamper
  (DROP COLUMN evidence_hmac + DELETE kv schema_hash) stays un-healed and
  boot_check refuses (store.py:99-102, boot.py:25-34); the ALTER is
  serialized under RLock with a PRAGMA-fallback for concurrent openers and
  converges. R12-3 revoked/disabled/expiry all fail-closed at
  resolve_machine_token; revoke_machine_token() present.
- MAJOR A — cold-trigger-drop is silently healed before the boot gate:
  AuthzStore.__init__ runs ensure_schema (CREATE ... IF NOT EXISTS) BEFORE
  wire_authz calls boot_check, so a hand-dropped critical trigger is
  recreated, schema_signature == kv baseline, and "hand-dropped trigger
  blocks multi-user boot" (CI-T-APPR-05) never fires on restart. End-to-end
  probe: drop trg_grant_no_self+trg_grant_no_cycle offline, plant a forged
  active connection_grants row (owner→same-human puppet, which the guarded
  API refuses), reopen → boot PASSES, trigger restored, forged row honored
  by has_active_grant/broker grant_checker, zero audit trail. The R12
  premise "leave it for boot_check's fail-closed refusals" is vacuous for
  the trigger-drop shape.
- MAJOR B — first_boot discriminator launders ANY tamper: boot_check mode
  is "first_boot" iff count_users()==0, and first_boot re-baselines without
  comparing (boot.py:22-24). Probe: drop column + delete kv baseline +
  DELETE FROM users → wire_authz boots, new schema_hash recorded (11bd13...),
  evidence_hmac stays dropped; owner-claim file persists, so a fresh Owner
  re-claim on the laundered DB is possible.
- OBSERVATION — revoke_machine_token() is store-only: no route/caller
  performs rotation (mint→switch→revoke) yet; mint does not refuse a
  disabled service identity; the R12 OBS on broker leases (revoke kills
  leases only at resolve time) remains open — jti is never embedded in
  leases. Bounded by lease/cap TTLs.
- Note: both MAJORs share the root cause — the gate's discriminating state
  (kv baseline, object set, user count) is compared at a point where it can
  be silently normalized (heal-before-check; first_boot re-baseline).
  Fundamental self-referential-baseline limit (attacker who rewrites kv to
  match is out of scope); these two vectors need NO kv rewrite.

## Review (adversarial B, round 14 — schema invariants / TOCTOU / migrations)

- Correct: R13-B1 pre-heal gate is genuine — raw `schema_signature` vs baseline
  compared in `AuthzStore.__init__` before `ensure_schema`; refused DB is never
  healed inside `open_store` (pinned test verified). R13-B2 discriminator works
  for the pinned scenario (wipe users+baseline, keep audit → refused).
  `_upgrade_approval_decision_columns` correctly requires baseline==old_sig and
  re-baselines (SQLite rewrites sqlite_master.sql on ADD COLUMN — confirmed).
  Migration validate-first on a scratch clone + post-apply name+body gate is sound.
- Fixed: nothing (probes only; read-only review).
- Note: first_boot still blesses a non-canonical object set — see MAJOR finding
  (audit-wipe escapes R13-B2; cheap fix: canonical weakened/missing gate in
  first_boot mode). Refusal-path audit append can raise unhandled
  OperationalError when audit_chain itself was dropped (fail-closed, ugly).
  run_migration is unwired dead code; evidence_hmac ALTER is unaudited.

## Review (round 16 — adversarial B, schema invariants + TOCTOU + upgrade paths)

- Correct: decided_at ALTER upgrade path works on old isolation.db (`_upgrade_approvals_columns` appends; probe: column added, old rows NULL). Freshness check typed correctly (ISO-parse + compare, mismatch fail-closed). Scheduler consume sits inside caller's BEGIN IMMEDIATE; all consumers route through `consume_verified_approval`. `credential_alive` machine: parsing is injection/collision-clean (uuid4-hex jti + parameterized SQL; session sids are uuid4-hex so `machine:` prefix cannot collide; `amt_`/`ast_` token prefixes distinct). Webhook gate fail-closed + constant-time compare, auth before resource-existence disclosure. SoA fiat works: hardened gate ignores flag; raw-DB flip unreachable. Concurrent first boots benign (same hash bless, idempotent stamp).

- Fixed: nothing changed in code (review findings below).
- Findings (adversarial B, round 16 — schema invariants / TOCTOU / upgrade paths):
  - MAJOR: run_migration "single transaction" is not atomic — audit.append()
    (anton/authz/boot.py:104) internally calls store.kv_set() (store.py:394-402)
    which issues conn.commit(), committing the BEGIN IMMEDIATE transaction
    mid-migration. Any failure after that point (e.g. schema_signature or the
    final kv_set("schema_hash")) leaves the DDL + WORM row durable and the
    except-branch ROLLBACK a no-op ("cannot rollback - no transaction is
    active" — reproduced). Probe: BEGIN IMMEDIATE; CREATE TABLE; kv-set commit;
    ROLLBACK → table survives. Boot then refuses on stale baseline (fail-closed,
    but the "roll back atomically" property is false). Also lines 123-128
    (trailing audit.append + re-baseline after `with store.lock`) are
    unreachable dead code. Fix: do not commit inside the migration txn — use a
    connection-level "in tx" flag so kv_set/audit defer their commit, or write
    the audit row + baseline with plain conn.execute and commit exactly once.
  - MINOR: genesis.stamp write-if-missing (__init__.py:116-118) runs on every
    boot outside any DB transaction and is not cross-process serialized; a
    crash between boot_check's baseline commit and the stamp write leaves the
    install without a stamp, so a subsequent DB wipe + boot re-blesses as
    first_boot (the commit message's "a wiped DB can never be re-blessed"
    holds only while the attacker cannot delete the file AND no crash window
    was hit). Both limits are acknowledged in comments, but the guarantee as
    stated is narrower than claimed.
  - OBSERVATION: _upgrade_approvals_columns backfill (db.py:230-236) stamps
    decided_at=ts for pre-R16 decided rows, but ts is the CREATION time — for
    any row older than the freshness window this converts an upgradable
    "no_decision_timestamp" refusal into "approval_expired" at the money/
    outbound/upskill gates. The comment "instead of bricking them" is
    misleading: post-upgrade installs must re-decide every pre-R16 approved
    sign-off older than 7 days (verified: consume returns approval_expired).
    Functionally consistent with the freshness design; operator-impact note.
  - OBSERVATION: freshness is skipped entirely on the no-secret consume path
    (db.py:318 `if max_age_s is not None` nested under `if secret:`); legacy
    single-operator mode is un-gated by design (documented boundary), and both
    wire_authz and cli.py refuse authz.enabled without decision_secret, so the
    boundary is unreachable in practice — no action required.

## Review (round 17, adversarial reviewer B, HEAD 1419653)

- **Correct — R16 atomicity fix is genuine.** Read boot.py run_migration (per-statement
  execution, in-migration-txn deferral at boot.py:84, commit at 111), store.py kv_set
  (deferred commit at store.py:402), audit.py append (deferred commit at audit.py:77).
  Ran `tests/authz`: 146 passed, 75 subtests passed.

- **Probed the exact failure shapes (+ synthetic crash):**
  - P1 real mid-apply DDL failure (CREATE UNIQUE INDEX on duplicated kv.value —
    passes empty-scratch validation, fails on live data): raised IntegrityError;
    index absent after; NO "migration" audit row; schema_hash baseline unchanged;
    only an intentional `migration_refused` row was committed (R5-4 requires
    refusals be recorded — the refusal row does not claim success).
  - P2 post-apply gate failure (MigrationIntegrityError via live-only
    missing/weakened): table rolled back, no success row, baseline untouched,
    in_migration_txn reset to False.
  - P3 sanctioned migration: DDL + "migration" audit row + refreshed schema_hash
    all committed; flag reset False.
  - P4 validation-refused hostile DROP TRIGGER: live DB untouched, refused row
    committed, baseline unchanged.
  - Crash probe: connection closed mid-transaction (BEGIN IMMEDIATE + DDL + kv
    write, no commit) leaves zero residue on reopen — R9 crash-window holds.

- **Fixed: (none required — no BLOCKER/MAJOR)**
- **Note:** literal "byte-identical" is not achievable by design: the
  spec-mandated `migration_refused` refusal row (R5-4) commits after the rollback,
  so the DB gains exactly that one row. The task's acceptance bar — no partial
  DDL, no success-claiming audit row, baseline untouched — is met.
- **Findings (non-blocking):**
  - MINOR boot.py:84-85: `in_migration_txn = True` and `BEGIN IMMEDIATE` sit
    OUTSIDE the try/except that resets the flag. If BEGIN raises (precondition:
    an already-open implicit transaction on the connection — reachable after any
    DML that raised before commit, e.g. create_user IntegrityError on duplicate
    username, which python sqlite3 legacy mode leaves in an open transaction),
    the flag leaks True and every subsequent kv_set/audit append defers its
    commit forever (silent write loss). Reproduced: after a stray open txn,
    BEGIN raises OperationalError, `kv_set` values never appear in the DB.
    Fix: move BEGIN (or the flag set) inside the try, or reset the flag when
    BEGIN itself fails. Reachability today is low — run_migration has no
    production call site yet (only exported + tests).
  - OBSERVATION boot.py:121-127: dead code after the `with store.lock` block
    (always returns at 113 or raises at 120) — a duplicated audit.append +
    re-baseline that would append a second actor-less "migration" row and refresh
    the baseline outside any transaction if a future edit removes the return.

## Review (round 18)

- **What's correct:** validate-first scratch gate raises before any live write; BEGIN
  IMMEDIATE is inside the try (round-17 flag-leak fixed — even a BEGIN failure resets
  `in_migration_txn`); per-statement execution via `complete_statement` handles trigger
  bodies; post-apply name+body gate inside the txn with ROLLBACK; `_audit_refusal` on the
  live-gate path; WORM row + deferred kv baseline commit atomically with DDL (probed: audit
  row seq present, schema_hash refreshed, `audit.verify()==True`); dead duplicate tail gone.
  `store.lock` is an RLock so audit.append inside the migration lock is reentrant-safe.
  Embedded `COMMIT;`/`END;` in migration SQL fails the scratch clone → live DB untouched.
  Full suite: 146 passed.
- **Fixed:** none (no BLOCKER/MAJOR).
- **Note:** literal "byte-identical" on rejection is false — the spec-mandated
  `migration_refused` row + `audit_head_seq` bump change bytes (R5-4 intent). Also:
  refusal rows record `actor='None'` (audit.append called without actor), so WORM
  can't attribute who attempted the migration.
- **Findings (non-blocking):**
  - MINOR boot.py:71-72 (via `_validate_migration_sql` executescript): any SQL error
    during scratch validation (e.g. migration ending in `END;`/`COMMIT;`) raises a raw
    `sqlite3.OperationalError` that escapes `run_migration` BEFORE the live txn/try —
    no `migration_refused` audit row is written and no MigrationIntegrityError wraps it.
    Probed: `CREATE TABLE junk (id INTEGER); END;` → rc OperationalError, events list
    unchanged (no refusal row), DB clean. Violates R5-4 for the error branch; callers
    catching MigrationIntegrityError see an unexpected type. Fix: wrap scratch
    executescript, call `_audit_refusal(...)` then re-raise as MigrationIntegrityError.
  - OBSERVATION boot.py:36-40 (refusal path): `migration_refused` rows store actor as
    the literal string "None" — attempted migrations are unattributable in the WORM
    chain. Fix: pass `actor=principal` (as the success path does).
