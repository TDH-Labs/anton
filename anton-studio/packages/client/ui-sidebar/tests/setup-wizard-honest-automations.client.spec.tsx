// @vitest-environment jsdom
/** diagnose:setup-automations fixes, pinned client-side:
 * 1. Step-1 suggestions come from GET /api/wizard/work-catalog (backend-
 *    served, categorized well beyond accounting), with a trimmed generic
 *    fallback only when that fetch fails.
 * 2. The step-1 "Describe it" box goes through the real draft endpoint
 *    (POST /api/automations/draft) and saves via PUT /api/automations/:id
 *    with state awaiting_approval — never running.
 * 3. finish() hands picks to POST /api/setup, which materializes them as
 *    awaiting_approval drafts server-side; the wizard never fabricates
 *    finished rows or a lastRun.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SetupScreen } from '../src/client/screens/SetupScreen.tsx'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const PROVIDERS = { providers: [{ id: 'anthropic', label: 'Anthropic' }] }
const WORK_CATALOG = {
  categories: [
    {
      id: 'marketing', label: 'Marketing', cards: [
        { id: 'newsletter-draft', label: 'Monthly newsletter', sub: "Assembles a draft from the month's highlights" },
      ],
    },
    {
      id: 'it-dev', label: 'IT & dev', cards: [
        { id: 'backup-check', label: 'Backup check', sub: "Confirms last night's backups actually finished" },
      ],
    },
  ],
}

type Call = { url: string; init?: RequestInit }
type Handler = (url: string) => Record<string, unknown> | undefined

function stubFetch(handlers: Handler[]): Call[] {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn((url: string | URL | Request, init?: RequestInit) => {
    const u = typeof url === 'string' ? url : url instanceof URL ? url.toString() : url.url
    calls.push({ url: u, init })
    for (const h of handlers) {
      const res = h(u)
      if (res !== undefined) return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(res) })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve(null) })
  }))
  return calls
}

const bodyOf = (init?: RequestInit): any =>
  typeof init?.body === 'string' && init.body.length > 0 ? JSON.parse(init.body) : {}

const okProviders = (): Handler =>
  (url) => (url.includes('/api/wizard/catalog') && !url.includes('work') ? PROVIDERS : undefined)

async function gotoStep1(handlers: Handler[]): Promise<Call[]> {
  const calls = stubFetch(handlers)
  render(<SetupScreen />)
  await waitFor(() => expect(screen.getByText(/What should Anton think with\?/)).toBeTruthy())
  fireEvent.click(screen.getByText('Skip for now'))
  await waitFor(() => expect(screen.getByText(/Pick as many as you like/)).toBeTruthy())
  return calls
}

describe('Setup wizard honest automations', () => {
  it('renders the backend work catalog on step 1 instead of the hardcoded accounting list', async () => {
    await gotoStep1([okProviders(), (url) => (url.includes('/api/wizard/work-catalog') ? WORK_CATALOG : undefined)])
    expect(screen.getByText('Monthly newsletter')).toBeTruthy()
    expect(screen.getByText('Backup check')).toBeTruthy()
    // no accounting-only hardcoded card survives when the backend answered
    expect(screen.queryByText('Follow up on unpaid bills')).toBeNull()
  })

  it('falls back to a trimmed generic list when the work catalog fetch fails', async () => {
    await gotoStep1([okProviders()]) // work-catalog hits the default 404 handler
    expect(screen.getByText('Weekly summary email')).toBeTruthy()
    expect(screen.queryByText('Monthly newsletter')).toBeNull()
  })

  it('"Describe it" drafts through /api/automations/draft and saves as awaiting_approval — never running, no lastRun', async () => {
    const calls = await gotoStep1([
      okProviders(),
      (url) => (url.includes('/api/wizard/work-catalog') ? WORK_CATALOG : undefined),
      (url) => {
        if (!url.includes('/api/automations/draft')) return undefined
        return {
          name: 'Morning digest',
          plain: 'A daily digest email of overnight highlights.',
          trigger: { kind: null, display: 'Every weekday at 7 AM', expr: null },
          steps: [{ text: 'Collect overnight highlights', assignee: 'agent' }],
          needsSignoff: true,
          state: 'awaiting_approval',
          author: 'agent',
        }
      },
    ])
    // type the description and request the draft
    fireEvent.change(screen.getByPlaceholderText(/Every weekday at 7 AM/), { target: { value: 'Email me a morning digest' } })
    fireEvent.click(screen.getByText('Draft it'))

    // reviewable card appears; nothing saved yet
    await waitFor(() => expect(screen.getByText('DRAFT — PENDING YOUR REVIEW')).toBeTruthy())
    expect(screen.getByText('Morning digest')).toBeTruthy()

    fireEvent.click(screen.getByText('Save for review'))
    await waitFor(() => expect(calls.some(c => c.url.includes('/api/automations/morning-digest'))).toBe(true))
    const put = calls.find(c => c.url.includes('/api/automations/morning-digest'))
    expect(put?.init?.method).toBe('PUT')
    const body = bodyOf(put?.init)
    expect(body.state).toBe('awaiting_approval')
    expect(body.state).not.toBe('running')
    expect(body.nodes?.length).toBeGreaterThan(0)
    expect(JSON.stringify(body)).not.toContain('lastRun')
  })

  it('finish() posts picked ids to /api/setup for server-side draft materialization', async () => {
    const calls = await gotoStep1([
      okProviders(),
      (url) => (url.includes('/api/wizard/work-catalog') ? WORK_CATALOG : undefined),
      (url) => {
        if (!url.includes('/api/setup')) return undefined
        return { status: 'recorded', picks: 1, drafted: 1, draftIds: ['backup-check'] }
      },
    ])

    fireEvent.click(screen.getByText('Backup check'))
    fireEvent.click(screen.getByText('Next — connect them'))
    fireEvent.click(screen.getByText('Next — connect them'))
    fireEvent.click(screen.getByText('Next — connect them'))
    expect(screen.getByText(/Drafted — waiting for your review\. Approve each one/)).toBeTruthy()
    fireEvent.click(screen.getByText('Go to Right now'))

    await waitFor(() => expect(calls.some(c => c.url.includes('/api/setup'))).toBe(true))
    const post = calls.find(c => c.url.includes('/api/setup'))
    expect(post?.init?.method).toBe('POST')
    expect(bodyOf(post?.init).picks).toEqual(['backup-check'])
  })
})
