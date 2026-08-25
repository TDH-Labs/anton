import type { CSSProperties } from 'react'
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots'
import type { createNavScreenStore, OpsScreen, SidebarNavOwnerProps } from '@deepseek-ai/dsh-client-ui-sidebar/client'
import { useOpsApi } from './useOpsApi.ts'

/** One leaf nav row: routes to an ops screen via the shared nav-screen store. */
type NavItem = { key: OpsScreen; label: string; icon: string; badge?: 'approvals' }
/** One labelled nav group (README Phase 3: "five labelled groups"). */
type NavGroup = { label: string; items: NavItem[] }

const NAV: NavGroup[] = [
  { label: 'Ask', items: [
    { key: 'ask', label: 'Ask Anton', icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' },
  ] },
  { label: 'Watch', items: [
    { key: 'now', label: 'Right now', icon: 'M22 12h-4l-3 9L9 3l-3 9H2' },
    { key: 'approvals', label: 'Waiting on you', icon: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z', badge: 'approvals' },
    { key: 'alerts', label: 'What went wrong', icon: 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0' },
  ] },
  { label: 'Run', items: [
    { key: 'automations', label: 'Automations', icon: 'M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM15 6a9 9 0 0 0-9 9' },
    { key: 'schedule', label: 'Schedule', icon: 'M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6' },
  ] },
  { label: 'Know', items: [
    { key: 'memory', label: 'Memory', icon: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10' },
    { key: 'learning', label: 'What Anton learned', icon: 'M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6' },
  ] },
  { label: 'Extend', items: [
    { key: 'addons', label: 'Add-ons', icon: 'm7.5 4.27 9 5.15M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z' },
  ] },
]

/**
 * Ops nav groups registered into the `sidebar.nav` seat (declared by
 * ui-sidebar's shell; this occupant fills it). Writes the active screen via
 * the shared nav-screen store; reads the same store to highlight the current
 * screen. The approvals badge reads /api/approvals — the same source as the
 * Right-now tile and the Approvals inbox, so all three agree.
 */
export function OpsNav({
  useStore, actions, wide,
}: PropsStore<ReturnType<typeof createNavScreenStore>> & Pick<SidebarNavOwnerProps, 'wide'>) {
  const activeScreen = useStore((s) => s.screen)
  const approvalsState = useOpsApi<unknown[]>('/api/approvals')
  const approvalsCount = (approvalsState.data ?? []).length
  const collapsed = !wide

  return (
    <div style={{ overflowY: 'auto', padding: '2px 8px 8px' }}>
      {NAV.map((g, idx) => (
        <div key={idx} style={{ marginBottom: 14 }}>
          {!collapsed && (
            <div style={{
              padding: '0 8px 6px', fontFamily: 'var(--dsw-font-family, "Barlow", system-ui, sans-serif)',
              fontSize: 10, lineHeight: 1, letterSpacing: '.14em', textTransform: 'uppercase',
              color: 'var(--dsw-alias-label-secondary)',
            }}
            >
              {g.label}
            </div>
          )}
          {g.items.map((it, i) => {
            const active = it.key === activeScreen
            const rowStyle: CSSProperties = {
              display: 'flex', alignItems: 'center', gap: 10, padding: '7px 9px', fontSize: 13.5, cursor: 'pointer',
              background: active ? 'var(--dsw-alias-state-business-tertiary)' : 'transparent',
              boxShadow: active ? 'inset 2px 0 0 var(--dsw-alias-state-business-primary)' : 'none',
              color: active ? 'var(--dsw-alias-accent-strong)' : 'var(--dsw-alias-label-primary)',
              fontWeight: active ? 500 : 400,
            }
            return (
              <div key={i} onClick={() => { actions.setScreen(it.key) }} style={rowStyle}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ flex: 'none', opacity: 0.85 }}><path d={it.icon} /></svg>
                {!collapsed && <span style={{ flex: 1, minWidth: 0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.label}</span>}
                {!collapsed && it.badge === 'approvals' && approvalsCount > 0 && (
                  <span style={{
                    flex: 'none', fontSize: 10, padding: '1px 6px', background: 'var(--dsw-alias-state-business-primary)',
                    color: 'var(--dsw-alias-bg-base)', fontFamily: 'ui-monospace, monospace',
                  }}
                  >
                    {approvalsCount}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}