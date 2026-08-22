# Anton vs Popular GUI Harnesses — Feature-Vetting Gap List

Compared against **OpenHands** (Agent Canvas GUI + SDK) and **Goose Desktop**
(Block), with Open WebUI/LibreChat as provider-UX reference. Sources: official
docs, DeepWiki architecture pages, release notes (2026-08). Not copying their
design — checking we're not missing table-stakes.

## Where Anton already matches or leads
- Provider catalog + custom OpenAI-compatible endpoints (now parity with
  OpenHands' custom model/base URL flow; better than pre-wizard).
- Approvals/governor gates: Anton's risk-tiered leash is AHEAD of both
  (Goose permission modes are coarser; OpenHands confirmation mode is binary).
- Schedules (cron+webhook) ≈ Goose schedules/OpenHands automations.
- Memory (vault+second brain), metering/budgets, canary tripwires: rare in
  both comparators.

## Gaps (ranked)

1. **Conversation/session UX** (both): OpenHands = tabbed conversations with
   files/terminal/browser panes per session; Goose = parallel live sessions
   grouped by project. Anton's Ops Center lacks a first-class multi-session
   chat surface with per-session file/terminal views.
2. **Git integration** (OpenHands): git control bar, PR-open from
   conversation, workspace file tree. Anton has none — needed for dev jobs.
3. **Per-message usage/cost UI** (Goose v1.43): tokens/cost/TTFT inline.
   Anton meters server-side but doesn't surface per-run cost in the UI.
4. **Secrets/credentials management UI**: Goose/OpenHands store keys via
   settings with masked display. Anton has secrets.yaml but no settings
   surface (partially addressed by wizard keys work).
5. **SSO / multi-user** (OpenHands Enterprise): see MULTIUSER-GOVERNANCE.md.
6. **Mobile/cloud access** (OpenHands Cloud): nice-to-have; Umbrel+Tailscale
   partially covers it.
7. **File-based custom agents/sub-agents** (OpenHands SDK microagents,
   Goose subagents): declare specialized agents as markdown. Anton has
   personas/rooms but not user-authorable in-product.
8. **Integrations directory breadth**: now solved by connections system
   (#6/#7); keep registry sync fresh.

## Recommended next builds (order)
1. Session surface with live job logs/files (closes #1, biggest daily-use gap)
2. Per-run cost badge using existing metering data (cheap, high visibility)
3. Git toolchain for code jobs (only if dev use-case matters to owners)
