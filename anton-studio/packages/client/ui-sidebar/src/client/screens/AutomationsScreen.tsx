import { useRef, useState } from 'react'
import bp from '../blueprint.module.css'
import { NodeEditorScreen, type EditorLink, type EditorNode } from './NodeEditorScreen.tsx'
import { draftToNodes, slugify, type AutomationDraft } from './automationDraft.ts'
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

// All three ways are real today: "Describe it" and "Upload a doc" POST
// /api/automations/draft (the configured model drafts a JSON workflow that is
// strictly validated server-side), "Draw it" opens the visual node editor
// below. A returned draft is only ever a reviewable card -- saving it goes
// through PUT /api/automations/:id as awaiting_approval, never running.
type MakeWay = { icon: string; title: string; desc: string }
const MAKE_WAYS: MakeWay[] = [
  { icon: 'M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z', title: 'Describe it', desc: 'Say it in plain English — Anton drafts the workflow' },
  { icon: 'M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z', title: 'Draw it', desc: 'Build nodes and connections on a visual canvas' },
  { icon: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6', title: 'Upload a doc', desc: 'Drop in a procedure doc (.txt/.md) — Anton maps it to steps' },
]

// DraftTrigger/AutomationDraft/slugify/draftToNodes moved to automationDraft.ts —
// shared verbatim with SetupScreen's "Describe it" box (diagnose:setup-automations).
let nextNewId = 1

/** Automations (README §3): live automation list, plus the node editor (§4) opened from a row, a card, or the "Draw it" cell. */
export function AutomationsScreen() {
  const { data, loading, error, refetch } = useOpsApi<Automation[]>('/api/initiatives')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingName, setEditingName] = useState<string>('')

  const [describeOpen, setDescribeOpen] = useState(false)
  const [description, setDescription] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [draft, setDraft] = useState<AutomationDraft | null>(null)
  const [savingDraft, setSavingDraft] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)

  const automations = data ?? []

  const requestDraft = (desc: string, sourceText?: string, sourceName?: string) => {
    if (!desc.trim()) return
    setDrafting(true)
    setDraftError(null)
    fetch('/api/automations/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: desc, source_text: sourceText ?? undefined, source_name: sourceName ?? undefined }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `${r.status}`)
        return r.json() as Promise<AutomationDraft>
      })
      .then((d) => { setDraft(d); setDescribeOpen(false) })
      .catch((e) => { setDraftError(e instanceof Error && e.message !== '[object Object]' ? `Anton couldn't finish the draft (${e.message}).` : "Anton couldn't reach the drafting model.") })
      .finally(() => setDrafting(false))
  }

  // Read entirely client-side (no upload endpoint exists or is needed):
  // .txt/.md text goes into the same draft request body as any description.
  const onDocPicked = async (f: File | null | undefined) => {
    if (!f) return
    if (!/\.(txt|md)$/i.test(f.name)) { setDraftError('Only .txt and .md files are supported.'); return }
    try {
      const text = await f.text()
      requestDraft(
        `Map this uploaded procedure document into an automation. Keep every ordered action it describes; add human sign-off steps where the document requires approval.`,
        text, f.name,
      )
    } catch {
      setDraftError('Could not read that file.')
    }
  }

  const confirmDraft = () => {
    if (draft === null) return
    const id = slugify(draft.name)
    const { nodes, links } = draftToNodes(draft)
    setSavingDraft(true)
    // Same persistence path as the wizard/editor approve flow — state stays
    // awaiting_approval; activation is a separate, explicit later act.
    fetch(`/api/automations/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: draft.name, plain: draft.plain, nodes, links, state: 'awaiting_approval' }),
    })
      .then(() => { setDraft(null); refetch() })
      .finally(() => setSavingDraft(false))
  }

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
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
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
                onClick={() => {
                  if (w.title === 'Describe it') { setDescribeOpen(o => !o); setDraftError(null) }
                  else if (w.title === 'Upload a doc') { fileRef.current?.click(); setDraftError(null) }
                  else { const id = `draft-${nextNewId++}`; setEditingName('New automation'); setEditingId(id) }
                }}
                style={{ flex: 1, background: 'var(--dsw-alias-bg-base)', padding: '16px 18px', cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 7 }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--dsw-alias-state-business-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={w.icon} /></svg>
                  <span style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{w.title}</span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', lineHeight: 1.4 }}>{w.desc}</div>
              </div>
            ))}
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            style={{ display: 'none' }}
            onChange={(e) => { void onDocPicked(e.target.files?.[0]); e.currentTarget.value = '' }}
          />

          {/* Describe-it panel: plain English -> POST /api/automations/draft */}
          {describeOpen && (
            <div style={{ border: LN, padding: 16, marginBottom: 24 }}>
              <div className={bp.kicker} style={{ margin: 0 }}>DESCRIBE IT</div>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="e.g. Every weekday at 7 AM, pull yesterday's sales totals from the accounting file and email me anything over budget."
                rows={3}
                style={{ width: '100%', marginTop: 10, marginBottom: 10, border: LN, background: 'transparent', color: 'var(--dsw-alias-label-primary)', fontFamily: 'inherit', fontSize: 13, padding: 10, resize: 'vertical', boxSizing: 'border-box' }}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <button
                  onClick={() => requestDraft(description)}
                  disabled={drafting || !description.trim()}
                  style={{ background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 12.5, padding: '7px 16px', cursor: drafting || !description.trim() ? 'default' : 'pointer', opacity: drafting || !description.trim() ? 0.55 : 1, fontFamily: 'inherit' }}
                >{drafting ? 'Drafting…' : 'Draft it'}</button>
                <span style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>You review the draft before anything is saved.</span>
              </div>
            </div>
          )}

          {drafting && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginBottom: 24 }}>Anton is drafting…</div>}
          {draftError && <div style={{ fontSize: 13, color: 'var(--dsw-alias-state-error-primary)', marginBottom: 24 }}>{draftError}</div>}

          {/* Reviewable draft card: nothing is saved until you confirm, and
              confirming files it as awaiting_approval — never running. */}
          {draft !== null && !drafting && (
            <div style={{ border: LN, padding: 16, marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <span className={bp.kicker} style={{ margin: 0, color: 'var(--dsw-alias-state-warn-label)' }}>DRAFT — PENDING YOUR REVIEW</span>
                <span style={{ flex: 1 }} />
                <button onClick={() => setDraft(null)} style={{ background: 'none', border: LN, color: 'var(--dsw-alias-label-primary)', fontSize: 12, padding: '4px 10px', cursor: 'pointer', fontFamily: 'inherit' }}>Discard</button>
                <button onClick={confirmDraft} disabled={savingDraft} style={{ background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 12, padding: '4px 10px', cursor: savingDraft ? 'default' : 'pointer', opacity: savingDraft ? 0.55 : 1, fontFamily: 'inherit' }}>{savingDraft ? 'Saving…' : 'Save for review'}</button>
              </div>
              <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{draft.name}</div>
              <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>{draft.plain}</div>
              <div className={bp.mono} style={{ fontSize: 12, color: 'var(--dsw-alias-label-secondary)', margin: '8px 0' }}>Runs: {draft.trigger?.display ?? '—'}</div>
              <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: 'var(--dsw-alias-label-primary)', lineHeight: 1.6 }}>
                {draft.steps.map((s, i) => (
                  <li key={i}>{s.text}{s.assignee === 'human' && <span style={{ color: 'var(--dsw-alias-state-warn-label)' }}> · needs your OK</span>}</li>
                ))}
              </ol>
            </div>
          )}

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
