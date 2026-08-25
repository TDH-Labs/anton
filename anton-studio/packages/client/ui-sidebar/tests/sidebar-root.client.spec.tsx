// @vitest-environment jsdom
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type {
  SidebarFooterActionOwnerProps, SidebarRootComponentProps, SidebarSectionOwnerProps,
  SidebarSettingsOwnerProps,
} from '../src/client/contract/slots.ts'
import { SidebarRoot } from '../src/client/SidebarRoot.tsx'
import { en } from '../src/client/locales.ts'

const t: SidebarRootComponentProps['t'] = key => (en as Record<string, string>)[key] ?? key
const neverHook = (() => { throw new Error('shell must not read global hooks') }) as never

afterEach(() => { cleanup() })

// SidebarRoot owns no store (see SidebarRootInjected's own doc: "No store is
// registered") — `sidebar.nav` is filled entirely by whoever registers into
// that slot (ui-anton-ops, product-side), same as every other declared hole.
// Ops-nav rendering/routing and the setup-wizard foot control both used to
// be exercised here because SidebarRoot rendered that content directly; both
// moved with the content itself and belong in ui-anton-ops's own tests now,
// not here.
function mountShell({ collapsed = false }: { collapsed?: boolean } = {}) {
  const startSession = vi.fn()
  const toggleSidebar = vi.fn()
  let regionOwner: SidebarSectionOwnerProps | undefined
  let settingsOwner: SidebarSettingsOwnerProps | undefined
  let footerActionOwner: SidebarFooterActionOwnerProps | undefined
  const brandMark = <span data-testid="custom-brand-mark">M</span>
  const brandName = <span data-testid="custom-brand-name">Custom Brand</span>

  const view = render(
    <SidebarRoot
      collapsed={collapsed} width={242}
      useSessions={neverHook} useWorkspaces={neverHook}
      startSession={startSession} toggleSidebar={toggleSidebar} t={t}
      renderSlot={((
        key: string,
        owner: SidebarFooterActionOwnerProps | SidebarSectionOwnerProps | SidebarSettingsOwnerProps,
        _options?: { fallback?: ReactNode },
      ) => {
        if (key === 'sidebar.brand.mark') return brandMark
        if (key === 'sidebar.brand.name') return brandName
        if (key === 'sidebar.settings') {
          settingsOwner = owner as SidebarSettingsOwnerProps
          return <div data-testid="settings-seat" data-wide={(owner as SidebarSettingsOwnerProps).wide} />
        }
        if (key === 'sidebar.footer.action') {
          footerActionOwner = owner as SidebarFooterActionOwnerProps
          return <div data-testid="footer-action-seat" data-wide={(owner as SidebarFooterActionOwnerProps).wide} />
        }
        if (key === 'sidebar.nav') {
          return <div data-testid="nav-seat" data-wide={(owner as SidebarSectionOwnerProps).wide} />
        }
        // sidebar.workspaces is the only remaining declared slot, and the
        // only one SidebarRoot hands an expandSidebar callback (see
        // SidebarRoot.tsx) — that's what "region" has always meant here.
        regionOwner = owner as SidebarSectionOwnerProps
        return <div data-testid="region" data-wide={(owner as SidebarSectionOwnerProps).wide} />
      }) as SidebarRootComponentProps['renderSlot']}
    />,
  )
  return {
    startSession,
    toggleSidebar,
    view,
    regionOwner: () => {
      if (regionOwner === undefined) throw new Error('region owner not rendered')
      return regionOwner
    },
    settingsOwner: () => {
      if (settingsOwner === undefined) throw new Error('settings owner not rendered')
      return settingsOwner
    },
    footerActionOwner: () => {
      if (footerActionOwner === undefined) throw new Error('footer action owner not rendered')
      return footerActionOwner
    },
  }
}

describe('SidebarRoot shell', () => {
  it('fills the declared brand, workspaces, settings, and footer-action holes', () => {
    const b = mountShell()
    expect(screen.getByTestId('custom-brand-mark')).toBeTruthy()
    expect(screen.getByTestId('custom-brand-name')).toBeTruthy()
    expect(screen.getByTestId('region')).toBeTruthy()
    expect(screen.getByTestId('settings-seat')).toBeTruthy()
    expect(screen.getByTestId('footer-action-seat')).toBeTruthy()
    expect(b.regionOwner().wide).toBe(true)
    expect(b.settingsOwner().wide).toBe(true)
    expect(b.footerActionOwner().wide).toBe(true)
  })

  it('starts a new session from the brand row and the capsule, and toggles the column', () => {
    const b = mountShell()
    const newSessionButtons = screen.getAllByRole('button', { name: 'New session' })
    expect(newSessionButtons).toHaveLength(2)
    fireEvent.click(newSessionButtons[0]!)
    expect(b.startSession).toHaveBeenCalledOnce()
    fireEvent.click(newSessionButtons[1]!)
    expect(b.startSession).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(b.toggleSidebar).toHaveBeenCalledOnce()
  })

  it('renders the rail on the collapsed state, with only the capsule New Session button', () => {
    mountShell({ collapsed: true })
    expect(screen.getAllByRole('button', { name: 'New session' })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Open sidebar' })).toBeTruthy()
    expect(screen.getByTestId('region')).toBeTruthy()
  })

  it('hands the region an expandSidebar request that only acts while collapsed', () => {
    const wideShell = mountShell()
    wideShell.regionOwner().expandSidebar()
    expect(wideShell.toggleSidebar).not.toHaveBeenCalled()

    const railShell = mountShell({ collapsed: true })
    railShell.regionOwner().expandSidebar()
    expect(railShell.toggleSidebar).toHaveBeenCalledOnce()
  })
})
