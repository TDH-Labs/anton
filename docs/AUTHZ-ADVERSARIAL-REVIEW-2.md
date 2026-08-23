# Second-Pass Adversarial Review

## Item verdicts

**1. Dual-layer authz (route + repository) — PARTIAL**
The bypass isn't the existing code; it's *future* code. Nothing structurally prevents a new repository function from omitting the acting-principal check — this is convention, not mechanism. Also: system jobs, migrations, and seed scripts will use a god-principal that trivially passes repo checks. Fix: CI/lint rule that fails any data-access function lacking a principal param, and a typed `SystemPrincipal` that is loudly logged and narrowly scoped — not reuse of an admin's identity.

**2. Scrubbed env + unix-socket credential service — PARTIAL**
The broker is now a god-object: anything on the host that can open the socket can request any secret. Unix socket permissions are all-or-nothing per OS user — and your executor runs as its own user, so executor-user compromise = full secret read. Fixes needed: per-execution scoped capability tokens (secret-granular, TTL'd), per-fetch audit, and the broker must refuse requests unattested to a live execution context. Otherwise you've moved the crown jewels from env vars to a socket with a bigger target painted on it.

**3. Self-grant prevention — PARTIAL**
Blocks the naive path only. Bypasses: (a) A grants to B, B grants to A — mutual escalation needs a *path* check, not pairwise; (b) grants to groups/shared resources where membership confers the right; (c) service principals creating grants on behalf of users; (d) ownership-transfer flows as a grant primitive. And if the Owner check lives only in the API layer, direct DB access (scripts, migrations) bypasses it. Put the invariant in the schema (trigger/CHECK) or accept it'll rot.

**4. Approver≠initiator constraint + break-glass — PARTIAL**
DB constraint is the strongest item here — good. Remaining gaps: same human initiating under a service account or secondary identity (constraint matches IDs, not humans); post-approval edits to the approved payload (TOCTOU — approve-then-mutate); approval records amended rather than created. Break-glass: "loud audit" assumes someone reads the audit. Sole-admin means *no second party to notice*. Require: time-boxed elevation, external-channel notification (email/webhook outside the system), and rate limits — otherwise break-glass becomes the normal path within two weeks.

**5. Injection containment via separated channel + identifier re-confirm — OPEN**
This is the weakest fix. Exact-identifier matching dies to: paraphrase ("send Bob the gist of that document"), summarization-as-exfil (user-requested summarize-then-send is indistinguishable from legitimate workflow), base64/encoding, subject/body splitting, acrostics. Worse, exfil doesn't require the send tool: calendar invites, shared-folder writes, webhook-config edits all move data out. Content matching is fundamentally brittle. You need *egress classification*: tag data at ingestion, propagate the tag through transformations (including LLM summaries), and gate every egress channel on tag level — not pattern-match payloads at the last hop. Confirmation prompts also decay into click-through under volume.

**6. Hash-chained audit + session/token hygiene — PARTIAL**
Hash chains detect tamper only if the chain head is anchored somewhere the attacker can't reach. Log on the same box as the app = attacker truncates the tail *and* rewrites the anchor. Publish periodic checkpoints to external/WORM storage or the chain is cosmetic. Fork attacks (two valid divergent chains) need sequence-number gap detection. Rotation: old tokens remain valid until natural expiry unless there's a revocation list keyed to rotation events. Role-change session revocation: verify API-token traffic is actually session-bound, else it's unaffected by revocation.

**7. Vault sidecars + owner-filtered index — PARTIAL**
Sidecar = split-brain state. Every copy/move/rename/backup-restore/git-checkout path that moves a file without its sidecar produces an orphan that defaults to... what? Default-public is fatal, default-private breaks workflows — either way the failure mode exists and will be hit. Team/shared resources break the single-owner predicate entirely. Derived artifacts (summaries, thumbnails, search caches, exported files) inherit no metadata. Migration/backfill: defaulting existing single-user data to one owner is fine until the second real user appears and discovers years of "their" data. Backfill must be explicit, reviewed, and idempotent.

## New flaws introduced by the fixes

1. **Authoritative-layer ambiguity** — with two enforcement points, tests get written against whichever is convenient; the other silently rots. Pick repo layer as canonical; route layer becomes UX sugar.
2. **Credential broker as single point of compromise** — see #2; you've concentrated risk while distributing storage.
3. **Confirmation fatigue** — Phase 1's re-confirmation prompts will be rubber-stamped at scale; each prompt costs security after ~the tenth one.
4. **Break-glass normalization** — exceptions with audit trails trend toward defaults.
5. **Self-grant rigidity drives workarounds** — legit sole-admin-adjacent setups (founder + VA) will route around via duplicate accounts, creating *unaudited* shadow admins. The workaround is worse than the hole.
6. **Sidecar consistency tax** — you've added a distributed-state problem to a filesystem. Consider embedding ACL in file header/format or xattrs instead.
7. **Chain-write contention** — hash chaining serializes audit writes; concurrent executors need a writer lock or you get forked chains from load, training operators to ignore integrity alerts.

## Summary table

| Item | Verdict |
|---|---|
| 1. Dual-layer authz | PARTIAL |
| 2. Executor isolation + credential svc | PARTIAL |
| 3. Self-grant prevention | PARTIAL |
| 4. Approver≠initiator + break-glass | PARTIAL |
| 5. Injection containment | **OPEN** |
| 6. Audit chain + session hygiene | PARTIAL |
| 7. Vault metadata + index filtering | PARTIAL |

Biggest residual risk ranking: **#5 (indirect exfiltration)** > **#2 (credential god-object)** > **migration/backfill (#7)** > everything else.