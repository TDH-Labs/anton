// @vitest-environment jsdom
/** Add-ons search box (ConnectionsCatalog): typing must filter the visible
 * connector cards by name/what/category, case-insensitively, and clearing
 * the input restores the full list. Guards the "search does nothing" bug. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConnectionsCatalog } from '../src/client/screens/ConnectionsCatalog.tsx'

const CATALOG = [
  { id: 'github', name: 'GitHub', category: 'developer', transport: 'remote-http', url: 'https://mcp.example/gh', auth: 'oauth', what: 'Repos, issues, PRs, CI runs' },
  { id: 'postgres', name: 'PostgreSQL', category: 'data', transport: 'stdio', auth: 'key', what: 'Read-only SQL against your database' },
  { id: 'quickbooks', name: 'QuickBooks', category: 'finance', transport: 'bridge', bridge: 'composio', auth: 'oauth', what: 'Invoices, bills, payments' },
]

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

function mount() {
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(url.includes('/api/wizard/mcp') ? [] : { connections: CATALOG, bridges: {} }),
  })))
  return render(<ConnectionsCatalog />)
}

const type = (q: string) => {
  fireEvent.change(screen.getByPlaceholderText('Search connectors…'), { target: { value: q } })
}

describe('Add-ons connector search', () => {
  it('renders every catalog card before a query is typed', async () => {
    mount()
    await waitFor(() => expect(screen.getByText('GitHub')).toBeTruthy())
    expect(screen.getByText('PostgreSQL')).toBeTruthy()
    expect(screen.getByText('QuickBooks')).toBeTruthy()
  })

  it('filters by name, case-insensitively', async () => {
    mount()
    await waitFor(() => expect(screen.getByText('GitHub')).toBeTruthy())
    type('GITHUB')
    expect(screen.queryByText('PostgreSQL')).toBeNull()
    expect(screen.queryByText('QuickBooks')).toBeNull()
    expect(screen.getByText('GitHub')).toBeTruthy()
  })

  it('filters by the what description and by category', async () => {
    mount()
    await waitFor(() => expect(screen.getByText('GitHub')).toBeTruthy())
    type('read-only')
    expect(screen.getByText('PostgreSQL')).toBeTruthy()
    expect(screen.queryByText('GitHub')).toBeNull()
    type('developer')
    expect(screen.getByText('GitHub')).toBeTruthy()
    expect(screen.queryByText('PostgreSQL')).toBeNull()
  })

  it('clears back to the full list when the input is emptied', async () => {
    mount()
    await waitFor(() => expect(screen.getByText('GitHub')).toBeTruthy())
    type('sql')
    expect(screen.queryByText('GitHub')).toBeNull()
    type('')
    expect(screen.getByText('GitHub')).toBeTruthy()
    expect(screen.getByText('PostgreSQL')).toBeTruthy()
    expect(screen.getByText('QuickBooks')).toBeTruthy()
  })
})
