import { useEffect, useState } from 'react'
import bp from '../blueprint.module.css'
import { renderMarkdown } from '../markdown.tsx'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/vault/graph's real node shape (dashboard.py) -- moc/
 * skill/note, not a fabricated business taxonomy (Decisions/Contacts/
 * Systems/...). Anton's vault doesn't currently classify notes any more
 * finely than this. */
type GraphNode = { id: string; title: string; type: 'moc' | 'skill' | 'note'; val: number }
type GraphLink = { source: string; target: string }
type Graph = { nodes: GraphNode[]; links: GraphLink[] }

/** Matches GET /api/vault/note's real contract (dashboard.py, "Ops Center
 * contract fields"). */
type NoteDetail = {
  title: string; kind: string; author: string; body: string
  provenance: string | null; usedCount: number; linkCount: number
}

const TYPE_COLOR: Record<GraphNode['type'], string> = {
  moc: 'var(--dsw-alias-state-business-primary)',
  skill: 'var(--dsw-alias-state-warn-label)',
  note: 'var(--dsw-alias-label-secondary)',
}

const TYPE_LABEL: Record<GraphNode['type'], string> = { moc: 'Map', skill: 'Skill', note: 'Note' }

type View = 'list' | '3d'

/** Memory: everything Anton actually has in its second brain, and where it
 * came from. The flat view is a real list driven by /api/vault/graph, not a
 * hand-placed node scatter -- Anton doesn't compute a 2D force layout for
 * this, and inventing fake node positions (or fake node content) to make a
 * richer-looking graph isn't worth it. The 3D view already does real
 * graph layout via /graph.html. */
export function MemoryScreen() {
  const { data, loading, error } = useOpsApi<Graph>('/api/vault/graph')
  const [activeType, setActiveType] = useState<'All' | GraphNode['type']>('All')
  const [view, setView] = useState<View>('list')
  const [activeId, setActiveId] = useState<string | null>(null)
  const [sonMode, setSonMode] = useState(false)
  const [detail, setDetail] = useState<NoteDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const nodes = data?.nodes ?? []

  useEffect(() => {
    setSonMode(document.body.getAttribute('data-anton-mode') === 'son')
    const handle = () => { setSonMode(document.body.getAttribute('data-anton-mode') === 'son') }
    window.addEventListener('son-of-anton-toggle', handle)
    return () => { window.removeEventListener('son-of-anton-toggle', handle) }
  }, [])

  useEffect(() => {
    if (view !== '3d') return
    const onMessage = (e: MessageEvent<unknown>) => {
      const d = e.data
      if (typeof d !== 'object' || d === null) return
      const { type, id } = d as { type?: unknown; id?: unknown }
      if (type !== 'open-node' || typeof id !== 'string') return
      setActiveId(id)
    }
    window.addEventListener('message', onMessage)
    return () => { window.removeEventListener('message', onMessage) }
  }, [view])

  useEffect(() => {
    if (activeId === null) { setDetail(null); return }
    let cancelled = false
    setDetailLoading(true)
    fetch(`/api/vault/note?path=${encodeURIComponent(activeId)}`)
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() as Promise<NoteDetail> })
      .then((d) => { if (!cancelled) setDetail(d) })
      .catch(() => { if (!cancelled) setDetail(null) })
      .finally(() => { if (!cancelled) setDetailLoading(false) })
    return () => { cancelled = true }
  }, [activeId])

  const visibleNodes = activeType === 'All' ? nodes : nodes.filter(n => n.type === activeType)
  const counts = (['All', 'moc', 'skill', 'note'] as const).map(t => ({
    t, count: t === 'All' ? nodes.length : nodes.filter(n => n.type === t).length,
  }))

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div style={{ minWidth: 0 }}>
          <div className={bp.kicker}>EVERYTHING ANTON KNOWS AND WHERE IT CAME FROM</div>
          <div className={bp.screenTitle}>Memory</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, display: 'flex', minWidth: 1050 }}>
        <div style={{ flex: 'none', width: 212, padding: '20px 18px', borderRight: LN, overflowY: 'auto' }}>
          <div className={bp.kicker} style={{ color: 'var(--dsw-alias-label-secondary)' }}>Show me</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {counts.map(({ t, count }) => (
              <div
                key={t}
                onClick={() => { setActiveType(t) }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '7px 9px', fontSize: 13.5, cursor: 'pointer',
                  background: activeType === t ? 'var(--dsw-alias-state-business-tertiary)' : 'transparent',
                  color: activeType === t ? 'var(--dsw-alias-accent-strong)' : 'var(--dsw-alias-label-primary)',
                  boxShadow: activeType === t ? 'inset 2px 0 0 var(--dsw-alias-state-business-primary)' : 'none',
                }}
              >
                <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {t === 'All' ? 'All' : TYPE_LABEL[t]}
                </span>
                <span className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{count}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', position: 'relative' }}>
          <div style={{ position: 'absolute', top: 12, right: 14, zIndex: 1, display: 'flex' }}>
            {(['list', '3d'] as View[]).map(v => (
              <div
                key={v}
                onClick={() => { setView(v) }}
                style={{
                  padding: '5px 11px', fontSize: 11.5, cursor: 'pointer', border: LN,
                  background: view === v ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-bg-base)',
                  color: view === v ? 'var(--dsw-alias-bg-base)' : 'var(--dsw-alias-label-primary)',
                }}
              >
                {v === 'list' ? 'List' : '3D vault'}
              </div>
            ))}
          </div>

          {view === 'list' ? (
            <div style={{ flex: 1, overflowY: 'auto', padding: '48px 18px 18px' }}>
              {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
              {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
              {!loading && !error && visibleNodes.length === 0 && (
                <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>
                  Nothing here yet — this fills in as Anton reads and writes notes.
                </div>
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {visibleNodes.map((n) => {
                  const active = n.id === activeId
                  return (
                    <div
                      key={n.id}
                      onClick={() => { setActiveId(n.id) }}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', cursor: 'pointer',
                        background: active ? 'var(--dsw-alias-state-business-tertiary)' : 'var(--dsw-alias-bg-layer-2)',
                      }}
                    >
                      <span style={{ width: 8, height: 8, borderRadius: '50%', flex: 'none', background: TYPE_COLOR[n.type] }} />
                      <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{n.title}</span>
                      <span className={bp.kicker} style={{ margin: 0, color: 'var(--dsw-alias-label-secondary)' }}>{TYPE_LABEL[n.type]}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : (
            <iframe
              key={sonMode ? 'son' : 'standard'}
              title="3D memory vault"
              src={`/graph.html?mode=${sonMode ? 'son' : 'standard'}`}
              style={{ flex: 1, width: '100%', border: 'none' }}
            />
          )}
        </div>

        <div style={{ flex: 'none', width: 326, borderLeft: LN, padding: '20px 22px', overflowY: 'auto' }}>
          {activeId === null ? (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Pick something on the left to see it here.</div>
          ) : detailLoading ? (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>
          ) : detail === null ? (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't open that note.</div>
          ) : (
            <>
              <div className={bp.kicker} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {detail.kind.toUpperCase()}
                <span style={{ color: 'var(--dsw-alias-label-secondary)', letterSpacing: 0, textTransform: 'none' }}>· {detail.author === 'agent' ? 'Anton wrote this' : 'You wrote this'}</span>
              </div>
              <div className={bp.screenTitle} style={{ fontSize: 21, margin: '6px 0 12px' }}>{detail.title}</div>
              <div style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--dsw-alias-label-primary)' }}>
                {renderMarkdown(detail.body)}
              </div>
              {detail.provenance !== null && (
                <div style={{ marginTop: 16, paddingTop: 14, borderTop: LN }}>
                  <div className={bp.kicker} style={{ color: 'var(--dsw-alias-label-secondary)' }}>Where it came from</div>
                  <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)' }}>{detail.provenance}</div>
                </div>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                <span className={bp.mono} style={{ fontSize: 11, padding: '3px 8px', border: LN, color: 'var(--dsw-alias-label-secondary)' }}>USED {detail.usedCount}×</span>
                <span className={bp.mono} style={{ fontSize: 11, padding: '3px 8px', border: LN, color: 'var(--dsw-alias-label-secondary)' }}>LINKS {detail.linkCount}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
