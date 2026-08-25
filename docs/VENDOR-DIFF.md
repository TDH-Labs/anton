# Vendored Harness — Diff Manifest & Upgrade Runbook

`anton-studio/` is a vendored copy of the DeepSeek harness
([deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)),
pinned at tag **`dsh-v0.1.0-rc.8`** (commit `141eb6fe`), with Anton-specific
product work layered on top. This file is the single source of truth for
what we changed, why, and how to absorb an upstream upgrade.

**House rule going forward:** new capability is a *slot registration*, a
*settings-namespace entry*, an *agent preset*, or an *MCP connector* first.
Editing a vendored harness file is the last resort and MUST be reflected
here. Run `scripts/vendor-diff.sh` before any upgrade; every file it lists
must have an entry below or be reverted.

## Pinned base

| | |
|---|---|
| Upstream | https://github.com/deepseek-ai/deepseek-harness |
| Base tag | `dsh-v0.1.0-rc.8` (`141eb6fe`) |
| Snapshot commit | `058d01a` ("vendor anton-studio UI source") |

## Our changes (by category)

### A. First-party product UI — lives in the vendored tree today; migrate to `packages/client/ui-anton-ops` (own package, slot registrations only)
| File | What we changed | Migration note |
|---|---|---|
| `ui-sidebar/src/client/OpsCockpit.tsx` | ops shell + setup modal card + session routing | move whole Ops Center into own package registering `shell.overlay` |
| `ui-sidebar/src/client/OpsNowScreen.tsx` | Right Now screen (clicks, status styling) | same |
| `ui-sidebar/src/client/screens/*.tsx` | Setup wizard, Add-ons, Approvals, Automations, Schedule, Memory, Learning, Alerts, ConnectionsCatalog | same; `automationDraft.ts` moves with it |
| `ui-sidebar/src/client/SidebarRoot.tsx` | live waiting-on-you badge | badge belongs in the ops package via a `sidebar.*` slot seat, not an edit |

### B. Host glue for the Anton backend — migrate to a cordis profile patch / dedicated plugin
| File | What we changed | Migration note |
|---|---|---|
| `host/apiproxy/src/index.ts` | registers `/api/*` reverse-proxy prefixes + Anton LLM adapter/provider | route table → profile patch; adapter → own plugin |
| `host/apiproxy/src/anton-auth.ts` | scoped machine credential (keep — new file, ours by construction) | move with the plugin |
| `host/apiproxy/src/anton-bridge.ts` | Anton FastAPI LLM adapter (keep — ours) | move with the plugin |
| `host/apiproxy/src/fetch/client.ts` | forward-header handling | upstream PR candidate if generic |

### C. Genuine upstream bug fixes — PR upstream, carry locally until merged
| File | Fix | Upstream PR? |
|---|---|---|
| `ui-conversation/src/client/service.ts` | chat transport fix | yes |
| `packages/llm/llm/src/message.ts` | adversarial-audit fix (`35283ec`) | yes |
| `packages/interaction/commands/src/index.ts` | adversarial-audit fix | yes |
| `ui-sidebar/*` `minHeight: 0` flex fix | dead-scrolling bug in bounded overlay columns | yes — generic |
| `docker/auth-gate.mjs` (in `anton-studio` sibling `docker/`) | trust-fence Host/Origin rewrite | yes — security |

### D. Tests riding with vendored packages — fine to keep; move with category A
`ui-sidebar/tests/*` (bridges card, addons load-error, right-now fixes, worklog status, setup wizard), `ui-settings-general/tests/*`, `apiproxy/tests/anton-proxy-auth.spec.ts`.

### E. Config-not-code wins already shipped
Chat provider/model selection rides the harness's **own** settings document
(`$DSH_HOME/settings.yaml` → `llm-pi-ai:` + `agent-default-model:`, written by
`anton/dsh_bridge.py`) — zero harness code. Keep it that way: new provider
support is a settings entry, never a patch.

## Upgrade runbook

```bash
# 1. See exactly what we carry:
scripts/vendor-diff.sh            # diffs anton-studio/ against the pinned tag

# 2. Absorb an upstream release:
#    - bump PINNED_TAG in this file and in scripts/vendor-diff.sh
#    - resolve conflicts file-by-file using the category table above
#      (A/B move with us; C re-apply on the new base; D re-run)
# 3. Test battery (all must be green before shipping):
#      .venv/bin/python -m pytest tests/ -q
#      cd anton-studio && npx tsc -b tsconfig.client.json
#      npx vitest run packages/client/ui-sidebar/tests packages/host/apiproxy/tests
# 4. CI green → digest-pinned store bump (community store repo).
```
