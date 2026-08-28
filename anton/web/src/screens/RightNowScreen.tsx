import { useState } from 'react'
import bp from '../blueprint.module.css'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** GET /api/agent/worklog */
type Worklog = {
  ongoing: { text: string; meta: string; pct: number | null; status?: string }[]
  done: { text: string; meta: string; status: string }[]
}

/** GET /api/jobs/state */
type JobState = {
  job_id: string
  paused: boolean
  run_now: boolean
  skip_next: boolean
  running: boolean
  started_at: string | null
}

const DOT: Record<string, string> = {
  ok: 'var(--dsw-alias-state-success-primary)',
  fail: 'var(--dsw-alias-state-error-primary)',
  skipped: 'var(--dsw-alias-label-secondary)',
  running: 'var(--dsw-alias-state-business-primary)',
}

/**
 * Right Now: what Anton is doing, what it just did, and the controls to
 * redirect it. This is the screen that answers "what's it working on",
 * "reprioritize it", and "what has it done" in one place.
 *
 * Every steering verb lands at the scheduler's next poll tick and none
 * interrupts a run already in flight (cmd_serve dispatches synchronously),
 * so the confirmation copy says exactly that rather than implying the job
 * stops the moment the button is pressed.
 */
export function RightNowScreen() {
  const work = useOpsApi<Worklog>('/api/agent/worklog')
  const jobs = useOpsApi<{ jobs: JobState[] }>('/api/jobs/state')
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const steer = (jobId: string, action: string, label: string) => {
    setBusy(`${jobId}:${action}`)
    fetch(`/api/jobs/${encodeURIComponent(jobId)}/steer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status))
        const body = await r.json()
        setNotice(`${label} ${jobId} — ${body.takes_effect}. A run already in progress finishes first.`)
        jobs.refetch()
        work.refetch()
      })
      .catch(() => { setNotice(`Couldn't ${label.toLowerCase()} ${jobId}. Try again.`) })
      .finally(() => { setBusy(null) })
  }

  const running = (work.data?.ongoing ?? []).filter(o => o.status === 'running')
  const scheduled = (work.data?.ongoing ?? []).filter(o => o.status !== 'running')
  const done = work.data?.done ?? []
  const jobRows = jobs.data?.jobs ?? []

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', padding: '18px 26px 14px', borderBottom: LN }}>
        <div className={bp.kicker}>
          {running.length > 0 ? `${running.length} RUNNING NOW` : 'NOTHING RUNNING RIGHT NOW'}
        </div>
        <div className={bp.screenTitle}>Right now</div>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '20px 26px 30px', maxWidth: 1020 }}>
          {notice !== null && (
            <div style={{ marginBottom: 18, padding: '10px 12px', border: LN, fontSize: 13, background: 'var(--dsw-alias-bg-layer-2)' }}>
              {notice}{' '}
              <span
                onClick={() => { setNotice(null) }}
                style={{ color: 'var(--dsw-alias-state-business-primary)', cursor: 'pointer', borderBottom: '1px solid currentColor' }}
              >Dismiss</span>
            </div>
          )}

          {/* In flight — real dispatch state, not "its cron window is due". */}
          <div className={bp.kicker} style={{ marginBottom: 8 }}>IN FLIGHT</div>
          {work.loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {work.error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-state-error-primary)' }}>Couldn't reach Anton.</div>}
          {!work.loading && !work.error && running.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', marginBottom: 22 }}>
              Nothing is running this moment. Scheduled work is listed below.
            </div>
          )}
          {running.map((o, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderBottom: LN }}>
              <span style={{ width: 7, height: 7, background: DOT.running, flex: 'none' }} />
              <span style={{ fontSize: 13.5 }}>{o.text}</span>
              <span style={{ flex: 1 }} />
              <span className={bp.mono} style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>{o.meta}</span>
            </div>
          ))}

          {scheduled.length > 0 && (
            <>
              <div className={bp.kicker} style={{ margin: '24px 0 8px' }}>DUE THIS TICK</div>
              {scheduled.map((o, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: LN }}>
                  <span style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>{o.text}</span>
                  <span style={{ flex: 1 }} />
                  <span className={bp.mono} style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>{o.meta}</span>
                </div>
              ))}
            </>
          )}

          {/* Steering. Three verbs, because a cron system has no useful
              notion of a priority integer. */}
          <div className={bp.kicker} style={{ margin: '30px 0 8px' }}>YOUR AUTOMATIONS</div>
          {jobs.loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {!jobs.loading && jobRows.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>No automations set up yet.</div>
          )}
          {jobRows.map(j => (
            <div key={j.job_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: LN, flexWrap: 'wrap' }}>
              <span className={bp.mono} style={{ fontSize: 13, minWidth: 180 }}>{j.job_id}</span>
              {j.running && (
                <span className={bp.kicker} style={{ margin: 0, padding: '2px 7px', background: 'var(--dsw-alias-state-business-primary)', color: 'var(--dsw-alias-bg-base)' }}>RUNNING</span>
              )}
              {j.paused && (
                <span className={bp.kicker} style={{ margin: 0, padding: '2px 7px', background: 'var(--dsw-alias-state-warn-tertiary)', color: 'var(--dsw-alias-state-warn-label)' }}>PAUSED</span>
              )}
              {j.run_now && !j.running && (
                <span className={bp.kicker} style={{ margin: 0, padding: '2px 7px', border: LN }}>RUN QUEUED</span>
              )}
              {j.skip_next && (
                <span className={bp.kicker} style={{ margin: 0, padding: '2px 7px', border: LN }}>SKIPPING NEXT</span>
              )}
              <span style={{ flex: 1 }} />
              <SteerButton label={j.paused ? 'Resume' : 'Pause'} disabled={busy !== null}
                onClick={() => { steer(j.job_id, j.paused ? 'resume' : 'pause', j.paused ? 'Resumed' : 'Paused') }} />
              <SteerButton label="Run now" disabled={busy !== null || j.paused}
                onClick={() => { steer(j.job_id, 'run-now', 'Queued') }} />
              <SteerButton label="Skip next" disabled={busy !== null || j.paused}
                onClick={() => { steer(j.job_id, 'skip-next', 'Will skip the next window for') }} />
            </div>
          ))}

          {/* What it has done — today's ledger, with honest statuses. */}
          <div className={bp.kicker} style={{ margin: '30px 0 8px' }}>DONE TODAY</div>
          {!work.loading && done.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing has run yet today.</div>
          )}
          {done.map((d, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: LN }}>
              <span style={{ width: 7, height: 7, background: DOT[d.status] ?? DOT.skipped, flex: 'none' }} />
              <span style={{ fontSize: 13 }}>{d.text}</span>
              <span style={{ flex: 1 }} />
              <span className={bp.mono} style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>{d.meta}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SteerButton(props: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={props.onClick}
      disabled={props.disabled}
      style={{
        padding: '5px 11px', background: 'transparent', color: 'var(--dsw-alias-label-primary)',
        border: LN, fontSize: 12.5, fontFamily: 'inherit',
        cursor: props.disabled ? 'default' : 'pointer', opacity: props.disabled ? 0.45 : 1,
      }}
    >{props.label}</button>
  )
}
