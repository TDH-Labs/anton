// @vitest-environment jsdom
/** The "Finished today" stream must render honestly: a green success check
 * only ever means exit 0. Failures get an error-colored X and skips (provider
 * prerequisite unmet — the old exit-1-per-cron-tick spam) a warn-colored dash.
 * Guards the "failures looked like successes with '(exit 1)' appended" bug. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSyncExternalStore } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { createNavScreenStore } from '../src/client/nav-store.ts'
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots'

function bindStoreHook<T>(instance: { getSnapshot: () => T; subscribe: (fn: () => void) => () => void }) {
  return ((sel: unknown) => useSyncExternalStore(instance.subscribe, () =>
    (sel as (s: T) => unknown)(instance.getSnapshot()))) as never
}
import { OpsNowScreen } from '../src/client/OpsNowScreen.tsx'

const today = new Date().toISOString().slice(0, 10)

function stubWorklog(done: { text: string; meta: string; status?: string }[]) {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
    ok: true,
    json: () => {
      if (url.includes('/api/agent/worklog')) return Promise.resolve({ ongoing: [], done })
      if (url.includes('/api/systems')) return Promise.resolve([])
      return Promise.resolve([]) // /api/approvals
    },
  })))
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('worklog rows are styled by honest status', () => {
  it('renders ok, fail, and skipped rows with distinct icons', async () => {
    stubWorklog([
      { text: 'ok-job (ok)', meta: '10:00', status: 'ok' },
      { text: 'fail-job (exit 1)', meta: '10:05', status: 'fail' },
      { text: 'skip-job (skipped (no provider))', meta: '10:10', status: 'skipped' },
    ])
    const store = createNavScreenStore().create()
    const props: PropsStore<ReturnType<typeof createNavScreenStore>> = {
      useStore: bindStoreHook(store),
      actions: store.actions,
    }
    render(<OpsNowScreen {...props} />)
    await waitFor(() => expect(screen.getByText('fail-job (exit 1)')).toBeTruthy())
    const rowIcon = (label: string) =>
      screen.getByText(label).closest('div')?.querySelector('svg')?.getAttribute('stroke')
    const okColor = rowIcon('ok-job (ok)')
    expect(okColor).toContain('--dsw-alias-state-success-primary')
    expect(rowIcon('fail-job (exit 1)')).toContain('--dsw-alias-state-error-primary')
    // skip is neither green nor red — warn styling, never a checkmark
    expect(rowIcon('skip-job (skipped (no provider))')).toContain('--dsw-alias-state-warn-label')
    expect(rowIcon('skip-job (skipped (no provider))')).not.toBe(okColor)
  })

  it('treats legacy rows without status as successes (back-compat)', async () => {
    stubWorklog([{ text: 'legacy-job (ok)', meta: `${today}T09:00` }])
    const store = createNavScreenStore().create()
    const props: PropsStore<ReturnType<typeof createNavScreenStore>> = {
      useStore: bindStoreHook(store),
      actions: store.actions,
    }
    render(<OpsNowScreen {...props} />)
    await waitFor(() => expect(screen.getByText('legacy-job (ok)')).toBeTruthy())
    const stroke = screen.getByText('legacy-job (ok)').closest('div')
      ?.querySelector('svg')?.getAttribute('stroke')
    expect(stroke).toContain('--dsw-alias-state-success-primary')
  })
})
