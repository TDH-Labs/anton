import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'

type Provider = { id: string; label: string; keyHint?: string; signupUrl?: string; custom?: boolean }

const FALLBACK: Provider[] = ['openai', 'anthropic', 'gemini', 'deepseek'].map((id) => ({ id, label: id }))

/**
 * Settings "API providers". Self-contained (the slot system passes no props):
 * renders every provider from the backend's /api/wizard/catalog — the same
 * source the first-run wizard uses, so the lists can never drift apart.
 * Supports all executor-known providers plus custom OpenAI-compatible
 * endpoints, live-lists models per saved key, and shows which keys are
 * already stored without ever echoing secrets back.
 */
export function ApiProvidersSection() {
  const [providers, setProviders] = useState<Provider[]>(FALLBACK)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [haveKey, setHaveKey] = useState<Record<string, boolean>>({})
  const [cloudModel, setCloudModel] = useState('')
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, string[]>>({})
  const [errorsByProvider, setErrorsByProvider] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [flash, setFlash] = useState('')

  const refreshStatus = () => {
    fetch('/api/wizard/keys')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.have_key) setHaveKey(d.have_key)
        if (d?.cloud_model) setCloudModel(d.cloud_model)
      })
      .catch(() => { /* status is best-effort */ })
  }

  useEffect(() => {
    fetch('/api/wizard/catalog')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.providers?.length) setProviders(d.providers) })
      .catch(() => { /* fallback already set */ })
    refreshStatus()
  }, [])

  const loadModels = (p: Provider) => {
    const key = (drafts[p.id] ?? '').trim()
    const base = p.custom ? (drafts['custom:base_url'] ?? '').trim() : ''
    if (!key && !base) return
    setBusy(p.id)
    const qs = new URLSearchParams({ provider: p.id })
    if (key) qs.set('key', key)
    if (base) qs.set('base_url', base)
    fetch(`/api/wizard/models?${qs.toString()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        setModelsByProvider((m) => ({ ...m, [p.id]: d.models ?? [] }))
        setErrorsByProvider((e) => ({ ...e, [p.id]: d.error ?? '' }))
      })
      .catch((err) => setErrorsByProvider((e) => ({ ...e, [p.id]: String(err.message ?? err) })))
      .finally(() => setBusy(null))
  }

  const saveProvider = (p: Provider) => {
    const key = (drafts[p.id] ?? '').trim()
    if (!key) {
      setFlash(`${p.label}: nothing new to save.`)
      return
    }
    const body: Record<string, string> = { provider: p.id, key }
    const baseUrl = p.custom ? (drafts['custom:base_url'] ?? '').trim() : ''
    if (baseUrl) body.base_url = baseUrl
    setBusy(p.id)
    fetch('/api/wizard/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => {
        if (r.ok) {
          setFlash(`${p.label} key saved.`)
          refreshStatus()
        } else setFlash(`${p.label}: save failed (HTTP ${r.status}).`)
      })
      .catch(() => setFlash(`${p.label}: save failed.`))
      .finally(() => setBusy(null))
  }

  const inputStyle: CSSProperties = {
    width: '100%', boxSizing: 'border-box', padding: '9px 11px', fontSize: 13, fontFamily: 'inherit',
    border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)',
  }
  const btnStyle: CSSProperties = {
    alignSelf: 'flex-start', padding: '5px 12px', background: 'transparent',
    border: '1px solid var(--dsw-alias-border-l2)', color: 'var(--dsw-alias-label-primary)',
    fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
        Configure API keys for the providers Anton supports. Enter a key and load its models to see what it can use.
        {cloudModel && <> Current default model: <strong>{cloudModel}</strong>.</>}
      </p>
      {providers.map((p) => (
        <div key={p.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <label style={{ fontWeight: 500 }}>
            {p.label}
            {' '}
            {haveKey[p.id]
              ? <span style={{ fontSize: 11.5, color: 'var(--dsw-alias-state-success-primary)' }}>· key saved</span>
              : <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>· no key</span>}
          </label>
          {p.custom && (
            <input
              type="text"
              value={drafts['custom:base_url'] ?? ''}
              onChange={(e) => setDrafts((d) => ({ ...d, 'custom:base_url': e.target.value }))}
              placeholder="Base URL, e.g. http://192.168.1.10:11434/v1"
              style={inputStyle}
            />
          )}
          <input
            type="password"
            value={drafts[p.id] ?? ''}
            onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
            onBlur={() => loadModels(p)}
            placeholder={haveKey[p.id] ? 'Saved — enter a new key to replace' : (p.keyHint ?? `Enter ${p.label} key…`)}
            style={inputStyle}
          />
          {(modelsByProvider[p.id]?.length ?? 0) > 0 && (
            <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
              {modelsByProvider[p.id]!.length} models available for this key
            </span>
          )}
          {errorsByProvider[p.id] && (
            <span style={{ fontSize: 12, color: 'var(--dsw-alias-state-danger-primary, #c0392b)' }}>{errorsByProvider[p.id]}</span>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => loadModels(p)} disabled={busy === p.id} style={btnStyle}>
              {busy === p.id ? 'Working…' : 'Load models'}
            </button>
            {(drafts[p.id] ?? '').trim() && (
              <button onClick={() => saveProvider(p)} disabled={busy === p.id} style={{ ...btnStyle, borderColor: 'var(--dsw-alias-state-business-primary)' }}>
                Save key
              </button>
            )}
          </div>
        </div>
      ))}
      {flash && <span style={{ fontSize: 12.5, color: 'var(--dsw-alias-state-success-primary)' }}>{flash}</span>}
    </div>
  )
}
