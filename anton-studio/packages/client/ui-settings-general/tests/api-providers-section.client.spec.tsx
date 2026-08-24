// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiProvidersSection } from '../src/client/ApiProvidersSection.tsx'

/**
 * The unified API-providers section: each provider card carries key entry,
 * a Load-models action (POST /api/wizard/models), and an inline model
 * picker; below the cards a combined list aggregates every loaded provider,
 * rows labeled with their provider. All backend calls are mocked here —
 * this spec pins the UX contract, not the wire.
 */

const CATALOG = {
  providers: [
    { id: 'anthropic', label: 'Anthropic', defaultModel: 'claude-sonnet-4-5' },
    { id: 'openai', label: 'OpenAI' },
  ],
}

let posts: Array<{ url: string; body: unknown }>

function mockFetch() {
  posts = []
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
    if (url === '/api/wizard/catalog') return Promise.resolve(ok(CATALOG))
    if (url === '/api/wizard/keys') return Promise.resolve(ok({ have_key: { anthropic: true }, cloud_model: '' }))
    if (url === '/api/wizard/models' && init?.method === 'POST') {
      const req = JSON.parse(String(init.body)) as { provider: string }
      posts.push({ url, body: req })
      const models = req.provider === 'anthropic'
        ? ['claude-sonnet-4-5', 'claude-haiku-4-5']
        : ['gpt-5-mini']
      return Promise.resolve(ok({ models, error: null }))
    }
    if (url === '/api/wizard/providers') {
      posts.push({ url, body: JSON.parse(String(init?.body)) })
      return Promise.resolve(ok({ status: 'saved' }))
    }
    return Promise.reject(new Error(`unexpected fetch ${url}`))
  }))
}

beforeEach(() => {
  mockFetch()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ApiProvidersSection unified provider cards', () => {
  it('loads models per card into an inline picker and aggregates them below with provider labels', async () => {
    render(<ApiProvidersSection />)
    // Catalog arrived: one card per provider.
    await waitFor(() => { expect(screen.getByText('Anthropic')).toBeTruthy() })

    const loadButtons = await screen.findAllByRole('button', { name: 'Load models' })
    fireEvent.click(loadButtons[0]!)
    fireEvent.click(loadButtons[1]!)

    // Inline picker per card, prefilled with the catalog's preferred model.
    const picker = await screen.findByLabelText('Anthropic model') as HTMLSelectElement
    expect(picker.value).toBe('claude-sonnet-4-5')

    // Combined list: every loaded model, each row labeled with its provider.
    expect((await screen.findAllByText('claude-haiku-4-5')).length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('gpt-5-mini').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Available models')).toBeTruthy()
    expect(screen.getAllByText('Anthropic').length).toBeGreaterThanOrEqual(2) // card + combined row
    expect(screen.getAllByText('OpenAI').length).toBeGreaterThanOrEqual(2)

    // Models load via POST so fresh keys never ride in URLs/logs.
    const modelPosts = posts.filter((p) => p.url === '/api/wizard/models')
    expect(modelPosts).toHaveLength(2)
    expect(modelPosts[0]).toMatchObject({ body: { provider: 'anthropic' } })
  })

  it('rides the picked model along when saving the key', async () => {
    render(<ApiProvidersSection />)
    await waitFor(() => { expect(screen.getByText('Anthropic')).toBeTruthy() })

    const keyInput = screen.getByPlaceholderText(/enter a new key to replace/i)
    fireEvent.change(keyInput, { target: { value: 'sk-ant-test' } })

    const loadButton = screen.getAllByRole('button', { name: 'Load models' })[0]!
    fireEvent.click(loadButton)
    await screen.findByLabelText('Anthropic model')

    const saveButton = await screen.findByRole('button', { name: /save key \+ model/i })
    fireEvent.click(saveButton)

    await waitFor(() => {
      const savePost = posts.find((p) => p.url === '/api/wizard/providers')
      expect(savePost).toEqual({
        url: '/api/wizard/providers',
        body: { provider: 'anthropic', key: 'sk-ant-test', model: 'claude-sonnet-4-5' },
      })
    })
  })

  it('marks the current default model in both the picker and the combined list', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input)
      const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
      if (url === '/api/wizard/catalog') return Promise.resolve(ok(CATALOG))
      if (url === '/api/wizard/keys') return Promise.resolve(ok({ have_key: {}, cloud_model: 'anthropic/claude-haiku-4-5' }))
      if (url === '/api/wizard/models') return Promise.resolve(ok({ models: ['claude-sonnet-4-5', 'claude-haiku-4-5'], error: null }))
      return Promise.reject(new Error(`unexpected fetch ${url}`))
    }))

    render(<ApiProvidersSection />)
    await waitFor(() => { expect(screen.getByText('Anthropic')).toBeTruthy() })
    fireEvent.click((await screen.findAllByRole('button', { name: 'Load models' }))[0]!)

    const option = await screen.findByRole('option', { name: 'claude-haiku-4-5 · current default' }) as HTMLOptionElement
    expect(option.selected).toBe(true)
    await screen.findByText('Available models')
    expect(screen.getByText('· default')).toBeTruthy()
  })
})
