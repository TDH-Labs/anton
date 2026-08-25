import { useEffect, useState } from 'react'
import type { ReactElement } from 'react'
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots'
import type {
  SidebarBrandMarkOwnerProps, SidebarBrandNameOwnerProps, createNavScreenStore,
} from '@deepseek-ai/dsh-client-ui-sidebar/client'

/** Registers into `sidebar.brand.mark`: the Anton / Son-of-Anton mark. */
export function AntonBrandMark({ size }: SidebarBrandMarkOwnerProps): ReactElement {
  const son = useSon()
  return <img src={son ? '/son_of_anton_logo.svg' : '/anton_logo.jpg'} alt="" style={{ width: size, height: size }} />
}

/** Registers into `sidebar.brand.name`: the Anton wordmark + tagline. */
export function AntonBrandName(_: SidebarBrandNameOwnerProps): ReactElement {
  const son = useSon()
  return (
    <>
      <div style={{ fontFamily: 'var(--dsw-font-family-heading, "Barlow Condensed", system-ui, sans-serif)', fontWeight: 600, fontSize: 19, lineHeight: 1, color: 'var(--dsw-alias-label-primary)', letterSpacing: '-0.01em' }}>{son ? 'Son of Anton' : 'Anton'}</div>
      <div style={{ fontFamily: 'var(--dsw-font-family, "Barlow", system-ui, sans-serif)', fontSize: 10, lineHeight: 1, letterSpacing: '.14em', textTransform: 'uppercase', marginTop: 3, color: 'var(--dsw-alias-label-secondary)' }}>{son ? 'Buckle Up' : 'Cog in Your Wheel'}</div>
    </>
  )
}

function useSon(): boolean {
  const [son, setSon] = useState(false)
  useEffect(() => {
    const read = () => setSon(localStorage.getItem('sonOfAntonMode') === 'true')
    read()
    window.addEventListener('son-of-anton-toggle', read)
    return () => { window.removeEventListener('son-of-anton-toggle', read) }
  }, [])
  return son
}

function toggleSonMode() {
  const isSon = localStorage.getItem('sonOfAntonMode') !== 'true'
  localStorage.setItem('sonOfAntonMode', String(isSon))
  if (isSon) document.body.setAttribute('data-anton-mode', 'son')
  else document.body.removeAttribute('data-anton-mode')
  globalThis.fetch(isSon ? '/api/mode/son-of-anton' : '/api/mode/standard', { method: 'POST' }).catch(() => {})
  window.dispatchEvent(new Event('son-of-anton-toggle'))
}

/** One `sidebar.footer.action` item: the Son-of-Anton toggle + Setup. */
export function AntonFooterActions({ actions, wide }: PropsStore<ReturnType<typeof createNavScreenStore>> & { wide: boolean }) {
  const son = useSon()
  const collapsed = !wide
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div onClick={toggleSonMode} style={{
        display: 'flex', alignItems: 'center', gap: 10, padding: '9px 10px', cursor: 'pointer',
        border: `1px solid ${son ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsh-sidebar-footer-border, var(--dsw-alias-border-l2))'}`,
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
    </div>
  )
}