import { useState } from 'react'
import bp from '../blueprint.module.css'
import { Blueprint } from '../Blueprint.tsx'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/approvals -> Approval[] (README, Data Contracts). */
type Approval = {
  id: number
  title: string
  sub: string
  reason: string
  evidence: string
  changes: { sign: string; text: string }[]
  age: string
  kind: string
}

const KIND_LABEL: Record<string, string> = {
  money: 'MONEY MOVE', standing: 'STANDING APPROVAL', accounting: 'ACCOUNTING CHANGE', integration: 'NEW INTEGRATION',
}

function signColor(sign: string): string {
  if (sign === '+') return 'var(--dsw-alias-state-success-primary)'
  if (sign === '-') return 'var(--dsw-alias-state-error-primary)'
  return 'var(--dsw-alias-label-secondary)'
}

/** Waiting on you (README §5): live approval queue, decided once/always/defer through POST /api/approvals/:id. */
export function ApprovalsScreen() {
  const { data, loading, error } = useOpsApi<Approval[]>('/api/approvals')
  const [resolved, setResolved] = useState<Set<number>>(new Set())

  const decide = (id: number, decision: 'once' | 'always' | 'defer') => {
    fetch(`/api/approvals/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    }).then(() => {
      if (decision !== 'defer') setResolved(prev => new Set(prev).add(id))
    }).catch(() => { /* left pending; the list re-fetches next visit */ })
  }

  const approvals = (data ?? []).filter(a => !resolved.has(a.id))

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div style={{ minWidth: 0 }}>
          <div className={bp.kicker}>{approvals.length} DECISION{approvals.length === 1 ? '' : 'S'} ONLY A PERSON CAN MAKE</div>
          <div className={bp.screenTitle}>Waiting on you</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '22px 26px 30px', display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 1020, minWidth: 760 }}>
          {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
          {!loading && !error && approvals.length === 0 && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Nothing waiting on you right now.</div>
          )}
          {approvals.map(a => (
            <Blueprint key={a.id} style={{ background: 'var(--dsw-alias-bg-layer-2)' }}>
              {/* Header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '14px 18px', borderBottom: LN }}>
                <span className={bp.kicker} style={{ margin: 0, padding: '3px 8px', background: 'var(--dsw-alias-state-warn-tertiary)', color: 'var(--dsw-alias-state-warn-label)' }}>{KIND_LABEL[a.kind] ?? a.kind.toUpperCase()}</span>
                <span style={{ flex: 1 }} />
                <span className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>{a.age}</span>
              </div>
              {/* Body */}
              <div style={{ padding: '18px 18px 0' }}>
                <div className={bp.screenTitle} style={{ fontSize: 19, marginBottom: 8 }}>{a.title}</div>
                <div style={{ fontSize: 13.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 12 }}>{a.reason}</div>
                {a.evidence !== '' && (
                  <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 12, padding: '10px 12px', background: 'var(--dsw-alias-bg-base)', borderLeft: '2px solid var(--dsw-alias-state-business-primary)' }}>
                    {a.evidence}
                  </div>
                )}
                {a.changes.length > 0 && (
                  <div className={bp.mono} style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 18 }}>
                    {a.changes.map((c, j) => (
                      <div key={j} style={{ color: signColor(c.sign) }}>{c.sign}  {c.text}</div>
                    ))}
                  </div>
                )}
              </div>
              {/* Actions */}
              <div style={{ display: 'flex', gap: 8, padding: '0 18px 18px', alignItems: 'center' }}>
                <button onClick={() => { decide(a.id, 'once') }} style={{ padding: '7px 16px', background: 'var(--dsw-alias-state-business-primary)', color: 'var(--dsw-alias-bg-base)', border: 'none', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Approve once</button>
                <button onClick={() => { decide(a.id, 'always') }} style={{ padding: '7px 16px', background: 'transparent', color: 'var(--dsw-alias-label-primary)', border: LN, fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Approve, and stop asking</button>
                <button onClick={() => { decide(a.id, 'defer') }} style={{ padding: '7px 16px', background: 'transparent', color: 'var(--dsw-alias-label-primary)', border: LN, fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}>Not now</button>
                <span style={{ flex: 1 }} />
              </div>
            </Blueprint>
          ))}
        </div>
      </div>
    </div>
  )
}
