import bp from '../blueprint.module.css'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/jobs -> Job[] (README, Data Contracts). */
type Job = {
  id: string
  automationId: string
  trigger: { type?: string; expr?: string; path?: string }
  nextRun: string | null
  lastRun: string | null
  cadenceMin: number | null
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
// getUTCDay(): 0=Sun..6=Sat -> DAYS index (Mon-first).
const DAY_INDEX = [6, 0, 1, 2, 3, 4, 5]

function cadenceLabel(mins: number | null): string {
  if (mins === null) return 'on event'
  if (mins >= 10080 && mins % 10080 === 0) return mins === 10080 ? 'weekly' : `every ${mins / 10080}w`
  if (mins >= 1440 && mins % 1440 === 0) return mins === 1440 ? 'daily' : `every ${mins / 1440}d`
  return `every ${mins}m`
}

/** Schedule (README §6): the week grid, driven by GET /api/jobs' nextRun. */
export function ScheduleScreen() {
  const { data, loading, error } = useOpsApi<Job[]>('/api/jobs')
  const jobs = data ?? []

  const byDay: Record<string, { time: string; name: string; cadence: string }[]> = Object.fromEntries(DAYS.map(d => [d, []]))
  for (const j of jobs) {
    if (j.nextRun === null) continue
    const dt = new Date(j.nextRun)
    if (Number.isNaN(dt.getTime())) continue
    const day = DAYS[DAY_INDEX[dt.getUTCDay()] ?? 0]
    if (day === undefined) continue
    const time = `${String(dt.getUTCHours()).padStart(2, '0')}:${String(dt.getUTCMinutes()).padStart(2, '0')}`
    byDay[day]?.push({ time, name: j.automationId, cadence: cadenceLabel(j.cadenceMin) })
  }
  for (const d of DAYS) byDay[d]?.sort((a, b) => a.time.localeCompare(b.time))

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div style={{ minWidth: 0 }}>
          <div className={bp.kicker}>THIS WEEK · EVERYTHING ON A TIMER</div>
          <div className={bp.screenTitle}>Schedule</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '22px 26px 30px', minWidth: 880 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 22 }}>
            {/* Text-to-schedule drafting doesn't exist yet (same real gap as
               Automations' "Describe it") -- marked accordingly rather than
               a control that silently does nothing when clicked. */}
            <span style={{ padding: '7px 13px', border: LN, fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', opacity: 0.55 }}>＋ Add something on a schedule</span>
            <span className={bp.kicker} style={{ margin: 0, color: 'var(--dsw-alias-label-secondary)' }}>SOON</span>
            <span style={{ fontSize: 12, color: 'var(--dsw-alias-label-secondary)' }}>say it in plain English — "draft the weekly invoice summary every Monday morning"</span>
          </div>

          {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginBottom: 16 }}>Loading…</div>}
          {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginBottom: 16 }}>Couldn't reach Anton.</div>}
          {!loading && !error && jobs.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginBottom: 16 }}>Nothing on a timer yet — automations you add a schedule to will show up here.</div>
          )}

          {/* Week grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '1px', background: 'var(--dsw-alias-border-l2)' }}>
            {DAYS.map(d => (
              <div key={d} style={{ background: 'var(--dsw-alias-bg-base)', padding: '8px 12px', borderBottom: LN }}>
                <div style={{ fontSize: 10, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)' }}>{d}</div>
              </div>
            ))}
            {DAYS.map(d => (
              <div key={d} style={{ background: 'var(--dsw-alias-bg-base)', padding: '10px 12px', minHeight: 120, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {(byDay[d] ?? []).map((j, i) => (
                  <div key={i} style={{ padding: '8px 9px', background: 'var(--dsw-alias-state-business-tertiary)', borderLeft: '2px solid var(--dsw-alias-state-business-primary)' }}>
                    <div style={{ fontSize: 11, fontFamily: 'ui-monospace, monospace', color: 'var(--dsw-alias-state-business-primary)', marginBottom: 3 }}>{j.time}</div>
                    <div style={{ fontSize: 12.5, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', lineHeight: 1.3 }}>{j.name}</div>
                    <div style={{ fontSize: 10.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>{j.cadence}</div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
