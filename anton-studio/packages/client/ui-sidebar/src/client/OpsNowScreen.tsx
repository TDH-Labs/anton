import type { CSSProperties } from 'react'
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots'
import bp from './blueprint.module.css'
import type { createNavScreenStore } from './nav-store.ts'
import { useOpsApi } from './useOpsApi.ts'

type Tile = { label: string; value: string; color: string; note: string }
/** Matches GET /api/systems -> System[] (README, Data Contracts). */
type System = {
  id: string
  name: string
  sub: string | null
  state: string | null
  lastCheck: string | null
  health: string
  selfManaged: boolean
}
/** Matches GET /api/agent/worklog (README, Data Contracts). `status` is
 * threaded from the backend ledger (ok | fail | skipped); older backends
 * that omit it are treated as ok for backwards compatibility. */
type Worklog = { ongoing: { text: string; meta: string; pct: string | null }[]; done: { text: string; meta: string; status?: 'ok' | 'fail' | 'skipped' }[] }
/** Matches GET /api/approvals (README, Data Contracts) — first two only, for the mini-panel. */
type Approval = { id: number; title: string; sub: string; kind: string }

const LN = '1px solid var(--dsw-alias-border-l2)'
const GENERIC_SYSTEM_ICON = 'M4 22h14a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4'

/** Done-item icon by honest status — success only ever means exit 0. Failures
 * get an error-colored X, skips a warn-colored dash; never a green check. */
function doneIcon(status: 'ok' | 'fail' | 'skipped'): { path: string; color: string } {
  if (status === 'ok') return { path: 'M20 6 9 17l-5-5', color: 'var(--dsw-alias-state-success-primary)' }
  if (status === 'fail') return { path: 'm18 6-12 12M6 6l12 12', color: 'var(--dsw-alias-state-error-primary)' }
  return { path: 'M5 12h14', color: 'var(--dsw-alias-state-warn-label)' }
}

function healthMeta(health: string): { badge: string; color: string } {
  if (health === 'ok') return { badge: 'HEALTHY', color: 'var(--dsw-alias-state-success-primary)' }
  if (health === 'error') return { badge: 'ERROR', color: 'var(--dsw-alias-state-error-primary)' }
  if (health === 'idle') return { badge: 'IDLE', color: 'var(--dsw-alias-label-secondary)' }
  return { badge: health.toUpperCase(), color: 'var(--dsw-alias-label-secondary)' }
}

/** "Right now" — the single pane of glass (README §2), the default screen after Ask Anton. */
export function OpsNowScreen({ actions }: PropsStore<ReturnType<typeof createNavScreenStore>>) {
  const systemsState = useOpsApi<System[]>('/api/systems')
  const worklogState = useOpsApi<Worklog>('/api/agent/worklog')
  const approvalsState = useOpsApi<Approval[]>('/api/approvals')

  const systems = systemsState.data ?? []
  const worklog = worklogState.data ?? { ongoing: [], done: [] }
  const approvals = (approvalsState.data ?? []).slice(0, 2)

  const tiles: Tile[] = [
    { label: 'WORKFLOWS RUNNING', value: String(worklog.ongoing.length), color: 'var(--dsw-alias-label-primary)', note: `${worklog.done.length} finished today` },
    { label: 'SYSTEMS ONLINE', value: String(systems.length), color: 'var(--dsw-alias-state-success-primary)', note: 'Managed components checked continuously' },
    { label: 'WAITING ON YOU', value: String((approvalsState.data ?? []).length), color: 'var(--dsw-alias-state-business-primary)', note: 'Decisions only a person can make' },
    { label: 'TIME SAVED THIS WEEK', value: '—', color: 'var(--dsw-alias-label-primary)', note: 'Versus manual execution' },
  ]

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div style={{ minWidth: 0 }}>
          <div className={bp.kicker}>ANTON · ALWAYS ON</div>
          <div className={bp.screenTitle}>Right now</div>
        </div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '22px 26px 30px', display: 'flex', flexDirection: 'column', gap: 26, minWidth: 800 }}>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 1, background: 'var(--dsw-alias-border-l2)' }}>
            {tiles.map((t, i) => (
              <div key={i} style={{ background: 'var(--dsw-alias-bg-base)', padding: '15px 17px' }}>
                <div className={bp.kicker} style={{ marginBottom: 9 }}>{t.label}</div>
                <div className={bp.screenTitle} style={{ fontSize: 38, lineHeight: 0.9, color: t.color }}>{t.value}</div>
                <div style={{ fontSize: 12, marginTop: 7, color: 'var(--dsw-alias-label-secondary)' }}>{t.note}</div>
              </div>
            ))}
          </div>

          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 11 }}>
              <h4 className={bp.sectionTitle} style={{ fontSize: 20 }}>What Anton is looking after</h4>
              <span style={{ fontSize: 12, color: 'var(--dsw-alias-label-secondary)' }}>{systems.length} systems · checked continuously</span>
            </div>
            <div style={{ borderTop: LN }}>
              {systemsState.loading && <div style={{ padding: '13px 8px', fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
              {systemsState.error && <div style={{ padding: '13px 8px', fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
              {systems.map((s) => {
                const meta = healthMeta(s.health)
                return (
                  <div key={s.id} style={{ display: 'grid', gridTemplateColumns: '26px minmax(0,1.5fr) minmax(0,1.6fr) 92px 118px 20px', alignItems: 'center', gap: 14, padding: '13px 8px', borderBottom: LN }}>
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--dsw-alias-state-business-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d={GENERIC_SYSTEM_ICON} /></svg>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{s.name}</div>
                      {s.sub !== null && <div style={{ fontSize: 11.5, marginTop: 2, color: 'var(--dsw-alias-label-secondary)' }}>{s.sub}</div>}
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-primary)' }}>{s.state ?? ''}</div>
                    <div className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{s.lastCheck !== null ? s.lastCheck.slice(11, 16) : ''}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{ width: 6, height: 6, flex: 'none', background: meta.color }} />
                      <span className={bp.kicker} style={{ margin: 0, color: meta.color }}>{meta.badge}</span>
                    </div>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ color: 'var(--dsw-alias-label-secondary)', opacity: 0.4 }}><path d="m9 18 6-6-6-6" /></svg>
                  </div>
                )
              })}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 1fr', gap: 26 }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 11 }}>
                <h4 className={bp.sectionTitle} style={{ fontSize: 20 }}>Anton's own to-do list</h4>
                <span style={{ fontSize: 12, color: 'var(--dsw-alias-label-secondary)' }}>work it gave itself</span>
              </div>
              <div className={bp.blueprint} style={{ padding: '15px 16px', background: 'var(--dsw-alias-bg-layer-2)' }}>
                <span className={`${bp.corner} ${bp.cornerTl}`} />
                <span className={`${bp.corner} ${bp.cornerTr}`} />
                <span className={`${bp.corner} ${bp.cornerBl}`} />
                <span className={`${bp.corner} ${bp.cornerBr}`} />
                <div className={bp.kicker} style={{ marginBottom: 10 }}>In progress</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 18 }}>
                  {worklog.ongoing.length === 0 && !worklogState.loading && (
                    <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing in progress right now.</div>
                  )}
                  {worklog.ongoing.map((w, i) => {
                    const barStyle: CSSProperties = { width: w.pct ?? '100%', height: '100%', background: 'var(--dsw-alias-state-business-primary)' }
                    return (
                      <div key={i}>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 13.5, color: 'var(--dsw-alias-label-primary)' }}>
                          <span style={{ flex: 1 }}>{w.text}</span>
                          <span className={bp.mono} style={{ flex: 'none', fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{w.meta}</span>
                        </div>
                        {w.pct !== null && (
                          <div style={{ height: 3, marginTop: 6, background: 'var(--dsw-alias-border-l2)' }}>
                            <div style={barStyle} />
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
                <div className={bp.kicker} style={{ color: 'var(--dsw-alias-label-secondary)', marginBottom: 10 }}>Finished today</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {worklog.done.length === 0 && !worklogState.loading && (
                    <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing finished yet today.</div>
                  )}
                  {worklog.done.map((w, i) => {
                    const icon = doneIcon(w.status ?? 'ok')
                    return (
                      <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 9, fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={icon.color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flex: 'none' }}><path d={icon.path} /></svg>
                        <span style={{ flex: 1 }}>{w.text}</span>
                        <span className={bp.mono} style={{ flex: 'none', fontSize: 11 }}>{w.meta}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 11 }}>
                <h4 className={bp.sectionTitle} style={{ fontSize: 20 }}>Waiting on you</h4>
                <span
                  onClick={() => { actions.setScreen('approvals') }}
                  style={{ fontSize: 12, cursor: 'pointer', color: 'var(--dsw-alias-accent-strong)', borderBottom: '1px solid currentColor' }}
                >Open the inbox</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {approvals.length === 0 && !approvalsState.loading && (
                  <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing waiting on you right now.</div>
                )}
                {approvals.map(a => (
                  <div key={a.id} className={bp.blueprint} onClick={() => { actions.setScreen('approvals') }} style={{ padding: '13px 15px', cursor: 'pointer' }}>
                    <span className={`${bp.corner} ${bp.cornerTl}`} />
                    <span className={`${bp.corner} ${bp.cornerTr}`} />
                    <span className={`${bp.corner} ${bp.cornerBl}`} />
                    <span className={`${bp.corner} ${bp.cornerBr}`} />
                    <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 6 }}>
                      <span className={bp.kicker} style={{ margin: 0, padding: '2px 7px', background: 'var(--dsw-alias-state-warn-tertiary)', color: 'var(--dsw-alias-state-warn-label)' }}>{a.kind.toUpperCase()}</span>
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', marginBottom: 2 }}>{a.title}</div>
                    <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>{a.sub}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
