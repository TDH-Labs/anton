// @vitest-environment jsdom
/** The three v0.2.3 "Right now" shell bugs stay fixed:
 * 1. Right-now screen click targets actually route (inbox link + approval cards).
 * 2. The sidebar Waiting-on-you badge reflects GET /api/approvals, not a literal.
 * 3. Starting a session while an ops overlay is up surfaces the chat again. */
import { useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { PropsStore, SnapshotSelectorHook } from '@deepseek-ai/dsh-client-ui-slots'
import type { SessionListState } from '@deepseek-ai/dsh-client-runtime/client'
import { OpsNowScreen } from '../src/client/OpsNowScreen.tsx'
import { OpsCockpit } from '../src/client/OpsCockpit.tsx'
import { SidebarRoot } from '../src/client/SidebarRoot.tsx'
import { createNavScreenStore } from '../src/client/nav-store.ts'
import { en } from '../src/client/locales.ts'

const t: (key: never) => string = key => (en as Record<string, string>)[key as string] ?? key

/** jsdom lacks matchMedia; OpsCockpit reads the live-strip breakpoint on mount. */
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
})

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

/** Wraps a bare EngineStoreInstance into the selector-hook shape `PropsStore.useStore` requires. */
function bindStoreHook<T>(instance: { getSnapshot: () => T; subscribe: (fn: () => void) => () => void }) {
  return function useBound<S>(selector: (state: T) => S): S {
    return useSyncExternalStore(instance.subscribe, () => selector(instance.getSnapshot()))
  }
}

/** Minimal well-shaped bodies for the three Right-now reads (systems / worklog / approvals). */
function opsFetch(approvals: unknown[]) {
  return vi.fn((url: string) => {
    let body: unknown = []
    if (url.includes('/api/approvals')) body = approvals
    if (url.includes('/api/agent/worklog')) body = { ongoing: [], done: [] }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
  })
}

type ListState<T> = { getSnapshot: () => T; subscribe: (fn: () => void) => () => void }

function mountNowScreen(store = createNavScreenStore().create()) {
  const props: PropsStore<ReturnType<typeof createNavScreenStore>> = {
    useStore: bindStoreHook(store),
    actions: store.actions,
  }
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('offline'))))
  render(<OpsNowScreen {...props} />)
  return store
}

describe('Right-now screen routes to the approvals inbox', () => {
  it('the Open-the-inbox link sets the shared screen', () => {
    const store = mountNowScreen()
    fireEvent.click(screen.getByText('Open the inbox'))
    expect(store.getSnapshot().screen).toBe('approvals')
  })

  it('an approval mini-card also routes', async () => {
    const store = createNavScreenStore().create()
    vi.stubGlobal('fetch', opsFetch([{ id: 1, title: 'T', sub: 'S', kind: 'money' }]))
    const props: PropsStore<ReturnType<typeof createNavScreenStore>> = {
      useStore: bindStoreHook(store),
      actions: store.actions,
    }
    render(<OpsNowScreen {...props} />)
    await waitFor(() => expect(screen.getByText('T')).toBeTruthy())
    fireEvent.click(screen.getByText('T'))
    expect(store.getSnapshot().screen).toBe('approvals')
  })
})

describe('Sidebar Waiting-on-you badge is live, not hardcoded', () => {
  function mountBadge(fetchJson: unknown[] | 'error') {
    vi.stubGlobal('fetch', vi.fn(() => (
      fetchJson === 'error'
        ? Promise.reject(new TypeError('offline'))
        : Promise.resolve({ ok: true, json: () => Promise.resolve(fetchJson) })
    )))
    const store = createNavScreenStore().create()
    const neverHook = (() => { throw new Error('not used') }) as never
    render(
      <SidebarRoot
        collapsed={false} width={242}
        useSessions={neverHook} useWorkspaces={neverHook}
        startSession={vi.fn()} toggleSidebar={vi.fn()} t={t}
        useStore={bindStoreHook(store)} actions={store.actions}
        renderSlot={() => <div data-testid="seat" /> as ReactNode}
      />,
    )
    return store
  }

  it('shows the live pending count when approvals exist', async () => {
    mountBadge([{ id: 1 }, { id: 2 }, { id: 3 }])
    await waitFor(() => expect(screen.getByText('3')).toBeTruthy())
  })

  it('hides the badge at zero and on fetch failure — never shows a stale literal', async () => {
    mountBadge([])
    await waitFor(() => expect(screen.getByText('Right now')).toBeTruthy())
    expect(screen.queryByText('2')).toBeNull()

    mountBadge('error')
    await waitFor(() => expect(screen.getAllByText('Waiting on you').length).toBeGreaterThan(0))
    expect(screen.queryByText('2')).toBeNull()
  })
})

describe('A new session surfaces the chat from under an ops overlay', () => {
  function mountCockpit(list: ListState<SessionListState>, initialScreen: 'now' | 'ask') {
    const spec = createNavScreenStore()
    // Seed the instance's state through its own factory contract: create(),
    // then write via actions before first read.
    const store = spec.create()
    if (initialScreen !== 'ask') store.actions.setScreen(initialScreen)
    const props = {
      useStore: bindStoreHook(store),
      actions: store.actions,
      useSessions: ((sel: (s: SessionListState) => unknown) =>
        useSyncExternalStore(list.subscribe, () => sel(list.getSnapshot()))) as SnapshotSelectorHook<SessionListState>,
    }
    render(<OpsCockpit {...props} />)
    return store
  }

  function fakeList(initialCurrent: string | undefined): ListState<SessionListState> & { setCurrent(c: string | undefined): void } {
    let state: SessionListState = {
      ids: [], byId: {}, current: initialCurrent,
      phase: 'ready' as SessionListState['phase'],
      subagentsByParent: {},
      breadcrumbs: undefined,
    } as unknown as SessionListState
    const listeners = new Set<() => void>()
    return {
      getSnapshot: () => state,
      subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } },
      setCurrent(next: string | undefined) {
        state = { ...state, current: next }
        act(() => { for (const fn of listeners) fn() })
      },
    }
  }

  it('routes back to ask when the current session changes while an ops screen is up', () => {
    const list = fakeList(undefined)
    const store = mountCockpit(list, 'now')
    list.setCurrent('s1')
    expect(store.getSnapshot().screen).toBe('ask')
  })

  it('does not fire on first mount, and ignores same-session refreshes', () => {
    const list = fakeList('s0')
    const store = mountCockpit(list, 'now')
    list.setCurrent('s0')
    expect(store.getSnapshot().screen).toBe('now')
    list.setCurrent('s1')
    expect(store.getSnapshot().screen).toBe('ask')
  })

  it('renders nothing on ask (chat shows through)', () => {
    const list = fakeList(undefined)
    const store = mountCockpit(list, 'ask')
    expect(store.getSnapshot().screen).toBe('ask')
    expect(document.querySelector('[data-slot-error]')).toBeNull()
  })
})
