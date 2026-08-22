import bp from '../blueprint.module.css'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/incidents -> Incident[] (README, Data Contracts). */
type Incident = {
  id: string
  title: string
  summary: string
  status: string
  window: string
  events: { time: string; text: string; actor: string }[]
}

const ACTOR_COLOR: Record<string, string> = {
  agent: 'var(--dsw-alias-state-business-primary)',
  system: 'var(--dsw-alias-label-secondary)',
  human: 'var(--dsw-alias-state-success-primary)',
}

function statusColor(status: string): string {
  if (status === 'resolved') return 'var(--dsw-alias-state-success-primary)'
  if (status === 'open') return 'var(--dsw-alias-state-warn-label)'
  return 'var(--dsw-alias-label-secondary)'
}

/** What went wrong (README §10): Anton caught it, worked out why, wrote it up, drafted a fix, stopped at the gate. */
export function AlertsScreen() {
  const { data, loading, error } = useOpsApi<Incident[]>('/api/incidents')
  const incidents = data ?? []

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div>
          <div className={bp.kicker}>EVERY INCIDENT, AND WHAT ANTON DID ABOUT IT</div>
          <div className={bp.screenTitle}>What went wrong</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '22px 26px 34px', maxWidth: 900, display: 'flex', flexDirection: 'column', gap: 24 }}>
          {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
          {!loading && !error && incidents.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing has gone wrong — nothing to show here yet.</div>
          )}
          {incidents.map((inc) => {
            const color = statusColor(inc.status)
            return (
              <div key={inc.id} className={bp.blueprint} style={{ background: 'var(--dsw-alias-bg-layer-2)', borderTop: `2px solid ${color}` }}>
                <span className={`${bp.corner} ${bp.cornerTl}`} />
                <span className={`${bp.corner} ${bp.cornerTr}`} />
                <span className={`${bp.corner} ${bp.cornerBl}`} />
                <span className={`${bp.corner} ${bp.cornerBr}`} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: LN }}>
                  <span className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{inc.id}</span>
                  <span className={bp.kicker} style={{ margin: 0, padding: '2px 7px', background: 'var(--dsw-alias-bg-base)', color }}>{inc.status.toUpperCase()}</span>
                  <span style={{ flex: 1 }} />
                  <span className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{inc.window}</span>
                </div>
                <div style={{ padding: '16px 18px' }}>
                  <div className={bp.screenTitle} style={{ fontSize: 17, marginBottom: 6 }}>{inc.title}</div>
                  <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginBottom: 16 }}>{inc.summary}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                    {inc.events.map((ev, j) => (
                      <div key={j} style={{ display: 'flex', gap: 12, padding: '7px 0', borderBottom: j < inc.events.length - 1 ? LN : 'none' }}>
                        <span className={bp.mono} style={{ flex: 'none', width: 42, fontSize: 11, color: 'var(--dsw-alias-label-secondary)', paddingTop: 1 }}>{ev.time}</span>
                        <span style={{ flex: 'none', width: 6, height: 6, background: ACTOR_COLOR[ev.actor] ?? 'var(--dsw-alias-label-secondary)', marginTop: 5, flexShrink: 0 }} />
                        <span style={{ fontSize: 13, color: 'var(--dsw-alias-label-primary)', flex: 1 }}>{ev.text}</span>
                        <span style={{ fontSize: 10, letterSpacing: '.12em', textTransform: 'uppercase', color: ACTOR_COLOR[ev.actor] ?? 'var(--dsw-alias-label-secondary)', flexShrink: 0 }}>{ev.actor}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
