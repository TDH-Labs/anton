// @vitest-environment jsdom
/** The Add-ons hosted-OAuth bridges card: paste a Composio/Nango key, see
 * honest configured state, never render the key back after saving. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { AddonsScreen } from '../src/client/screens/AddonsScreen.tsx'

const calls: { url: string; init?: RequestInit | undefined }[] = []
let bridgesBody = { bridges: { composio: false, nango: false } }

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input)
    calls.push({ url, init })
    let body: unknown = {}
    if (url.includes('/api/integrations/bridges')) body = bridgesBody
    if (url.includes('/api/wizard/mcp')) body = []
    if (url === '/api/integrations/bridges/configure') {
      const parsed = JSON.parse(String(init?.body)) as { bridge: string }
      bridgesBody = { ...bridgesBody, bridges: { ...bridgesBody.bridges, [parsed.bridge]: true } }
      body = { bridge: parsed.bridge, configured: bridgesBody.bridges }
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
  }))
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); calls.length = 0; bridgesBody = { bridges: { composio: false, nango: false } } })

describe('Add-ons hosted-OAuth bridges card', () => {
  it('shows unconfigured state with a key field, saves, then shows CONFIGURED', async () => {
    stubFetch()
    render(<AddonsScreen />)
    await waitFor(() => expect(screen.getByText('Composio')).toBeTruthy())
    expect(screen.queryByText('CONFIGURED')).toBeNull()

    const inputs = screen.getAllByPlaceholderText('Paste API key…')
    expect(inputs.length).toBeGreaterThanOrEqual(1)
    fireEvent.change(inputs[0] as HTMLElement, { target: { value: 'ak_live_test' } })
    const saves = screen.getAllByText('Save')
    expect(saves.length).toBeGreaterThanOrEqual(1)
    fireEvent.click(saves[0] as HTMLElement)

    await waitFor(() => expect(screen.getByText('CONFIGURED')).toBeTruthy())
    const posted = calls.find((c) => c.url === '/api/integrations/bridges/configure')
    expect(posted).toBeTruthy()
    expect(JSON.parse(String(posted?.init?.body))).toEqual({ bridge: 'composio', key: 'ak_live_test' })
    // the key is never rendered back once saved
    await waitFor(() => expect(screen.getByPlaceholderText('Replace key…')).toBeTruthy())
    expect(screen.queryByDisplayValue('ak_live_test')).toBeNull()
  })
})
