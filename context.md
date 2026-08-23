Research complete. Findings written to `/Users/ai/harbor-sas/context.md` (201 lines, ~29KB).

## Summary

**Verdict: No commercial product combines Anton's full stack.** Every contender owns one or two of its axes; none ship them integrated in a single self-hosted box, none enforce separation-of-duties at the DB level, and none claim an adversarially-verified build as a shipped property.

**Method note:** `web_explore` wasn't injected into this scout session's toolset, so I discovered the pi-web-agent extension was installed but inactive, and drove it via nested `pi -p` runs (opencode-zen-free provider) — 7 research passes across the 4 categories, with `pi-worker-search/fetch` fallback when DuckDuckGo rate-limited. Provenance is marked **(verified)** vs **(inferred)** throughout.

**Key findings per category:**
- **Enterprise platforms** (Copilot Studio, Agentforce, Bedrock Agents, Vertex/Agentspace, ServiceNow, Moveworks, Aisera): cloud SaaS, all have HITL approval + RBAC + some audit; zero have credential brokers, SoD, egress tagging, or red-team verification. ServiceNow is the only one with an on-prem story.
- **Security/governance startups** (AgentOps, Patronus, Arize, Lakera, Prompt Security, Zenity, Aim, Knostic, Guardrails AI, NeMo): observability or guardrail point-tools that **block, not ask** — no approval gates, no credential vaulting, no SoD; all bolt onto someone else's platform.
- **Self-hosted frameworks** (LangGraph, CrewAI, SuperAGI, AutoGPT, Flowise, Dify, n8n, Activepieces, Windmill): the closest category — Dify (RBAC+SSO+tamper-evident audit), n8n (RBAC+audit+Vault/Infisical secret stores), AutoGPT Platform (org multi-tenancy + managed creds + AuditLog), Windmill (approval steps). But credentials are *stored*, not *brokered per-execution*; approvals are workflow-level, not approver≠initiator triggers.
- **Emerging agent-IAM/audit/red-team layer:** the market is assembling Anton's primitives standalone — Infisical Agent Vault and HashiCorp Vault RAR (per-execution credential brokering), DVARA (HMAC hash-chained audit log), MS Foundry AI Red Teaming Agent / Lakera / HackerOne (adversarial verification *as a service*, not a build property).

**Closest 3 competitors:** Dify, n8n, AutoGPT Platform (Windmill/CrewAI Enterprise as near-misses).

**Clearest gaps (Anton's moat):** single-box full stack; SQLite schema-enforced SoD with boot-time trigger-hash checks; per-execution capability-token broker (SO_PEERCRED, unix socket, revocation reach-through); adversarially-verified build with a convergence gate (CONV-1); tag-based egress gating with confirmation budgets; dual-layer canonical data-layer authZ.

Caveats are flagged in the doc — Cat-4 vendor lists are search-derived leads (several deep fetches failed), and pricing is public-page approximate.