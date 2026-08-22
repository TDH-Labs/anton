import { useState } from 'react'
import bp from '../blueprint.module.css'
import { NodeEditorScreen, type EditorLink, type EditorNode } from './NodeEditorScreen.tsx'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/**
 * Matches GET /api/initiatives -> Automation[] (README, Data Contracts).
 * `trigger` is typed optional, not just its fields: it's a fetch()-boundary
 * value, and a backend still running the pre-reshape route (see NodeEditor's
 * approve-flow write path) would omit it entirely rather than send nulls.
 */
type Automation = {
  id: string
  name: string
  plain: string
  trigger?: { kind: 'cron' | 'event' | 'interval' | null; display: string | null; expr: string | null }
  needsSignoff: boolean
  author: 'human' | 'agent'
  lastRun: string | null
  state: 'running' | 'awaiting_approval' | 'blocked' | 'failed' | 'off'
  risk: 'low' | 'medium' | 'high'
  nodes: EditorNode[]
  links: EditorLink[]
}

const STATE_COLORS: Record<Automation['state'], string> = {
  running: 'var(--dsw-alias-state-success-primary)',
  awaiting_approval: 'var(--dsw-alias-state-warn-label)',
  off: 'var(--dsw-alias-label-secondary)',
  blocked: 'var(--dsw-alias-state-warn-label)',
  failed: 'var(--dsw-alias-state-error-primary)',
}

// "Draw it" is real today (opens the visual node editor below). The other
// two need real backend capability that doesn't exist yet -- text-to-
// automation drafting, document parsing -- so they're marked not-yet-
// available (soon: true) rather than silently doing nothing when clicked,
// or being aliased to "Draw it" (a blank canvas isn't what someone asking
// to "describe it in plain English" actually wants).
const MAKE_WAYS: { icon: string; title: string; desc: string; soon?: boolean }[] = [
  { icon: 'M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z', title: 'Describe it', desc: 'Say it in plain English — Anton drafts the workflow', soon: true },
  { icon: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z', title: 'Draw it', desc: 'Build nodes and connections on a visual canvas' },
  { icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6', title: 'Upload a doc', desc: 'Drop in a procedure doc — Anton maps it to steps', soon: true },
]

let nextNewId = 1

/** Automations (README §3): live automation list, plus the node editor (§4) opened from a row, a card, or the "Draw it" cell. */
export function AutomationsScreen() {
  const { data, loading, error, refetch } = useOpsApi<Automation[]>('/api/initiatives')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState<string>('')

  const automations = data ?? []

  if (editingId !== null) {
    const editing = automations.find(a => a.id === editingId)
    return (
      <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', overflowY: 'auto', padding: '22px 26px 30px', background: 'var(--dsw-alias-bg-base)' }}>
        <NodeEditorScreen
          automationId={editingId}
          automationName={editing?.name ?? editingName}
          initialNodes={editing?.nodes ?? []}
          initialLinks={editing?.links ?? []}
          onDone={() => { setEditingId(null); refetch() }}
        />
      </div>
    )
  }

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div style={{ minWidth: 0 }}>
          <div className={bp.kicker}>{automations.length} DRAFTED · {automations.filter(a => a.author === 'human').length} BUILT BY YOU</div>
          <div className={bp.screenTitle}>Automations</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '22px 26px 30px', minWidth: 900 }}>
          {/* Ways to create */}
          <div style={{ display: 'flex', gap: 1, background: 'var(--dsw-alias-border-l2)', marginBottom: 24 }}>
            {MAKE_WAYS.map((w, i) => (
              <div
                key={i}
                onClick={w.title === 'Draw it' ? () => { const id = `draft-${nextNewId++}`; setEditingName('New automation'); setEditingId(id) } : undefined}
                style={{ flex: 1, background: 'var(--dsw-alias-bg-base)', padding: '16px 18px', cursor: w.soon === true ? 'default' : 'pointer', opacity: w.soon === true ? 0.55 : 1 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 7 }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--dsw-alias-state-business-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={w.icon} /></svg>
                  <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{w.title}</span>
                  {w.soon === true && <span className={bp.kicker} style={{ margin: 0, color: 'var(--dsw-alias-label-secondary)' }}>SOON</span>}
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', lineHeight: 1.4 }}>{w.desc}</div>
              </div>
            ))}
          </div>

          {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
          {!loading && !error && automations.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing drafted yet — describe or draw one above.</div>
          )}

          {/* Table: Automation | When it runs | Sign-off | Built by | Last run | State (README §3) */}
          {automations.length > 0 && (
            <div style={{ borderTop: LN }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2.2fr) minmax(0,1.1fr) 90px 110px 90px 110px 24px', gap: 14, padding: '8px 8px', borderBottom: LN }}>
                {['Automation', 'When it runs', 'Sign-off', 'Built by', 'Last run', 'State', ''].map((h, i) => (
                  <div key={i} className={bp.kicker} style={{ margin: 0 }}>{h}</div>
                ))}
              </div>
              {automations.map(a => (
                <div
                  key={a.id}
                  onClick={() => { setEditingName(a.name); setEditingId(a.id) }}
                  style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2.2fr) minmax(0,1.1fr) 90px 110px 90px 110px 24px', alignItems: 'center', gap: 14, padding: '13px 8px', borderBottom: LN, cursor: 'pointer' }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '44ch' }}>{a.name}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>{a.plain}</div>
                  </div>
                  <div className={bp.mono} style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{a.trigger?.display ?? '—'}</div>
                  <div style={{ fontSize: 11.5, color: a.needsSignoff ? 'var(--dsw-alias-state-warn-label)' : 'var(--dsw-alias-label-secondary)' }}>{a.needsSignoff ? 'Yes' : 'No'}</div>
                  <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>{a.author === 'agent' ? 'Anton ✦' : 'You'}</div>
                  <div className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{a.lastRun ?? '—'}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                    <span style={{ width: 6, height: 6, flex: 'none', background: STATE_COLORS[a.state] }} />
                    <span className={bp.kicker} style={{ margin: 0, fontSize: 10, letterSpacing: '.12em', color: STATE_COLORS[a.state] }}>{a.state.replace('_', ' ')}</span>
                  </div>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--dsw-alias-label-secondary)', opacity: 0.4 }}><path d="m9 18 6-6-6-6" /></svg>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
