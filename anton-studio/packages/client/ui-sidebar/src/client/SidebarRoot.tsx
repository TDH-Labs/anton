import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { IconNewChatOutline16, IconPanelLeftOutline16, Tooltip } from '@deepseek-ai/dsh-client-ui-primitives'
import type { SidebarRootComponentProps } from './contract/slots.ts'
import type { OpsScreen } from './nav-store.ts'

/** One leaf nav row: routes to an ops screen via the shared nav-screen store. */
type NavItem = { key: OpsScreen; label: string; icon: string; badge?: string }
/** One labelled nav group (README Phase 3: "five labelled groups"). */
type NavGroup = { label: string; items: NavItem[] }

const NAV: NavGroup[] = [
  { label: 'Ask', items: [
    { key: 'ask', label: 'Ask Anton', icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' },
  ] },
  { label: 'Watch', items: [
    { key: 'now', label: 'Right now', icon: 'M22 12h-4l-3 9L9 3l-3 9H2' },
    { key: 'approvals', label: 'Waiting on you', icon: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z', badge: '2' },
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
 * The sidebar shell: brand row (`sidebar.brand.mark` / `sidebar.brand.name`
 * — ui-brand-official overrides these; declaring is claiming, contract/
 * slots.ts), the ops-nav screen groups (README Phase 3), the workspace/
 * session browser and settings/footer-action holes this package declares
 * (`sidebar.workspaces` / `sidebar.settings` / `sidebar.footer.action`), and
 * the Son of Anton toggle.
 *
 * Retired from the pre-redesign shell: the pointer-hover scrollbar reveal
 * and the collapse crossfade choreography (COLLAPSE_SETTLE_MS/quietBars/
 * railIn in the old SidebarRoot.module.css) — polish independent of the
 * Ops Center contract, not restored here. The column still collapses to a
 * 56px rail (manually, via the toggle button below, or automatically below
 * the narrow-viewport breakpoint), just without the eased crossfade.
 */
export function SidebarRoot({
  collapsed, renderSlot, startSession, toggleSidebar, t, useStore, actions,
}: SidebarRootComponentProps) {
  const [son, setSon] = useState(false)

  useEffect(() => {
    setSon(localStorage.getItem('sonOfAntonMode') === 'true')
    const handleToggle = () => { setSon(localStorage.getItem('sonOfAntonMode') === 'true') }
    window.addEventListener('son-of-anton-toggle', handleToggle)
    return () => { window.removeEventListener('son-of-anton-toggle', handleToggle) }
  }, [])

  const toggleSon = () => {
    const isSon = !son
    setSon(isSon)
    localStorage.setItem('sonOfAntonMode', String(isSon))
    if (isSon) {
      document.body.setAttribute('data-anton-mode', 'son')
    } else {
      document.body.removeAttribute('data-anton-mode')
    }
    globalThis.fetch(isSon ? '/api/mode/son-of-anton' : '/api/mode/standard', { method: 'POST' }).catch(console.error)
  }

  const activeScreen = useStore(s => s.screen)
  const wide = !collapsed
  const expandSidebar = () => { if (collapsed) toggleSidebar() }

  return (
    <div style={{
      width: collapsed ? 56 : 242,
      display: 'flex', flexDirection: 'column', height: '100%',
      background: 'var(--dsw-specific-sidebar-fill)',
      borderRight: '1px solid var(--dsw-alias-border-l2)',
      overflow: 'hidden',
    }}
    >
      <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 9, padding: '16px 16px 14px' }}>
        {wide && (
          <button
            type="button"
            onClick={() => { startSession() }}
            aria-label={t('session.new.label')}
            style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 9, padding: 0, border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer', textAlign: 'left' }}
          >
            <span aria-hidden="true" style={{ flex: 'none', display: 'inline-flex' }}>
              {renderSlot('sidebar.brand.mark', { size: 26 }, {
                fallback: <img src={son ? '/son_of_anton_logo.svg' : '/anton_logo.jpg'} alt="" style={{ width: 26, height: 26 }} />,
              })}
            </span>
            <span style={{ minWidth: 0 }}>
              {renderSlot('sidebar.brand.name', {}, {
                fallback: (
                  <>
                    <div style={{ fontFamily: 'var(--dsw-font-family-heading, "Barlow Condensed", system-ui, sans-serif)', fontWeight: 600, fontSize: 19, lineHeight: 1, color: 'var(--dsw-alias-label-primary)', letterSpacing: '-0.01em' }}>{son ? 'Son of Anton' : 'Anton'}</div>
                    <div style={{ fontFamily: 'var(--dsw-font-family, "Barlow", system-ui, sans-serif)', fontSize: 10, lineHeight: 1, letterSpacing: '.14em', textTransform: 'uppercase', marginTop: 3, color: 'var(--dsw-alias-label-secondary)' }}>{son ? 'Buckle Up' : 'Cog in Your Wheel'}</div>
                  </>
                ),
              })}
            </span>
          </button>
        )}
        <Tooltip label={collapsed ? t('toggle.open') : t('toggle.collapse')} delayMs={500}>
          <button
            type="button"
            onClick={() => { toggleSidebar() }}
            aria-label={collapsed ? t('toggle.open') : t('toggle.collapse')}
            style={{ flex: 'none', width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--dsw-alias-label-secondary)' }}
          >
            {!wide
              ? <span aria-hidden="true" style={{ display: 'inline-flex' }}>{renderSlot('sidebar.brand.mark', { size: 24 }, { fallback: <img src={son ? '/son_of_anton_logo.svg' : '/anton_logo.jpg'} alt="" style={{ width: 24, height: 24 }} /> })}</span>
              : <IconPanelLeftOutline16 size={16} />}
          </button>
        </Tooltip>
      </div>

      <div style={{ flex: 'none', padding: '0 12px 10px' }}>
        {/* Persistent trigger: the wordmark's New-Session shortcut only exists
            while wide, so this is the sole way to start a session from the
            collapsed rail. */}
        <Tooltip label={t('session.new.label')} delayMs={500} disabled={wide}>
          <button
            type="button"
            onClick={() => { startSession() }}
            aria-label={t('session.new.label')}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', justifyContent: wide ? 'flex-start' : 'center',
              gap: 9, padding: wide ? '8px 10px' : '8px', cursor: 'pointer',
              border: '1px solid var(--dsw-alias-border-l2)', background: 'transparent', color: 'var(--dsw-alias-label-primary)',
            }}
          >
            <IconNewChatOutline16 size={wide ? 14 : 18} />
            {wide && <span style={{ fontSize: 12.5 }}>{t('session.new.label')}</span>}
          </button>
        </Tooltip>
      </div>

      <div style={{ flex: 'none', overflowY: 'auto', padding: '2px 8px 8px', maxHeight: '58%' }}>
        {NAV.map((g, idx) => (
          <div key={idx} style={{ marginBottom: 14 }}>
            {!collapsed && <div style={{ padding: '0 8px 6px', fontFamily: 'var(--dsw-font-family, "Barlow", system-ui, sans-serif)', fontSize: 10, lineHeight: 1, letterSpacing: '.14em', textTransform: 'uppercase', color: 'var(--dsw-alias-label-secondary)' }}>{g.label}</div>}
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
                  {!collapsed && it.badge !== undefined && <span style={{ flex: 'none', fontSize: 10, padding: '1px 6px', background: 'var(--dsw-alias-state-business-primary)', color: 'var(--dsw-alias-bg-base)', fontFamily: 'ui-monospace, monospace' }}>{it.badge}</span>}
                </div>
              )
            })}
          </div>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0, borderTop: '1px solid var(--dsw-alias-border-l2)', display: 'flex', flexDirection: 'column' }}>
        {renderSlot('sidebar.workspaces', { wide, expandSidebar })}
      </div>

      <div style={{ flex: 'none', padding: '10px 12px 14px', borderTop: '1px solid var(--dsw-alias-border-l2)', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div onClick={toggleSon} style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '9px 10px', cursor: 'pointer',
          border: `1px solid ${son ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`,
          background: son ? 'var(--dsw-alias-state-business-tertiary)' : 'transparent',
          color: son ? 'var(--dsw-alias-accent-strong)' : 'var(--dsw-alias-label-primary)',
        }}
        >
          <img src="/son_of_anton_logo.svg" alt="" style={{ width: 22, height: 22, flex: 'none' }} />
          {!collapsed && (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 500, lineHeight: 1.2 }}>Son of Anton</div>
                <div style={{ fontSize: 10.5, lineHeight: 1.3, opacity: 0.7 }}>Buckle Up</div>
              </div>
              <div style={{ flex: 'none', width: 30, height: 16, padding: 2, background: son ? 'var(--dsw-alias-state-business-primary)' : 'transparent', border: `1px solid ${son ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`, display: 'flex', justifyContent: son ? 'flex-end' : 'flex-start', boxSizing: 'border-box' }}>
                <div style={{ width: 10, height: 10, background: son ? 'var(--dsw-alias-bg-base)' : 'var(--dsw-alias-label-secondary)' }} />
              </div>
            </>
          )}
        </div>
        <div onClick={() => { actions.setScreen('setup') }} style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, padding: '8px 10px', cursor: 'pointer',
          border: '1px solid var(--dsw-alias-border-l2)', color: 'var(--dsw-alias-label-primary)', fontSize: 12.5,
        }}
        >
          {!collapsed ? 'Set up' : (
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
          )}
        </div>
        {renderSlot('sidebar.footer.action', { wide })}
        {renderSlot('sidebar.settings', { wide })}
      </div>
    </div>
  )
}
