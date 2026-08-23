# Connector Strategy — Native / Nango / Composio (2026-08-23)

## The portfolio

All three paths are live in `connections.py` and pass through identical
governance (broker wrap, egress tags, approval gates, WORM audit). They
are interchangeable per tool per deployment without touching the core.

| Layer | Path | Data locality | Cost | Breadth |
|---|---|---|---|---|
| Flagship financial | **Native QBO** (`qbo_oauth.py`, built+tested) | Tokens never leave box | $0 | 1 |
| Local breadth | **Nango self-hosted** (container via existing bridge) | Tokens stay on box | $0 + ops | ~200 |
| Fast breadth | **Composio cloud** (existing bridge) | Tokens transit third party | per-account | ~250 + actions |

## Decision rule (per tool, per client)

1. **Financial/books data** (QBO, banking, payments):
   LOCAL only \u2014 Nango self-hosted or Native QBO. Cloud forbidden.
2. **Low-sensitivity productivity** (Slack, CRM, calendars):
   Composio by default \u2014 fastest breadth.
3. **Client contract forbids cloud token handling:**
   Nango self-hosted regardless of category.
4. **Single-tool need:** cheapest path that works; revisit if >3 tools
   accumulate (consolidation trigger).

## Switching criteria (when to move a tool BETWEEN layers)

Move a tool from Composio \u2192 local when ANY of:
- Its data classification rises (starts touching PII/financials)
- Annualized Composio cost for that tool exceeds ~4 engineer-hours
  of maintaining it natively/via Nango
- Client contractual requirement arrives

Move a tool local \u2192 Composio never (data locality only relaxes toward
local). Exception: tool proves unmaintainable locally AND data class is
low-sensitivity.

## Consolidation review cadence

Quarterly: count tools per layer, annualized bridge costs, incidents.
If Nango self-hosted covers everything Composio was used for across two
consecutive quarters, retire the Composio bridge for that deployment.

## Vendor app registration (ONE-TIME, TDH Labs as vendor)

- Intuit developer app (for Native QBO production): register under TDH
  Labs \u2014 NOT under any operator/client business. Requires privacy
  policy URL + Intuit's app review before connecting customer
  production books.
- Nango self-hosted: no external registration required.
- Composio: platform account under TDH Labs.

## Known tracked gaps

- Genesis marker design decision (see progress.md OPEN items)
- Webhook secret provisioning surfaced in setup wizard output
