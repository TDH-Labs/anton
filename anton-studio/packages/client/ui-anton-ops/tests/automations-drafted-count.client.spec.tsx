// @vitest-environment jsdom
/** The "N DRAFTED" kicker must count only automations still awaiting
 * approval, not every automation regardless of state -- guards a bug where
 * approving and turning on an automation left the header stuck at the
 * original total (GET /api/initiatives' full list length) forever. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { AutomationsScreen } from '../src/client/screens/AutomationsScreen.tsx'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const AUTOMATIONS = [
  {
    id: 'weekly-report', name: 'Weekly summary email', plain: 'Every Friday.',
    trigger: { kind: 'cron', display: 'Every Friday', expr: null },
    needsSignoff: true, author: 'agent', lastRun: null,
    state: 'running', risk: 'low', nodes: [], links: [],
  },
  {
    id: 'invoice-chase', name: 'Invoice chase', plain: 'Nudge overdue invoices.',
    trigger: { kind: 'cron', display: 'Daily', expr: null },
    needsSignoff: true, author: 'agent', lastRun: null,
    state: 'awaiting_approval', risk: 'low', nodes: [], links: [],
  },
  {
    id: 'built-by-hand', name: 'Built by hand', plain: 'A human-built n8n flow.',
    trigger: { kind: 'cron', display: 'Hourly', expr: null },
    needsSignoff: false, author: 'human', lastRun: null,
    state: 'running', risk: 'low', nodes: [], links: [],
  },
]

function mount() {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(
      url.includes('/api/initiatives') ? AUTOMATIONS
        : url.includes('/api/n8n/config') ? { base_url: null }
          : null,
    ),
  })))
  return render(<AutomationsScreen />)
}

describe('Automations header count', () => {
  it('counts only awaiting_approval rows as DRAFTED, not the whole list', async () => {
    mount()
    await waitFor(() => expect(screen.getByText('Weekly summary email')).toBeTruthy())
    // One of three rows is awaiting_approval; the other two (one running,
    // one already running-and-human-built) must not inflate the count.
    expect(screen.getByText('1 DRAFTED · 1 BUILT BY YOU')).toBeTruthy()
  })
})
