# AuthZ Consensus Review — Final Report

**Phase:** Consensus
**Scope:** Anton authz subsystem (router, broker, schema, boot, breakglass, audit) post-21605cd
**Method:** Findings from prior review rounds were put to adversarial vote; only findings that survived review are reported here.

---

## Summary

- **Surviving findings: 11** (7 findings + 3 observations + 1 positive-verifications block)
- **Discarded findings: 0**

All submitted items survived adversarial review. No findings were discarded; the two split votes (O-2 at 1/2, and one other) were retained as observations rather than rejected because they are factual, reproducible, and useful for follow-up even where severity consensus was not unanimous.

---

## MAJOR Findings

### FINDING R2A-1 — Duplicate `/api/authz/egress/channels` route (stub shadows real handler)
**Location:** `anton/authz/router.py` (~L135), introduced by 21605cd

A leftover stub returning `{"todo": True}` is registered **before** the real `create_egress_channel` handler; Starlette first-match routing makes the real handler unreachable.
*Justification:* Empirically verified — an authenticated Owner POST returns `200 {"todo": True}`, the `egress_channels` table stays empty, no create-channel audit-chain row is written — yet the middleware logs a 'mutation' row as if the action succeeded. This is a silently dead security control (REQ-EGRESS-06) with fabricated audit evidence.
**Fix:** Delete the stub route.

### FINDING R2A-2 — Broker monotonic-clock fallback sub-threshold staircase extends TTLs
**Location:** `anton/authz/broker.py` (`epoch_now`)

Each backward host-clock jump smaller than `skew_threshold_s` (300s) updates `last_wall` downward via `kv_set('last_wall', wall)` while `projected = max(wall, prev_wall)` tracks it down.
*Justification:* Verified — three consecutive −290s steps regress `epoch_now` by 870s total with **no alarm**, so every lease/cap-token expiry comparison sees an earlier "now", extending validity indefinitely via repeated small jumps. Directly violates REQ-CRED-06 ("can never extend TTLs"); the existing regression test (`FixHostClockBackwardJump`) only covers a single −1800s jump and misses the staircase.
**Fix:** Never lower `last_wall`; store `max(prev_wall, wall)` as a high-water mark.

### FINDING R2A-3 — Self-grant triggers bypassed by fabricated parties
**Location:** `anton/authz/schema.py` (`trg_grant_no_self`, `trg_grant_no_cycle`)

The WHEN clause compares two subselect human_ids; if `granter_id` names a nonexistent user, both subselects return NULL, `NULL=NULL` evaluates to NULL, and the trigger does not fire.
*Justification:* Verified — direct-SQL INSERT of a grant with `granter_id='fabricated-nonexistent-id'` and the real owner as grantee succeeds, leaving the owner holding a self-grant attributed to a phantom granter. Fails REQ-GRNT-02's guarantee that scripts cannot bypass the invariant (the CI-T-GRNT-02 direct-SQL case) whenever either party id is unknown.
**Fix:** The WHEN clause must also abort when either users lookup returns NULL (NOT EXISTS both-users check).

### FINDING R2A-4 — `run_migration` rebaselines schema hash after incomplete critical-object check
**Location:** `anton/authz/boot.py`

`run_migration` asserts only `CRITICAL_TRIGGERS`, which omits `trg_approval_no_delete`, `trg_grant_no_reparty`, `trg_grant_no_cycle_reactivate`, and the `ux_decision_once` unique index — then unconditionally rebaselines `kv.schema_hash`.
*Justification:* Verified — a migration dropping all three triggers plus the index passes and launders the weakened schema into the recorded baseline, so future boots see no mismatch. Dropping `ux_decision_once` reintroduces exactly the double-decision race 21605cd fixed; dropping `trg_approval_no_delete` weakens approval append-only. Violates REQ-PRIN-02.
**Fix:** Extend the migration gate to cover all security-critical objects before rebaselining.

### FINDING R2A-5 — WebSocket scopes bypass AuthzMiddleware and guarded auditor
**Locations:** middleware dispatch (BaseHTTPMiddleware runs for http scopes only); `audit_routes_behavioral/_walk` in `guards.py`

A WebSocketRoute added post-startup delivers data to an unauthenticated client. Compounding this, the guarded-mode route auditor **skips** flagging WebSockets and route-less mounts whenever `state.authz_middleware_active` is True — false assurance precisely where the runtime guard does not apply.
*Justification:* Verified empirically. Violates REQ-DATA-01 / CI-T-DATA-01 (fail-closed enumeration of WebSockets and dynamically registered handlers). Rated MAJOR rather than BLOCKER only because no WS routes currently ship.
**Fix:** Enforce authz on ws scope (or reject unregistered WS routes) and remove the auditor's skip condition.

---

## MINOR Findings

### FINDING R2A-6 — Break-glass elevation proceeds when all notification channels fail
**Locations:** `anton/authz/schema.py` (`trg_role_no_self_modify`), `anton/authz/breakglass.py`

The trigger checks only breakglass event existence + expiry, ignoring `channels_ok`; `request_breakglass` records the event and returns `elevated=True` with `channels_ok=0`.
*Justification:* A fully silent (undelivered) elevation satisfies the sole-admin escape hatch, contradicting REQ-APPR-03 / REQ-GRNT-03's "loud, not silent" requirement.

### FINDING R2A-7 — Audit tail-truncation detection keyed on unprotected in-file kv state
**Location:** audit log verify path

Tail-row deletion combined with rewriting `kv.audit_head_seq` makes `AuditLog.verify()` return `(True, 'ok')` — verified empirically after dropping `trg_audit_no_delete`.
*Justification:* The docstring's claim that truncation is detected "even when remaining rows are internally consistent" holds only against attackers who leave kv untouched. External WORM anchoring (REQ-AUDIT-02) remains the actual control and should be documented as such rather than implied by the in-database check.

---

## Observations

### OBSERVATION O-1 — Unmapped read routes are Viewer-readable by default
Unmapped GET/read routes pass for any authenticated role (`required_capability` returns None for non-mutating methods); the auditor only flags mutating fallback reliance. Consistent with ED-1 data-layer-canonical doctrine, but every newly added read route is Viewer-readable until explicitly mapped.

### OBSERVATION O-2 — Middleware identity chain is synthetic *(split vote: 1/2)*
Middleware mutation audit rows hardcode `workspace='default'`, `agent_instance='dashboard:<username>'`, `tool_credential='none'`. Satisfies REQ-AUTH-01's non-null requirement, but the four-identity chain is synthetic, not derived from actual execution context. Retained despite non-unanimous vote as factually accurate and actionable.

### OBSERVATION O-3 — Disabled-user sessions remain valid; wrong broker exception class
(1) `store.resolve_session` never checks `users.disabled` — an already-issued session for a disabled user stays valid (latent only; no code path currently sets `disabled=1`). (2) `BrokerClient.call` raises raw `JSONDecodeError` instead of `BrokerDegraded` on malformed responses — still fails closed, but with the wrong exception class.

---

## Positive Verifications (fixes confirmed genuine)

1. **fetch() fail-closed** — denies `peer_uid=None` and non-allowed uids with an `authorization_denied` audit row (REQ-CRED-02).
2. **Default-deny fallback works** — unmapped POST gives Viewer 403 / Owner routing-404; guarded auditor now flags fallback-reliant mutations.
3. **Grant trigger collapses service identities to owning human** — U granting U's bot is rejected.
4. **Socket lease→mint→fetch flow** completes without master-key material leaving the broker; lease op validates a live session token.
5. **Audit `_entry_hash` covers sponsor_user/workspace/agent_instance/tool_credential** — identity-column rewrites detected as ChainTampered.
6. **Both audit append-only triggers exist** and are listed in CRITICAL_TRIGGERS.
7. **Decision race closed** — `ux_decision_once` + IntegrityError→ApprovalRejected + `authorization_denied` audit.
8. **Rotation failure on revoke audited** (`grant_rotation_failed`) and alerted while revoke still proceeds.
9. **Full repo suite green** — 294 passed + 75 matrix subtests.

---

## Discard Count

**0 findings were discarded.** All 11 items that entered adversarial review survived (9 unanimously at 2/2; O-2 at 1/2 was retained as an observation).

## Recommended Priority Order

1. R2A-1 (delete stub route — trivial fix, dead security control)
2. R2A-4 (migration gate — prevents silent schema weakening)
3. R2A-3 (trigger NULL bypass)
4. R2A-2 (clock staircase)
5. R2A-5 (WS scope gap — pre-empt before any WS route ships)
6. R2A-6, R2A-7 (minor hardening)
