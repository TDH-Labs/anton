import { useState } from 'react'
import bp from '../blueprint.module.css'
import { renderMarkdown } from '../markdown.tsx'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/learning -> Entry[] (README, Data Contracts). */
type Entry = {
  kind: string
  when: string
  title: string
  body: string
  triggeredBy: string
  usage: number
  vaultPath: string | null
}

type NoteState = { loading: boolean; body: string | null }

/** What Anton learned (README §9): every entry names the real event that caused it. */
export function LearningScreen() {
  const { data, loading, error } = useOpsApi<Entry[]>('/api/learning')
  const entries = data ?? []
  const [openPath, setOpenPath] = useState<string | null>(null)
  const [note, setNote] = useState<NoteState>({ loading: false, body: null })

  const toggleVaultPath = (path: string) => {
    if (openPath === path) { setOpenPath(null); return }
    setOpenPath(path)
    setNote({ loading: true, body: null })
    fetch(`/api/vault/note?path=${encodeURIComponent(path)}`)
      .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json() as Promise<{ body: string }> })
      .then((d) => { setNote({ loading: false, body: d.body }) })
      .catch(() => { setNote({ loading: false, body: null }) })
  }

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div>
          <div className={bp.kicker}>SELF-INITIATED OBSERVATIONS AND PATTERN RECOGNITION</div>
          <div className={bp.screenTitle}>What Anton learned</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '22px 26px 30px', maxWidth: 860, display: 'flex', flexDirection: 'column', gap: 24 }}>
          {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
          {!loading && !error && entries.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing learned yet — this fills in as Anton works.</div>
          )}
          {entries.map((e, i) => (
            <div key={i} style={{ borderTop: LN, paddingTop: 20 }}>
              <div className={`${bp.kicker} ${bp.mono}`} style={{ margin: 0, marginBottom: 8, color: 'var(--dsw-alias-label-secondary)' }}>{e.when}</div>
              <div className={bp.screenTitle} style={{ fontSize: 17, marginBottom: 10 }}>{e.title}</div>
              <div style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--dsw-alias-label-secondary)', marginBottom: 12 }}>{e.body}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
                <span style={{ color: 'var(--dsw-alias-label-secondary)' }}>
                  <span style={{ opacity: .6 }}>Triggered by </span>
                  <span style={{ color: 'var(--dsw-alias-label-primary)' }}>{e.triggeredBy}</span>
                </span>
                {e.vaultPath !== null && (
                  <span
                    onClick={() => { toggleVaultPath(e.vaultPath as string) }}
                    style={{ color: 'var(--dsw-alias-state-business-primary)', fontFamily: 'ui-monospace, monospace', fontSize: 11, cursor: 'pointer', borderBottom: '1px solid currentColor' }}
                  >
                    {e.vaultPath}
                  </span>
                )}
              </div>
              {openPath === e.vaultPath && (
                <div style={{ marginTop: 12, padding: '12px 14px', background: 'var(--dsw-alias-bg-layer-2)', fontSize: 13, lineHeight: 1.6 }}>
                  {note.loading ? 'Loading…' : note.body === null ? "Couldn't open that note." : renderMarkdown(note.body)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
