import type { CSSProperties } from 'react'
import { useLiveStripUnpinned } from './responsive.ts'
import { useOpsApi } from './useOpsApi.ts'

type WorklogItem = { text: string; meta: string }
type Worklog = { ongoing: WorklogItem[]; done: WorklogItem[] }
type Approval = { id: number; title: string; age: string }
type Job = { id: string; automationId: string; trigger: { type?: string }; nextRun: string | null }
type LearningEntry = { title: string; body: string; when: string }

const KICKER: CSSProperties = { font: '400 10px/1 "Barlow", system-ui, sans-serif', letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)', marginBottom: 11 }

function upNextFromJobs(jobs: Job[]): { time: string; text: string }[] {
  return jobs
    .filter(j => j.nextRun !== null)
    .map(j => ({ dt: new Date(j.nextRun as string), name: j.automationId }))
    .filter(j => !Number.isNaN(j.dt.getTime()))
    .sort((a, b) => a.dt.getTime() - b.dt.getTime())
    .slice(0, 3)
    .map(j => ({
      time: `${String(j.dt.getUTCHours()).padStart(2, '0')}:${String(j.dt.getUTCMinutes()).padStart(2, '0')}`,
      text: j.name,
    }))
}

/**
 * The live strip (README, "Phase 2" / "Screens / Views" — 322px, persistent
 * on every screen): Right now, Waiting on you, Next up tonight, Just learned.
 * Reads real data from the same Ops Center APIs the full screens use —
 * /api/agent/worklog, /api/approvals, /api/jobs, /api/learning — rather than
 * a fixture, so a fresh install shows its own actual (empty) state, not
 * someone else's sample automations.
 */
export function LiveStrip() {
  const unpinned = useLiveStripUnpinned()
  const worklog = useOpsApi<Worklog>('/api/agent/worklog')
  const approvals = useOpsApi<Approval[]>('/api/approvals')
  const jobs = useOpsApi<Job[]>('/api/jobs')
  const learning = useOpsApi<LearningEntry[]>('/api/learning')

  if (unpinned) return null

  const live = worklog.data?.ongoing[0] ?? worklog.data?.done[0] ?? null
  const approvalList = approvals.data ?? []
  const upNext = upNextFromJobs(jobs.data ?? [])
  const learned = learning.data?.[0] ?? null

  return (
    <div style={{
      width: 322,
      height: '100%',
      borderLeft: '1px solid var(--dsw-alias-border-l2)',
      background: 'var(--dsw-alias-bg-layer-2)',
      overflowY: 'auto',
    }}
    >
      <div style={{ padding: '18px 18px 16px', borderBottom: '1px solid var(--dsw-alias-border-l2)' }}>
        <div style={{ ...KICKER, color: 'var(--dsw-alias-state-business-primary)' }}>Right now</div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, marginTop: 4, background: 'var(--dsw-alias-state-success-primary)', boxShadow: '0 0 0 3px rgba(63,125,85,.16)' }} />
          <div>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{live?.text ?? 'Nothing running right now'}</div>
            <div style={{ font: '11px ui-monospace, monospace', marginTop: 4, color: 'var(--dsw-alias-label-secondary)' }}>{live?.meta ?? 'idle'}</div>
          </div>
        </div>
      </div>

      <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--dsw-alias-border-l2)' }}>
        <div style={KICKER}>Waiting on you · {approvalList.length}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
          {approvalList.length === 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)' }}>Nothing waiting on you.</div>
          )}
          {approvalList.slice(0, 2).map((a) => (
            <div key={a.id} style={{ padding: '10px 11px', border: '1px solid var(--dsw-alias-border-l2)', cursor: 'pointer' }}>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{a.title}</div>
              <div style={{ font: '10.5px ui-monospace, monospace', marginTop: 4, color: 'var(--dsw-alias-label-secondary)' }}>{a.age}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--dsw-alias-border-l2)' }}>
        <div style={KICKER}>Next up</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {upNext.length === 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)' }}>Nothing scheduled yet.</div>
          )}
          {upNext.map((u, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
              <span style={{ flex: 'none', fontSize: 11, width: 46, color: 'var(--dsw-alias-accent-strong)', font: 'ui-monospace, monospace' }}>{u.time}</span>
              <span style={{ flex: 1, fontSize: 12.5, lineHeight: 1.4, color: 'var(--dsw-alias-label-primary)' }}>{u.text}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '16px 18px' }}>
        <div style={KICKER}>Just learned</div>
        <div style={{ fontSize: 13, lineHeight: 1.5, color: 'var(--dsw-alias-label-primary)' }}>{learned?.body || learned?.title || "Nothing learned yet — this fills in as Anton works."}</div>
        {learned !== null && (
          <div style={{ fontSize: 12, marginTop: 9, cursor: 'pointer', color: 'var(--dsw-alias-accent-strong)', borderBottom: '1px solid currentColor', display: 'inline-block' }}>Everything Anton learned →</div>
        )}
      </div>
    </div>
  )
}
