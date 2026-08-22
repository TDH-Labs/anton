# Multi-User Access & Governance — Design Scope

Status: SCOPING (2026-08-22). Grounded in current code (single
`ANTON_DASHBOARD_TOKEN`, one shared `isolation.db`/vault/`secrets.yaml`,
governor gates with risk levels) and in external practice: NIST CC CSRC
agent-identity concept paper (2026), Microsoft Zero Trust least-privilege
for AI agents, AWS SRA for generative-AI agents (session isolation),
Authorization-First Retrieval (TrustNLP 2026), Oracle/AWS secure-RAG ACL
guidance.

## 0. The two threats people conflate

1. **UI leakage** — user A opens something user B owns. Solved by classic
   authN/authZ.
2. **Agent-mediated leakage** — the agent itself carries B's data into A's
   context/output: shared memory retrieval, cached sessions, tool results,
   or prompt injection telling it to fetch-and-forward. UI permissions do
   NOT solve this; the LLM is treated as an untrusted component that must
   be *given* only what the caller is allowed to see.

Anton's architecture is currently maximally vulnerable to #2: everything is
global (one vault, one memory DB, global secrets, one token).

## 1. Identity & AuthN

- Per-user accounts with OIDC SSO (Google Workspace / Entra ID); local
  password accounts as fallback for tiny installs.
- Every dashboard/API request carries a user session; replace the single
  shared `dashboard_token` with per-user tokens (keep a machine token for
  automations, bound to a service identity).
- Four-identity chain on every action (NVIDIA/NIST pattern):
  `user (sponsor) → workspace → agent instance → tool credential`.
  Audit rows record all four.

## 2. Roles (RBAC baseline)

| Role | Can do | Cannot |
|---|---|---|
| Admin | users, connections, budgets, all jobs | approve own raises |
| Approver | approve/reject gate requests within authority | edit jobs |
| Operator | create/run jobs, use connectors | approve, manage users |
| Viewer | read dashboards/results they own or are shared | run anything |

Segregation of duties: maker ≠ checker. The person who builds an
automation cannot be the default approver of its money-movement gates.

## 3. Resource-level authorization (ABAC layer)

Resources carry `owner`, `visibility` (private|team|org), and labels
(entity: beaverton/oregon-city/…; sensitivity: normal|financial|hr).
Enforcement points (server-side only, never UI):

- `/api/*` route guard: user → role → resource ownership/labels.
- Jobs: visible to owner + approvers of their gates + admins.
- Connections: per-user OAuth tokens; admin-configured bridges (Composio/
  Nango) are org-level but *act as* the connecting user downstream.
- Memory/vault: every note/chunk gets owner+visibility at write time.

## 4. Hard gates against the AGENT (the important part)

a. **Per-user executor credentials.** The agent never holds org secrets;
   it receives short-scoped capability tokens via a credential proxy
   (pattern: NVIDIA enterprise tool-access model). Raw `secrets.yaml`
   values stop entering any prompt or process environment wholesale.

b. **Authorization-first retrieval.** Vault/memory retrieval filters by the
   caller's ACLs *before* chunks enter the model context (pipeline-ordering
   rule from TrustNLP'26: semantic search must not precede authorization).
   No "please ignore docs you shouldn't see" prompts — hard WHERE clauses.

c. **Session isolation.** One sandbox/context per job; no cross-session
   cache. Shared state only through ACL-checked stores (AWS SRA guidance).

d. **Egress control / DLP on outputs.** Before any send (email/Slack/
   webhook/channel post), scan output for other users' data patterns and
   classification labels mismatched to the recipient. Block + flag, don't
   just warn.

e. **Tool allowlists per role/job tier.** Existing leash levels map to
   permission modes; add per-tool deny rules (e.g., Viewer-context agents
   get read-only tools).

f. **Prompt-injection containment.** Tool results are untrusted input:
   strip/flag instructions-from-data, require re-approval when a gated
   action originates from tool content rather than the human.

## 5. Governance

- **Audit**: immutable, replayable log of every action with the four-
  identity chain, inputs hash, output recipient. Retention policy knob.
- **Approval ledger**: who approved what, under which policy version.
- **Budgets stay**, but become per-user/per-team with admin ceilings.
- **Framework alignment**: map controls to NIST AI RMF (Map/Measure/
  Manage), ISO/IEC 42001 management clauses, EU AI Act logging/transparency
  for deployers. This is checklist work once §4 exists.
- **Change management**: model/provider changes (the wizard!) are audited
  events; admin approval required below owner level.

## 6. Phased build

1. **Phase 1 (authZ spine)**: users table + sessions, RBAC guards on every
   existing route, audit log. Ship behind single-tenant compat mode.
2. **Phase 2 (isolation)**: ownership columns + visibility on jobs/vault/
   memory; authorization-first retrieval; per-job contexts.
3. **Phase 3 (agent hard-gates)**: credential proxy, egress DLP, tool
   allowlists per role, injection containment.
4. **Phase 4 (governance polish)**: SSO, budget ceilings, framework
   mapping, admin console.

Non-negotiable invariant to enforce in tests at every phase: *"no API path,
retrieval query, or agent tool-call may return data whose ACLs exclude the
acting identity"* — tested with hostile cases (B's job asking about A's
data; injected instructions in tool output requesting cross-user fetch).
