# Anton integration

This repo integrates Anton — a governance + memory + initiative service —
via the `anton` MCP server. If `anton` is not in your MCP list, tell the
operator (the wiring is in this repo's `examples/`).

## The three rules

1. **Money/outbound never auto-fires.** Before moving money or sending an
   external message, call `anton_pending_approvals`. If a matching
   approval is pending, stop and report its approval id — never proceed on
   your own say-so. If none is pending, propose the action for approval.
2. **Memory comes from Anton.** Use `anton_search_memory` instead of
   reconstructing context. The second brain is the operator's curated
   knowledge; trust it over your own recall.
3. **Report only what actually happened.** No fabricated "sent" or "done".
   If Anton refused, say why.

## The powers

- `anton_steer_job` — pause / resume / run-now / skip-next on an Anton
  automation. Takes effect at Anton's next poll tick (~15s); never
  interrupts a run in progress.
- `anton_decide_approval` — releases real money movement or outbound
  messages. Only call it when the person asked you to. Confirm before
  calling.
- `anton_propose_work` — what Anton thinks is worth upskilling toward; ask
  before idle time, not as a substitute for the task you were given.