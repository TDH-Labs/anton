# Final Review Report — Consensus Phase

**Task:** consensus
**Status:** FINAL

## Summary

- **Surviving findings:** 15 (all included below)
- **Discarded findings:** Not present in the surviving set. The vote record shows **4 reviewer votes were discarded** as dissents across 4 findings that survived on split votes (findings F6, F8, F11, F15 at 1/2). Any findings rejected outright by both reviewers are not represented in this data and are therefore not enumerated.
- **Vote totals:** 26 of 30 recorded votes supported the surviving findings.

## Severity Distribution

| Severity | Count |
|---|---|
| BLOCKER | 6 |
| MAJOR | 4 |
| MINOR | 4 |
| OBSERVATION | 1 |

---

## BLOCKER Findings

### F1. Broker peer-uid attestation fails OPEN (HIGH)
`anton/authz/broker.py` gates fetch() with `if peer_uid is not None and peer_uid not in self.allowed_uids`, but `_peer_uid()` returns `None` when SO_PEERCRED / LOCAL_PEERCRED / getpeereid all fail. A `None` uid skips the rejection branch entirely — contradicting the function's own "fail closed" docstring — so any unresolvable peer (including callers where getsockopt failed in `_dispatch`) is treated as attested. Violates REQ-CRED-02. **Justification:** Unanimous (2/2). Fail-open on identity resolution defeats the entire attestation mechanism and is trivially exploitable.

### F2. Route guard allowlist fails open for unmapped routes (HIGH)
`anton/authz/guards.py required_capability()` returns `None` for every route absent from ROUTE_CAPABILITIES, and AuthzMiddleware enforces nothing when capability is None. Despite the module comment claiming unmapped mutating routes "fail closed at settings.write," no such fallback code exists. Today, any POST/PUT/PATCH/DELETE to an unmapped endpoint passes with ANY role, including Viewer. Violates REQ-DATA-01 fail-closed doctrine (ED-2). **Justification:** Unanimous (2/2). Verified against actual code — the documented fallback does not exist; an allowlist that defaults to permit is a classic fail-open design flaw.

### F3. Self-grant prevention bypassable via owned service identities (MEDIUM)
`schema.py trg_grant_no_self` compares only `NEW.granter_id = NEW.grantee_id` (principal IDs), and `grants.py create_grant` performs no human-level check. User U can create a grant between their own principal and their service account (same human_id via `store.create_service_identity`), then exercise the connection through the service principal. The human-collapse rule applied to approvals (`trg_approval_no_self_approve`) was deliberately omitted from grants. Violates REQ-GRNT-02. **Justification:** Unanimous (2/2). Concrete bypass path demonstrated end-to-end; inconsistent application of the same anti-self-dealing rule within one schema strengthens the case.

### F4. Capability-token issuance unreachable over broker socket (MEDIUM)
`broker._dispatch` implements only ping/poll/fetch. There is no socket op to request an execution lease or mint a capability token, and BrokerClient exposes only ping/fetch/poll_kill_switch. Leases/tokens are issued exclusively via in-process CredentialBroker methods, so the specced executor flow (lease + secret-granular TTL token + SO_PEERCRED, REQ-CRED-02a–c) cannot occur through the unix-socket daemon. Whoever assembles jobs in-process must hold master key material, collapsing the app/broker trust boundary of REQ-CRED-01. **Justification:** Unanimous (2/2). Architectural gap confirmed by exhaustive op enumeration — the spec's core trust-boundary claim is not implementable as built.

### F5. Audit entry hash omits four-identity columns (MEDIUM)
`audit.py _entry_hash` binds only prev_hash|seq|ts|event_type|actor|payload_json. sponsor_user, workspace, agent_instance, and tool_credential are stored but not hash-covered, so verify() passes after an attacker edits those columns on any row (e.g., rewriting sponsor attribution). REQ-AUDIT-01 requires the four-identity chain to be tamper-evident like the rest of the row. **Justification:** Unanimous (2/2). Direct hash-input inspection confirms the omission; tampering with exactly the columns the requirement names goes undetected.

### F6. Audit log is not append-only at schema level (MEDIUM) — *split vote 1/2*
Unlike authz_approvals (which has UPDATE/DELETE abort triggers), audit_chain has NO triggers and no writer restriction in code; any process opening authz.db can UPDATE/DELETE rows or forge a fully valid chain continuation (hash inputs are public; GENESIS is constant '0'*64). REQ-AUDIT-01's "append-only" and "writable only by the API process" are documentation-only. **Justification:** Survived on majority. Schema comparison against authz_approvals is concrete evidence; even if exploitability depends on DB-level access, the requirement's letter is plainly unmet in code.

## MAJOR Findings

### F7. Broker single-time-authority is fake — wall clock, not monotonic (MEDIUM)
`epoch_now() = time.time() - kv['epoch_base_wall']` remains raw wall clock relative to a fixed base. A backward system-clock jump DECREASES epoch_now, extending lease/token/break-glass windows past TTL. No monotonic fallback (time.monotonic), no skew alarm inside epoch_now — check_client_clock alarms only on CLIENT-reported drift. CI-T-CRED-06's claim that a ±30min jump leaves validity unchanged cannot hold for a backward jump on the broker host itself. **Justification:** Unanimous (2/2). The arithmetic is deterministic: backward jumps mathematically extend validity windows; the test's stated guarantee is unsound.

### F8. Approval double-decision race (TOCTOU) (MEDIUM) — *split vote 1/2*
`approvals.approve()` reads "already decided" outside the write transaction and approval_decisions has NO UNIQUE(approval_id); two concurrent approvers both pass the check and two decision rows insert. `execute_approved()` then selects one arbitrary decision row. Fix: UNIQUE index on approval_id + INSERT-based race resolution. **Justification:** Survived on majority. Race window verified by transaction-boundary analysis; non-deterministic decision selection on execution makes the consequence more than theoretical.

### F9. Grant revocation rotation failures silently swallowed (LOW)
`grants.revoke_grant` wraps `store.token_rotator(...)` in `except Exception: pass`, and token_rotator defaults to None on AuthzStore. REQ-GRNT-01's mandatory server-side refresh-token rotation on revoke can silently no-op while the audit row claims clean revocation. At minimum the failure must be audited/alerted. **Justification:** Unanimous (2/2). Bare-except swallowing of a security-mandated side effect, combined with a falsified audit trail, is unacceptable regardless of likelihood.

### F10. CI route auditor vacuous once middleware active (LOW)
`guards.audit_routes_behavioral()` checks `if not guarded` for EVERY route class, so with `state.authz_middleware_active=True` (the deployed configuration) it reports zero findings regardless of which routes exist or whether required_capability() maps them. Combined with the ROUTE_CAPABILITIES gap (F2), CI-T-DATA-01's synthetic-route test only exercises the unguarded-app branch, never real coverage. **Justification:** Unanimous (2/2). Compounding effect with F2 means the control designed to catch F2-class gaps is structurally incapable of doing so in production config.

## MINOR Findings

### F11. Four-identity audit rows are cosmetic (LOW) — *split vote 1/2*
AuthzMiddleware stamps every mutation with hardcoded workspace='default', tool_credential='none', agent_instance='dashboard:<username>'. Fields are non-null (passing CI-T-AUTH-01's letter) but carry no real workspace/agent/credential identity. **Justification:** Survived on majority. Hardcoded constants satisfy form but not substance; downstream consumers relying on these fields get misleading data.

### F12. Machine tokens never expire; no downtime-free rotation path in code (LOW)
machine_tokens has created/revoked only — no expires column, no overlapping-generation scheme beyond manually minting a second token and flipping revoked on the old one. REQ-AUTH-02's "rotatable without downtime" is achievable manually but unenforced and undocumented in code. **Justification:** Unanimous (2/2). Absence of expiry is verifiable schema-level fact; lifetime credentials contradict modern token hygiene even if rotation is manually possible.

### F13. Repo lint is name-matching and shallow (INFO)
`guards.lint_repo_file` flags functions containing '.execute(' calls lacking a parameter literally named 'principal'; renaming the param, positional-only/keyword tables, or delegating SQL through a helper evades it. visit_FunctionDef misses async defs (visit_AsyncFunctionDef undefined) — async repo functions are entirely unlinted. Acceptable as defense-in-depth given the data layer exists, but weaker than claimed. **Justification:** Unanimous (2/2). Trivially demonstrable evasions; the async-def gap means an entire class of functions is unchecked. Kept at INFO because defense-in-depth framing limits the claimed protection.

### F14. Cycle-prevention trigger has reactivation edge (INFO)
trg_grant_no_cycle runs only on INSERT and walks active=1 grants; trg_grant_no_reparty blocks party changes, but flipping a REVOKED grant back to active=1 via direct SQL UPDATE (parties unchanged) resurrects the grant without re-running the transitive cycle check. Reproduction: INSERT A->B, B->A rejected; but A->B + legacy B->A(active=0) row + UPDATE active=1 succeeds. **Justification:** Unanimous (2/2). Concrete reproduction sequence provided; kept at INFO because exploitation requires direct SQL access rather than the API surface.

## OBSERVATION

### F15. Data-layer admin bypass is by design but undocumented in-code (INFO) — *split vote 1/2*
`datalayer.get_connection_credential` short-circuits for roles holding settings.write/secrets.rotate (Owner/Admin), returning credentials WITHOUT consulting connection_grants — the grants table never constrains admins. Consistent with the RBAC table, but means ED-1's canonical layer enforces grants only for Operator/Approver/Viewer principals. **Justification:** Survived on majority. Recorded not as a defect but as a documented-design gap: intentional behavior that contradicts reasonable reader expectations of "grants constrain everyone" should be explicit in code/docs.

---

## Disposition

All 15 findings above survived adversarial review and constitute the final consensus set. **4 reviewer votes were discarded** as dissents (on F6, F8, F11, F15, each surviving at 1/2); findings rejected unanimously by reviewers during adversarial phases are not part of this dataset and are not enumerated here.

Recommended next step: prioritize remediation of the six BLOCKER items, starting with the two fail-open identity/authorization defects (F1, F2).
