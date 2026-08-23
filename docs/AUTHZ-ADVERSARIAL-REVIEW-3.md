**OPEN ISSUES — Third-Pass Adversarial Review**

**Operational/lifecycle**

1. **BLOCKER — Restore breaks the audit chain and ACLs simultaneously.** A restore from backup rewinds the hash chain; sequence-gap detection then flags every post-backup entry as tamper, and there's no defined procedure distinguishing "restore" from "attacker truncation." Worse, restoring vault markdown without its sidecar-metadata DB silently drops ownership/ACL state — the embedding index rebuild then applies wrong owner filters. *Fix:* Define a documented re-anchor ceremony (signed restore manifest appended to chain as a checkpoint-of-checkpoints); back up vault + sidecar DB + audit log atomically; make embedding-index rebuilds derive ACLs from sidecar DB only, never from file paths.

2. **MAJOR — Migrations bypass your own authz lint.** CI lint requires principal params in repository code, but Alembic/SQL migrations are raw SQL touching grants tables, RBAC rows, and the approver≠initiator constraint. An upgrade migration can silently weaken constraints. *Fix:* Migration runner runs under a distinct `MigrationPrincipal`, every migration is hash-recorded in the audit chain, and post-migration CI verifies triggers/constraints still exist (schema-hash assertion).

3. **MAJOR — No multi-device/concurrent-session model.** Per-user sessions with no device binding means a leaked laptop session is indistinguishable from the owner's phone. Revocation also doesn't reach already-issued capability tokens until TTL expiry — a revoked admin keeps executing for up to TTL. *Fix:* Session list UI with per-device revoke; broker checks a revocation list on every token issuance AND supports a kill-switch invalidating outstanding tokens immediately (executors poll before each tool call, not just at start).

4. **MINOR — Clock skew.** TTL validation and break-glass windows use wall clock across processes. On Umbrel boxes NTP is often broken; skew lengthens break-glass windows and shortens/extends token TTLs unpredictably. *Fix:* Broker is the single time authority — tokens carry broker-signed issuance epoch; windows computed against broker clock, with monotonic fallback and skew alarm.

**Small-business reality**

5. **BLOCKER — Design collapses or gets silently gutted for 1-person shops.** With Owner=Admin=Approver=Operator as one person, approver≠initiator blocks *every* sensitive action, so the realistic outcome is someone drops the SQLite triggers by hand (`sqlite3 app.db "DROP TRIGGER..."`) — no detection, no logging. Five roles become one role and the whole RBAC layer is ceremony. *Fix:* Explicit **single-operator mode** declared at install: constraints downgrade to (a) time-delay + loud self-attestation instead of hard blocks, (b) schema-hash of all triggers/constraints recorded in the audit chain so trigger-dropping is detected at next boot, (c) RBAC collapses to Owner-only with the other four roles disabled rather than fake-assigned. Full mode remains available for teams ≥2.

6. **BLOCKER — Self-lockout is unrecoverable.** Break-glass requires approver≠initiator and external notification — but in a 1-person shop the initiator *is* the only approver, and if the notification channel (email/Slack) is down or the Owner lost their factor, break-glass deadlocks. Total lockout of a small business. *Fix:* Offline recovery artifact generated at install (recovery codes or a signed recovery token stored printed/off-machine); using it triggers mandatory post-hoc audit entry and forces re-keying of credentials broker secrets.

7. **MAJOR — Break-glass notification is a single point of failure even for teams.** Notification depends on one external channel; outage = break-glass unusable = availability incident. *Fix:* Two independent channels configured at setup; break-glass succeeds if either delivers, with the undelivered channel flagged.

**Supply chain**

8. **BLOCKER — MCP servers are untrusted code with broker adjacency.** The credential broker refuses "unattested requests," but attestation of third-party MCP server code proves nothing — a compromised or malicious MCP server is a *legitimate* client that can request capabilities and exfiltrate. Nothing says MCP servers run isolated. *Fix:* Run each MCP server as its own OS user/container with its own scoped broker identity; capability tokens bound per-server with per-tool scopes; allowlist + version pinning + SBOM; treat MCP server output as untrusted input data (tagged, injection-screened), never as trusted tool results.

9. **MAJOR — OAuth connector over-scoping unchecked.** Grants table records *that* a connection was approved, not *which scopes* were granted vs. actually used. Users click through Google/Microsoft consent screens granting mail+drive+contacts when the feature needs read-only calendar. *Fix:* Record granted scopes in the grants table; runtime downscoping via token exchange where the provider supports it; periodic diff of granted-vs-used scopes surfaced to Admin; CI/config check flags connectors requesting write scopes unused in code.

10. **MINOR — Dependency hygiene unspecified.** No lockfile policy, vuln scanning, or update cadence stated for a product shipping Docker images to small businesses. *Fix:* Locked deps, SBOM per release, automated CVE scan gating releases.

**Availability/DoS-as-security-bug**

11. **MAJOR — Audit checkpoint failure must never gate writes.** As specced, checkpoint-to-WORM failure risks blocking all work — and an S3 outage or expired WORM bucket credential becomes a remote (or accidental) denial of service against the customer. *Fix:* Checkpoints async best-effort; local durable append-only buffer survives indefinitely; alert on lag; writes never block on external storage.

12. **MINOR — Credential broker is a SPOF.** Socket daemon crash halts every executor. *Fix:* systemd/Docker health check + auto-restart; executors fail closed but surface a clear "broker unavailable" state rather than silent retry loops.

**Tag-propagation model**

13. **BLOCKER — Live tool output has no tags at all.** Classification happens "at ingestion," but the highest-risk data path — browser scrapes and shell command output fetched *at runtime* — never passes through ingestion. Untracked web content (potentially attacker-controlled, injection-laden) enters the LLM context untagged and unclassified, then flows to egress channels gated on… nothing. This holes the entire containment model below the waterline. *Fix:* Executor stamps every tool result with provenance + classification (browser fetches default to UNTRUSTED/high-caution; shell output inherits the execution's minimum tag); egress gate treats untagged as maximally sensitive; injected-content detection runs on live fetches same as ingested docs.

14. **MAJOR — Cross-tag aggregation/inference rule undefined.** Spec propagates tags through transformations including summaries, but says nothing about combination effects: summarizing 500 PUBLIC records can reveal one SECRET record's content; joining low-tag datasets can infer high-tag facts (revenue × headcount × geography ⇒ identifiable client). Max-tag propagation alone doesn't cover this. *Fix:* Summary/join operations inherit max tag of inputs **and** flag aggregate outputs whose constituent count is small (<k) or whose sources span classification boundaries for mandatory re-review; define k and enforce at the egress gate, not just advisory.

15. **MAJOR — Direct vault edits desynchronize tags.** Markdown files are user-editable outside the sidecar; edits/copy/move leave stale tags, and the owner-filtered embedding index then retrieves chunks whose real content no longer matches their classification. *Fix:* File-watcher/inotify re-classification queue; embeddings invalidated on content hash change until re-tagged; egress gate re-verifies tag freshness (hash match) before send.

16. **MINOR — Egress channels themselves are unguarded config.** Gating exists per channel level, but who can *create* an egress channel (new webhook connector) isn't specified — an Operator-level compromise adds a channel and waits. *Fix:* Channel creation/deletion is Approver-gated and audit-chained.

---

**VERDICT: CHANGES REQUIRED**