import { useEffect, useState } from 'react'
import bp from './blueprint.module.css'
import { GROUP_LABEL, NAV, screenFromHash, type NavEntry, type ScreenId } from './nav.ts'
import { useOpsApi } from './useOpsApi.ts'
import { RightNowScreen } from './screens/RightNowScreen.tsx'
import { ApprovalsScreen } from './screens/ApprovalsScreen.tsx'
import { AlertsScreen } from './screens/AlertsScreen.tsx'
import { AutomationsScreen } from './screens/AutomationsScreen.tsx'
import { ScheduleScreen } from './screens/ScheduleScreen.tsx'
import { MemoryScreen } from './screens/MemoryScreen.tsx'
import { LearningScreen } from './screens/LearningScreen.tsx'
import { AddonsScreen } from './screens/AddonsScreen.tsx'
import { SetupScreen } from './screens/SetupScreen.tsx'
import { SettingsScreen } from './SettingsScreen.tsx'

const LN = '1px solid var(--dsw-alias-border-l2)'

function renderScreen(id: ScreenId) {
  switch (id) {
    case 'right-now': return <RightNowScreen />
    case 'approvals': return <ApprovalsScreen />
    case 'alerts': return <AlertsScreen />
    case 'automations': return <AutomationsScreen />
    case 'schedule': return <ScheduleScreen />
    case 'memory': return <MemoryScreen />
    case 'learning': return <LearningScreen />
    case 'addons': return <AddonsScreen />
    case 'settings': return <SettingsScreen />
    case 'setup': return <SetupScreen />
  }
}

/**
 * The Ops Center shell: nav rail, active screen, and the live strip.
 *
 * Screen selection is component state mirrored into the URL hash, replacing
 * the vendored harness's slot registry and DI container -- one tree owns the
 * screen, so there is nothing to register into.
 */
export function App() {
  const [screen, setScreen] = useState<ScreenId>(screenFromHash)

  useEffect(() => {
    const onHash = () => { setScreen(screenFromHash()) }
    window.addEventListener('hashchange', onHash)
    return () => { window.removeEventListener('hashchange', onHash) }
  }, [])

  const go = (id: ScreenId) => {
    window.location.hash = `#/${id}`
    setScreen(id)
  }

  const groups = ['watch', 'run', 'know', 'setup'] as const

  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)' }}>
      <nav style={{ flex: 'none', width: 210, borderRight: LN, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-layer-2)' }}>
        <div style={{ padding: '16px 18px 14px', borderBottom: LN }}>
          <div style={{ fontFamily: 'Barlow Condensed, sans-serif', fontWeight: 700, fontSize: 21, letterSpacing: '-0.01em' }}>Anton</div>
          <div className={bp.kicker} style={{ margin: '2px 0 0' }}>COG IN YOUR WHEEL</div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '10px 0' }}>
          {groups.map(group => (
            <div key={group} style={{ marginBottom: 10 }}>
              <div className={bp.kicker} style={{ padding: '6px 18px 4px' }}>{GROUP_LABEL[group]}</div>
              {NAV.filter((e: NavEntry) => e.group === group).map(entry => (
                <button
                  key={entry.id}
                  onClick={() => { go(entry.id) }}
                  aria-current={screen === entry.id ? 'page' : undefined}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '7px 18px', border: 'none', fontSize: 13.5, fontFamily: 'inherit',
                    cursor: 'pointer',
                    background: screen === entry.id ? 'var(--dsw-alias-bg-base)' : 'transparent',
                    color: screen === entry.id
                      ? 'var(--dsw-alias-state-business-primary)'
                      : 'var(--dsw-alias-label-primary)',
                    fontWeight: screen === entry.id ? 600 : 400,
                  }}
                >{entry.label}</button>
              ))}
            </div>
          ))}
        </div>
        <button
          onClick={() => { go('setup') }}
          style={{ flex: 'none', padding: '11px 18px', borderTop: LN, border: 'none', borderTopWidth: 1, borderTopStyle: 'solid', borderTopColor: 'var(--dsw-alias-border-l2)', background: 'transparent', color: 'var(--dsw-alias-label-secondary)', fontSize: 12.5, fontFamily: 'inherit', textAlign: 'left', cursor: 'pointer' }}
        >Set up</button>
      </nav>

      <main style={{ flex: 1, minWidth: 0, display: 'flex' }}>{renderScreen(screen)}</main>

      <LiveStrip onGo={go} />
    </div>
  )
}

type Approval = { id: number }
type Worklog = { ongoing: { text: string; status?: string }[] }

/** The right-hand strip: what is running, and what needs a person. */
function LiveStrip(props: { onGo: (id: ScreenId) => void }) {
  const work = useOpsApi<Worklog>('/api/agent/worklog')
  const approvals = useOpsApi<Approval[]>('/api/approvals')
  const running = (work.data?.ongoing ?? []).filter(o => o.status === 'running')
  const waiting = approvals.data?.length ?? 0

  return (
    <aside style={{ flex: 'none', width: 208, borderLeft: LN, padding: '16px 16px 20px', overflowY: 'auto', background: 'var(--dsw-alias-bg-layer-2)' }}>
      <div className={bp.kicker}>RIGHT NOW</div>
      {running.length === 0
        ? <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 20 }}>Nothing running.</div>
        : running.map((o, i) => (
          <div key={i} style={{ fontSize: 12.5, marginBottom: 6, display: 'flex', gap: 7, alignItems: 'center' }}>
            <span style={{ width: 6, height: 6, background: 'var(--dsw-alias-state-business-primary)', flex: 'none' }} />
            {o.text}
          </div>
        ))}
      <div className={bp.kicker} style={{ marginTop: 18 }}>WAITING ON YOU · {waiting}</div>
      {waiting === 0
        ? <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)' }}>Nothing waiting on you.</div>
        : (
          <button
            onClick={() => { props.onGo('approvals') }}
            style={{ padding: '5px 10px', border: LN, background: 'transparent', color: 'var(--dsw-alias-label-primary)', fontSize: 12.5, fontFamily: 'inherit', cursor: 'pointer' }}
          >Review {waiting}</button>
        )}
    </aside>
  )
}
