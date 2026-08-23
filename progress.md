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
