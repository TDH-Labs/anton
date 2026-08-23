# Anton Multi-User Authorization — Binding Build Spec

Status: **FROZEN v1.0** (2026-08-22). This document is the binding build
spec for Anton's multi-user authZ. Implementation is measured against the
requirements herein; deviations require a spec amendment commit, not code
comments.

Inputs (traceability sources):
- `docs/MULTIUSER-GOVERNANCE.md` — design scope (SCOPING, 2026-08-22)
- `docs/AUTHZ-ADVERSARIAL-REVIEW.md` — first-pass review; findings `R1-F1..R1-F12`, required-before-ship items `R1-R1..R1-R10`
- `docs/AUTHZ-ADVERSARIAL-REVIEW-2.md` — second pass; item verdicts `R2-I1..R2-I7`, new flaws `R2-N1..R2-N7`
- `docs/AUTHZ-ADVERSARIAL-REVIEW-3.md` — third pass; open issues `R3-O1..R3-O16` with severities

## 0. Global invariant and enforcement doctrine

**INV-1 (the invariant).** *No API path, retrieval query, agent tool-call,
or egress send may return data whose ACLs exclude the acting identity.*
Tested with hostile cases at every phase (B's job asking about A's data;
injected instructions in tool output requesting cross-user fetch).

**ED-1 (enforcement doctrine).** The repository/data layer is the
*canonical* enforcement point. Route-level guards are UX sugar and
fail-closed redundancy. Where the two disagree, the data layer wins.
(R2-N1 resolves R2-I1's "authoritative-layer ambiguity" this way.)

**ED-2 (fail-closed).** Every check that cannot complete (broker down,
tag missing, sidecar missing, schema-hash mismatch) denies the operation
and surfaces an explicit degraded state. Untagged data is treated as
maximally sensitive. Missing ACL metadata defaults to private.

## 1. Identity, Sessions, RBAC

### REQ-AUTH-01 — Per-user identities replace the shared token [MUST]
All dashboard/API access authenticates as a named user principal. The
single `ANTON_DASHBOARD_TOKEN` is replaced by per-user sessions plus one
machine token bound to a distinct service identity. Every action carries
the four-identity chain: `sponsor user → workspace → agent instance →
tool credential`; audit rows record all four.
Traces: GOV §1; R1-F7; R1-F12 (first-run Owner claim must be explicit,
not predictable).
Test: `CI-T-AUTH-01` — request with legacy shared token returns 401 after
migration flag flips; every audited mutation row has all four identity
fields non-null.

### REQ-AUTH-02 — Session lifecycle: server-side, revocable, device-bound [MUST]
Sessions are server-side records (not long-lived bearer JWTs). Each
session is bound to a device record visible in a per-user session list
with per-device revoke. Revocation on role change, grant change, or
password reset takes effect immediately: API-token traffic is validated
against session state on every request (no cached auth decisions).
Login enforces rate limiting + lockout. Machine tokens use separate
signing material from user sessions and are rotatable without downtime.
Traces: R1-R5; R2-I6; R3-O3.
Test: `CI-T-AUTH-02` — revoke admin's session mid-job; next API call from
that session 401s; outstanding capability tokens issued under it are
killed within one executor poll interval (see REQ-CRED-04); machine-token
ciphertext differs from session-token ciphertext.

### REQ-AUTH-03 — RBAC roles are explicit capability sets [MUST]
Roles: Admin, Approver, Operator, Viewer (+ Owner in single-operator mode,
REQ-APPR-06). Capability→role mapping lives in one declarative table in
code; no implicit hierarchy ("Approver" does not subsume "Operator").
Admins cannot approve their own raises; Operators cannot approve or manage
users; Viewers get read-only tool tiers only.
Traces: GOV §2; R1-F3.
Test: `CI-T-AUTH-03` — matrix test asserting for each role×capability the
declared allow/deny against actual route behavior, including negative
cases (Viewer invoking run, Operator approving).

## 2. Route + Data-Layer Authorization

### REQ-DATA-01 — Dual-layer enforcement, repository canonical [MUST]
Every HTTP/WS/MCP route carries `require_user(capability)`. Independently,
every data-access function takes an acting-principal parameter and applies
ownership/ACL predicates itself. A CI lint fails any repository function
performing I/O without a principal parameter; a fail-closed route-audit
test suite runs in CI (not just startup) enumerating WebSockets, static
mounts, mounted sub-apps, lifespan/background tasks, and dynamically
registered MCP handlers.
Traces: R1-F1, R1-F2, R1-R1, R1-R9; R2-I1; R2-N1.
Test: `CI-T-DATA-01` — synthetic route registered post-startup with no
guard fails CI; repo function with missing principal param fails lint;
internal call of `get_connection_credential()` without principal raises.

### REQ-DATA-02 — Executor-side checks before tool execution [MUST]
The executor re-verifies ACLs before each tool call against the calling
principal's current grants (polling revocation state — see REQ-CRED-04),
never trusting the route layer's earlier decision.
Traces: R1-R1; R2-I3.
Test: `CI-T-DATA-02` — grant revoked between job start and tool call;
executor refuses the call and emits an authorization-denied audit row.

### REQ-DATA-03 — No god-principal in normal paths [MUST]
Background jobs, schedulers, and seed scripts run as `SystemPrincipal`
(§9). It passes repo checks but is loudly logged, narrowly scoped per
invocation, and never equals or borrows a human admin identity.
Traces: R2-I1.
Test: `CI-T-DATA-03` — any audit row written by SystemPrincipal outside
the allowlisted job registry fails a CI assertion / runtime alarm.

## 3. Credential Broker

### REQ-CRED-01 — Broker architecture [MUST]
A dedicated credential-broker daemon holds all connector secrets,
encrypted at rest with its key outside any path readable by the executor
or the app process. Secrets never enter prompts, env vars, or process
environments wholesale. Executors obtain secrets only via the broker over
a unix socket.
Traces: R1-F5, R1-F11, R1-R2, R1-R8; R2-I2.
Test: `CI-T-CRED-01` — executor process env contains no secret values
(canary strings planted in secrets.yaml absent from `/proc/self/environ`
of executor); direct DB read of credentials table yields ciphertext.

### REQ-CRED-02 — Per-execution scoped capability tokens [MUST]
Broker issues short-TTL capability tokens that are (a) secret-granular
(one token names exactly the connections/scope it may read), (b)
time-boxed to the execution, (c) attested to a live execution context
(broker refuses requests not carrying valid execution attestation).
Per-fetch audit rows record requester, secret id, and purpose.
Traces: R2-I2; R1-F6.
Test: `CI-T-CRED-02` — unattested socket request denied; token replay
after TTL denied; token scoped to connection A cannot read connection B;
each fetch produced exactly one audit row.

### REQ-CRED-03 — Minimal-callback machine token [MUST]
The executor's callback identity may invoke only "submit tool result"
class endpoints — never user-scoped reads/writes. Compromise of the
executor yields no API-wide access. Documented rotation + incident
playbook for stolen machine tokens.
Traces: R1-F6; R1 nice-to-haves (incident playbook, adopted).
Test: `CI-T-CRED-03` — machine token attempting any endpoint outside its
allowlist receives 403 and generates an alert row.

### REQ-CRED-04 — Revocation reach-through and kill switch [MUST]
The broker checks a revocation list on every issuance AND executors poll
kill-switch state before each tool call (not just at job start). A revoked
admin's outstanding tokens die within one poll interval.
Traces: R3-O3; R2-I6.
Test: `CI-T-CRED-04` — kill switch flipped mid-execution; next tool call
fails closed with explicit "revoked" state, not a silent retry loop.

### REQ-CRED-05 — Broker availability posture [SHOULD]
Broker runs under systemd/Docker health check with auto-restart.
Executors fail closed but surface an explicit "broker unavailable" state.
Traces: R3-O12.
Test: `CI-T-CRED-05` — broker SIGKILLed; executor reports degraded state
within one poll interval and does not loop-retry silently.

### REQ-CRED-06 — Broker is the single time authority [MUST]
TTL validation and break-glass windows are computed against the broker's
signed issuance epoch (monotonic fallback), not wall clock across
processes. Skew beyond threshold raises an alarm rather than extending
windows silently.
Traces: R3-O4.
Test: `CI-T-CRED-06` — system clock jumped ±30 min on a worker process;
token validity and break-glass window unchanged relative to broker epoch;
alarm fired.

## 4. Connection Grants & Self-Grant Prevention

### REQ-GRNT-01 — Grants table with scope recording [MUST]
Connection grants record: granter actor, grantee principal, connection,
scope level (`use`/`full`), **granted OAuth scopes**, policy version, and
timestamps. `full` never exposes refresh tokens to the grantee; revoke
triggers server-side token rotation.
Traces: R1-F3, R1-F11, R1-R8; R3-O9.
Test: `CI-T-GRNT-01` — `full` grant response inspected: refresh token
absent; revoke then reuse of old refresh token fails against provider
mock.

### REQ-GRNT-02 — Self-grant prevention enforced in schema [MUST]
SQLite triggers/constraints enforce: no principal may create, modify, or
delete a grant affecting its own privileges (including its own roles).
The invariant lives in the database, not the API layer, so scripts and
migrations cannot bypass it. Path-based check (transitive): A→B→A mutual
escalation chains are rejected, not just pairwise self-grants. Ownership
transfer flows are treated as grants and subject to the same rule.
Traces: R1-F3, R1-R3; R2-I3 (bypasses a–d).
Test: `CI-T-GRNT-02` — direct SQL insert of self-grant rejected by
trigger (API bypass attempt); A-grants-B, B-grants-A sequence rejected;
ownership-transfer-as-grant rejected when self-directed.

### REQ-GRNT-03 — Sole-admin escape hatch is loud, not silent [MUST]
Where self-modification is genuinely unavoidable (sole Owner), it requires
the break-glass path (REQ-APPR-03/04) with time-boxed elevation, external
notification, rate limits — never a quiet UPDATE.
Traces: R1-F3, R1-R3; R2-N4, R2-N5.
Test: `CI-T-GRNT-03` — sole-admin self-elevation without break-glass
artifacts impossible at schema level; break-glass path writes mandatory
audit + notification records.

### REQ-GRNT-04 — OAuth scope hygiene [SHOULD]
Granted-vs-used scope diff surfaced to Admin periodically; config/CI check
flags connectors requesting write scopes unused in code; downscoping via
token exchange where the provider supports it.
Traces: R3-O9.
Test: `CI-T-GRNT-04` — fixture connector granted mail+drive+contacts but
code uses calendar-read only; report flags all three; release gate fails.

## 5. Approvals

### REQ-APPR-01 — approver ≠ initiator, enforced as a DB constraint [MUST]
Approval records are append-only creations (never amendments) carrying
initiator id, approver id, approved payload hash, and policy version. A
schema constraint rejects approval where approver == initiator. TOCTOU:
any edit to the payload after approval invalidates the approval (hash
mismatch detected at execution time).
Traces: R1-F4, R1-R4; R2-I4 (TOCTOU, amendment, secondary-identity gaps).
Test: `CI-T-APPR-01` — same-id approval rejected at DB level; payload
mutated post-approval causes execution-time rejection + audit row;
UPDATE on approval row rejected by trigger.

### REQ-APPR-02 — Human-binding of approvals [MUST]
Initiator/approver matching compares the human sponsor behind each
identity, so initiating under a service account or secondary identity
does not satisfy approver ≠ initiator.
Traces: R2-I4.
Test: `CI-T-APPR-02` — initiator acts via service identity owned by user
U; U attempts approval; rejected (human-id match).

### REQ-APPR-03 — Break-glass with dual-channel external notification [MUST]
Break-glass requires: time-boxed elevation, external notification over two
independently configured channels (configured at setup); success if either
delivers, undelivered channel flagged. Rate limits prevent normalization;
elevation windows expire automatically.
Traces: R1-F4; R2-I4; R2-N4; R3-O7.
Test: `CI-T-APPR-03` — one channel mocked as down; break-glass completes
and flags the failure; second break-glass inside rate-limit window is
denied; elevation auto-expires.

### REQ-APPR-04 — Offline recovery artifact [MUST]
At install, generate an offline recovery artifact (recovery codes / signed
recovery token) stored off-machine by the operator. Its use works with all
channels down and no second approver, triggers mandatory post-hoc audit
entry, and forces re-keying of broker secrets.
Traces: R3-O6.
Test: `CI-T-APPR-04` — full lockdown simulation (all channels down,
Owner factor lost); recovery artifact unlocks; audit entry written;
broker re-key executed and old secrets invalid.

### REQ-APPR-05 — Single-operator mode [MUST]
Declared explicitly at install when Owner=Admin=Approver=Operator is one
human. In this mode: (a) sensitive-action constraints downgrade to
time-delay + loud self-attestation instead of hard blocks; (b) a
schema-hash of ALL triggers/constraints is recorded in the audit chain at
boot — hand-dropped triggers are detected at next startup and block boot
into multi-user mode; (c) RBAC collapses to Owner-only with the other four
roles disabled, never fake-assigned. Full mode available for teams ≥ 2.
Traces: R3-O5.
Test: `CI-T-APPR-05` — trigger dropped out-of-band via sqlite3 CLI; boot
detects hash mismatch and refuses multi-user start; single-operator mode
delay+attestation path exercised; role table shows Owner-only.

## 6. Egress Tag Classification

### REQ-EGRESS-01 — Tags assigned at ingestion AND at live fetch [MUST]
Every datum entering the system carries provenance + classification tag.
Ingestion tags documents. Live tool results are stamped by the executor at
fetch time: browser content defaults UNTRUSTED/high-caution; shell output
inherits the execution's minimum tag. Untagged = maximally sensitive.
Traces: R2-I5; R3-O13.
Test: `CI-T-EGRESS-01` — browser scrape flows into LLM context with
UNTRUSTED stamp present; shell output carries execution-minimum tag;
synthetic untagged datum treated as top-secret at gate.

### REQ-EGRESS-02 — Tag propagation through transformations including LLM summaries [MUST]
Summaries, joins, caches, and derived artifacts inherit the max tag of
inputs. LLM-generated summaries inherit the max tag of everything in the
generating context — enforced structurally (context-tag accumulator), not
by scanning output text. Caches are keyed by principal + tag, never
shared across principals.
Traces: GOV §4d; R1-F8; R2-I5; R2-N3.
Test: `CI-T-EGRESS-02` — summarize a SECRET doc; summary object carries
SECRET; cache poisoning attempt (same query, different users) returns
disjoint entries.

### REQ-EGRESS-03 — Egress gates on tag level, not payload pattern-matching [MUST]
Before ANY outbound channel (email, Slack, webhook, channel post,
calendar invite, shared-folder write, webhook-config edit), the gate
checks recipient clearance vs. payload tag. Mismatch = block + flag, not
warn. Confirmation prompts are budgeted (fatigue control): repeated
prompts escalate to hard block rather than decaying into click-through.
Traces: GOV §4d; R2-I5 (paraphrase/base64/splitting bypasses);
R2-N3; R3-O16.
Test: `CI-T-EGRESS-03` — exfil attempts via paraphrase, base64 encoding,
subject/body split, calendar-invite carrier, and webhook-config edit each
blocked by tag mismatch regardless of content shape.

### REQ-EGRESS-04 — Cross-tag aggregation rule with k-anonymity floor [MUST]
Summary/join outputs whose constituent count < k (k=5 default, config
min 3) OR whose sources span classification boundaries require mandatory
re-review before egress — enforced at the gate, advisory nowhere.
Traces: R3-O14.
Test: `CI-T-EGRESS-04` — join of 4 PUBLIC records yielding one client's
identifiable profile held for review; k configurable; boundary-spanning
summary flagged even when individually low-tag.

### REQ-EGRESS-05 — Tag freshness on direct vault edits [MUST]
File-watcher/inotify queue re-classifies edited vault files; embeddings
are invalidated on content-hash change until re-tagged; the egress gate
re-verifies tag freshness (content-hash match) before send; stale =
blocked.
Traces: R3-O15.
Test: `CI-T-EGRESS-05` — file edited out-of-band; embedding retrieval of
new content blocked pending re-tag; egress of stale-tagged content
rejected on hash mismatch.

### REQ-EGRESS-06 — Egress channel creation is privileged [MUST]
Creating/deleting an egress channel (new webhook connector etc.) is
Approver-gated and audit-chained; Operators cannot add channels.
Traces: R3-O16.
Test: `CI-T-EGRESS-06` — Operator POST of new webhook connector → 403 +
audit row; Approver creation succeeds and appears in chain.

### REQ-EGRESS-07 — Injection containment [MUST]
Tool output (including MCP server output) is delivered in structured,
delimited data channels, never concatenated into the instruction stream.
Any gated action whose parameters reference content originating from tool
output requires interactive confirmation; cross-workspace identifier hits
in tool output trigger re-confirmation. Browser/shell tools disabled by
default for non-Owner users until the credential proxy exists.
Traces: R1-F9, R1-R6; R2-I5 residual.
Test: `CI-T-EGRESS-07` — attacker page instructing "email workspace X
invoices" produces a confirmation requirement, not an action; delimited
output containing instruction-like text cannot invoke tools directly.

## 7. Audit: WORM-Anchored Hash Chain

### REQ-AUDIT-01 — Hash-chained, four-identity, append-only log [MUST]
Append-only SQLite log with per-entry hash chaining and monotonic
sequence numbers. Coverage: authz denials, grant changes, approvals,
logins, failed authorizations, privilege changes, migration events
(REQ-MIGR-01), break-glass, recovery-artifact use. Writable only by the
API process; the executor cannot write it. Fork detection via sequence-
gap detection.
Traces: R1-F10, R1-R7; R2-I6; R2-N7 (writer lock serializes chain writes).
Test: `CI-T-AUDIT-01` — tamper with one row ⇒ verification fails; delete
tail entries ⇒ gap detection fires; concurrent writers produce a single
valid chain (no forks under load test).

### REQ-AUDIT-02 — External WORM anchoring, async best-effort [MUST]
Periodic chain-head checkpoints publish to external/WORM storage the app
cannot alter. Checkpointing is asynchronous best-effort: local durable
append-only buffer survives indefinitely; external-storage outage NEVER
blocks application writes; lag alerts fire above threshold.
Traces: R2-I6 (anchor reachable-by-attacker flaw); R3-O11.
Test: `CI-T-AUDIT-02` — WORM sink offline for hours: writes continue,
buffer retains entries, lag alert raised, catch-up checkpoint verifies on
restore; simulated tail-truncate+rewrite fails anchor verification.

### REQ-AUDIT-03 — Restore re-anchor ceremony [MUST]
Restores follow a documented ceremony: (1) back up vault + sidecar DB +
audit atomically; (2) restore all three together; (3) append a signed
restore manifest to the chain as a checkpoint-of-checkpoints, declaring
the pre-restore head, so post-backup entries are distinguishable from
attacker truncation; (4) embedding-index rebuilds derive ACLs from the
sidecar DB only, never file paths; (5) ceremony completion requires the
break-glass-grade acknowledgment.
Traces: R3-O1.
Test: `CI-T-AUDIT-03` — restore drill: chain verifies post-ceremony;
entries after backup point flagged as post-restore, not tamper; index
rebuild honors sidecar ACLs (owner filters intact); skipping the manifest
step fails verification.

## 8. Vault Sidecars & Owner-Filtered Index

### REQ-VAULT-01 — Sidecar metadata with consistency discipline [MUST]
Each vault file has an ACL sidecar (owner, visibility, tags, content
hash). Consistency rules: copy/move/rename paths are brokered operations
that move the sidecar atomically; orphan detection at scan treats a
missing sidecar as PRIVATE (fail-closed), surfaces an orphan report;
backup/restore includes sidecars atomically (REQ-AUDIT-03).
Traces: R1-F8, R1-R10; R2-I7; R2-N6 (xattr/header alternative evaluated:
sidecar chosen, with brokered-path mitigation).
Test: `CI-T-VAULT-01` — file copied via brokered path carries sidecar;
orphan file created out-of-band defaults PRIVATE in retrieval; orphan
report lists it.

### REQ-VAULT-02 — Authorization-first retrieval everywhere [MUST]
Vault/memory/embedding search filters by caller ACLs BEFORE chunks enter
model context (hard WHERE clauses; pipeline-ordering rule). Index entries
carry owner+visibility+tag; vector-search path filtered identically to
SQL path. Team/shared resources use membership predicates, not
single-owner assumptions. Derived artifacts (summaries, thumbnails,
caches, exports) inherit metadata at creation.
Traces: GOV §4b; R1-F8; R1-R10; R2-I7.
Test: `CI-T-VAULT-02` — hostile retrieval parity fuzz: for random
principal/resource pairs, SQL path and vector path return identical
visibility verdicts; derived summary of B's doc invisible to A.

### REQ-VAULT-03 — Explicit, reviewed, idempotent backfill [MUST]
Migration of existing single-user data assigns ownership via an explicit,
reviewable backfill manifest (idempotent, re-runnable), not silent
defaulting at second-user creation time.
Traces: R2-I7.
Test: `CI-T-VAULT-03` — backfill run twice yields identical state;
unreviewed default-owner assignment impossible without manifest.

## 9. Principals: SystemPrincipal / MigrationPrincipal

### REQ-PRIN-01 — Typed non-human principals [MUST]
`SystemPrincipal` (background jobs, schedulers, seeds) and
`MigrationPrincipal` (Alembic/raw-SQL migrations) are distinct typed
principals — loudly logged, narrowly scoped, never aliases of a human
admin, never interchangeable. Repo lint accepts only these two non-human
principal types.
Traces: R2-I1; R3-O2.
Test: `CI-T-PRIN-01` — type-level test: constructing a repo call with an
admin user object where a principal type is required fails typing/lint;
SystemPrincipal invocation logged with job registry entry.

### REQ-PRIN-02 — Migrations are constrained and recorded [MUST]
Migration runner operates exclusively under MigrationPrincipal; every
migration is hash-recorded in the audit chain; post-migration CI asserts
the schema-hash (triggers/constraints still exist and match — see
REQ-APPR-05(b)); a migration weakening the approver≠initiator constraint
or self-grant triggers fails the pipeline.
Traces: R3-O2; R2-I3(d).
Test: `CI-T-PRIN-02` — hostile fixture migration drops the approval
trigger; post-migration schema-hash assertion fails CI; migration event
present in audit chain.

## 10. MCP Supply Chain Rules

### REQ-MCP-01 — Isolation per MCP server [MUST]
Each MCP server runs as its own OS user/container with its own scoped
broker identity; capability tokens are bound per-server with per-tool
scopes; an MCP server can only reach secrets explicitly granted to it.
Traces: R3-O8.
Test: `CI-T-MCP-01` — malicious-fixture MCP server requesting a secret
outside its grant denied; process isolation verified (different uid /
container boundary).

### REQ-MCP-02 — Allowlist, pinning, SBOM [MUST]
MCP servers admitted via allowlist + version pinning + per-release SBOM;
unpinned or unlisted servers refuse to register. Locked dependencies and
automated CVE scan gate releases.
Traces: R3-O8, R3-O10.
Test: `CI-T-MCP-02` — registry sync of unpinned server rejected; SBOM
generated per release artifact; CVE-scan stage blocks on critical finding
(fixture CVE injected).

### REQ-MCP-03 — MCP output is untrusted input [MUST]
MCP server output enters through the same tagged/untrusted data channel
as browser content (UNTRUSTED default), injection-screened, never treated
as trusted tool results or instructions.
Traces: R3-O8; R1-F9; REQ-EGRESS-01/07.
Test: `CI-T-MCP-03` — fixture MCP output containing instruction text is
delimited, tagged UNTRUSTED, screened, and cannot trigger a gated action
without confirmation.

## 11. Convergence Threshold & Framework Mapping

### CONV-1 — Convergence definition [BINDING]
This spec is considered converged — and implementation shippable — only
when **two consecutive independent adversarial reviews issue PROCEED
verdicts with zero BLOCKER and zero MAJOR findings** against the
implemented system (not merely this document). MINOR findings may remain
open provided each has a tracked remediation item. Reviews count as
"independent" only if produced by disjoint reviewer models/processes with
access to running code and the hostile-test corpus. A MAJOR found after a
PROCEED resets the counter to zero.

### CONV-2 — Framework mapping [MUST]
| Spec area | NIST AI RMF | SOC 2 |
|---|---|---|
| INV-1 invariant + hostile tests | MEASURE-2.x, MANAGE-2.x | CC6.1 (logical access controls) |
| Identity/sessions/RBAC (§1) | MAP-1.x (roles/context), MANAGE-4.x | CC6.1, CC6.2 |
| Dual-layer authz + fail-closed (§2, ED-2) | MANAGE-2.x | CC6.1 |
| Credential broker (§3) | MANAGE-3.x | CC6.1 (least privilege), CC6.3 (role change/modification removal) |
| Grants, approver≠initiator, SoD (§4–5) | GOVERN (SoD expectations) | CC6.1, CC6.3 |
| Egress tagging/DLP (§6) | MEASURE-2.x | CC6.1 (data-in-transit protection of classified data) |
| WORM audit + re-anchor (§7) | MANAGE-4.x (incident detection) | CC7.2 (adjacent), CC6.1 evidence |
| Vault ACLs + authz-first retrieval (§8) | MAP-3.x (data sensitivity) | CC6.1, CC6.7 (adjacent) |
| Principals/migrations (§9) | MANAGE-3.x | CC8.1 (adjacent), CC6.3 |
| MCP supply chain (§10) | MAP-5.x, MANAGE-5.x | CC6.1 |

SOC2 CC6.1/CC6.3 anchors: CC6.1 — logical access security measured
against the INV-1 hostile-test corpus as control evidence; CC6.3 —
role/grant changes remove access timely, evidenced by REQ-AUTH-02
revocation tests, REQ-CRED-04 kill-switch latency, and REQ-PRIN-02
constraint-integrity assertions.

## Appendix A — Finding coverage matrix

| Finding | Requirement(s) |
|---|---|
| R1-F1/F2, R1-R1/R9 | REQ-DATA-01, REQ-DATA-02 |
| R1-F3, R1-R3 | REQ-GRNT-01..03 |
| R1-F4, R1-R4 | REQ-APPR-01..04 |
| R1-F5/F11, R1-R2/R8 | REQ-CRED-01..03, REQ-GRNT-01 |
| R1-F6 | REQ-CRED-02, REQ-CRED-03 |
| R1-F7 | REQ-AUTH-01, REQ-AUTH-02 |
| R1-F8, R1-R10 | REQ-VAULT-01..02, REQ-EGRESS-02 |
| R1-F9, R1-R6 | REQ-EGRESS-07, REQ-MCP-03 |
| R1-F10, R1-R7 | REQ-AUDIT-01, REQ-AUDIT-02 |
| R1-F12 | REQ-AUTH-01 (explicit first-run Owner claim) |
| R2-I1, R2-N1 | REQ-DATA-01 (ED-1 canonical layer), REQ-DATA-03 |
| R2-I2 | REQ-CRED-01..02 |
| R2-I3 | REQ-GRNT-02 (path check), REQ-GRNT-03 |
| R2-I4 | REQ-APPR-01..03 |
| R2-I5 | REQ-EGRESS-01..04, 07 |
| R2-I6 | REQ-AUTH-02, REQ-AUDIT-01..02, REQ-CRED-04 |
| R2-I7, R2-N6 | REQ-VAULT-01, REQ-AUDIT-03 |
| R2-N2 | REQ-CRED-02 (attestation) |
| R2-N3/N4/N5 | REQ-EGRESS-03, REQ-APPR-03, REQ-GRNT-03 |
| R2-N7 | REQ-AUDIT-01 (writer lock) |
| R3-O1 | REQ-AUDIT-03 |
| R3-O2 | REQ-PRIN-01..02 |
| R3-O3 | REQ-AUTH-02, REQ-CRED-04 |
| R3-O4 | REQ-CRED-06 |
| R3-O5 | REQ-APPR-05 |
| R3-O6 | REQ-APPR-04 |
| R3-O7 | REQ-APPR-03 |
| R3-O8 | REQ-MCP-01..03 |
| R3-O9 | REQ-GRNT-01, REQ-GRNT-04 |
| R3-O10 | REQ-MCP-02 |
| R3-O11 | REQ-AUDIT-02 |
| R3-O12 | REQ-CRED-05 |
| R3-O13 | REQ-EGRESS-01 |
| R3-O14 | REQ-EGRESS-04 |
| R3-O15 | REQ-EGRESS-05 |
| R3-O16 | REQ-EGRESS-06 |

## Appendix B — Open items carried forward (non-blocking)

- OPEN-1: SSO (OIDC Google Workspace / Entra ID) — Phase 4 per GOV §6;
  sessions spec is SSO-compatible.
- OPEN-2: Per-user budgets with admin ceilings — Phase 4.
- OPEN-3: Session binding heuristics (UA/IP drift alerts) — nice-to-have.
- OPEN-4: Immutable audit to a second independent container — enhancement
  over REQ-AUDIT-02.
- OPEN-5: k value calibration study for REQ-EGRESS-04 per deployment.
