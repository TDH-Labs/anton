// @vitest-environment jsdom
/** ConnectionsCatalog must fail loudly: when GET /api/connections/catalog
 * errors (e.g. the apiproxy's scoped credential 403ing before the machine-
 * token scopes were added), the grid shows an honest explanation instead of
 * silently rendering zero connectors. Guards the "empty Add-ons page" bug. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { ConnectionsCatalog } from '../src/client/screens/ConnectionsCatalog.tsx'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Add-ons catalog load failures surface honestly', () => {
  it('shows an error note when the catalog endpoint returns non-200', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/api/wizard/mcp')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
      return Promise.resolve({ ok: false, status: 403 })
    }))
    render(<ConnectionsCatalog />)
    await waitFor(() => expect(screen.getByText(/Couldn't load the connector catalog/i)).toBeTruthy())
    expect(screen.getByText(/No connectors to show/i)).toBeTruthy()
    // and no connector cards are rendered alongside the failure
    expect(screen.queryByText('GitHub')).toBeNull()
  })

  it('shows an error note when the catalog fetch rejects outright', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.includes('/api/wizard/mcp')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
      return Promise.reject(new TypeError('Failed to fetch'))
    }))
    render(<ConnectionsCatalog />)
    await waitFor(() => expect(screen.getByText(/No connectors to show/i)).toBeTruthy())
  })

  it('does not show the failure note once connectors loaded fine', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.includes('/api/wizard/mcp') ? [] : { connections: [{ id: 'github', name: 'GitHub', category: 'developer', transport: 'remote-http', url: 'https://mcp.example/gh', auth: 'oauth', what: 'Repos' }], bridges: {} }),
    })))
    render(<ConnectionsCatalog />)
    await waitFor(() => expect(screen.getByText('GitHub')).toBeTruthy())
    expect(screen.queryByText(/No connectors to show/i)).toBeNull()
  })
})
