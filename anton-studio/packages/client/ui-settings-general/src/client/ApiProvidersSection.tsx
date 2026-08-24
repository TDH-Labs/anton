import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'

type Provider = { id: string; label: string; keyHint?: string; signupUrl?: string; baseUrl?: string; defaultModel?: string; custom?: boolean }

const FALLBACK: Provider[] = ['openai', 'anthropic', 'gemini', 'deepseek'].map((id) => ({ id, label: id }))

/**
 * Settings "API providers". Self-contained (the slot system passes no props):
 * renders every provider from the backend's /api/wizard/catalog — the same
 * source the first-run wizard uses, so the lists can never drift apart.
 * Supports all executor-known providers plus custom OpenAI-compatible
 * endpoints. Each provider card unifies what used to be split across two
 * tabs: key entry, a "Load models" action (same /api/wizard/models flow as
 * the first-run wizard's Connect-AI step), and an inline model picker whose
 * pick rides along in the save call (persisted as routes.cloud_model).
 * Below the cards, one combined "Available models" list aggregates every
 * loaded provider, each row labeled with its provider. Shows which keys are
 * already stored without ever echoing secrets back.
 */
export function ApiProvidersSection() {
  const [providers, setProviders] = useState<Provider[]>(FALLBACK)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [haveKey, setHaveKey] = useState<Record<string, boolean>>({})
  const [cloudModel, setCloudModel] = useState('')
  const [modelsByProvider, setModelsByProvider] = useState<Record<string, string[]>>({})
  const [pickedModel, setPickedModel] = useState<Record<string, string>>({})
  const [errorsByProvider, setErrorsByProvider] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [flash, setFlash] = useState('')

  const refreshStatus = () => {
    fetch('/api/wizard/keys')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.have_key) setHaveKey(d.have_key)
        if (typeof d?.cloud_model === 'string') setCloudModel(d.cloud_model)
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
    const base = p.custom ? (drafts['custom:base_url'] ?? '').trim() : ''
    setBusy(p.id)
    // POST (not the deprecated GET): the fresh key rides in the body, never
    // in URLs/logs; an empty body key makes the backend fall back to the
    // already-saved key, so "Load models" works for stored keys too.
    fetch('/api/wizard/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: p.id, key: (drafts[p.id] ?? '').trim(), base_url: base }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        setModelsByProvider((m) => ({ ...m, [p.id]: d.models ?? [] }))
        setErrorsByProvider((e) => ({ ...e, [p.id]: d.error ?? '' }))
        // Prefill rule: keep an explicit pick; else the provider's slice of
        // the already-saved routes.cloud_model (e.g. "anthropic/claude-…");
        // else the catalog's default model, else the first listed one.
        const models: string[] = d.models ?? []
        if (models.length > 0) {
          const saved = cloudModel.startsWith(`${p.id}/`) ? cloudModel.slice(p.id.length + 1) : ''
          const preferred = p.defaultModel ?? ''
          setPickedModel((sel: Record<string, string>) => {
            const cur = sel[p.id] ?? ''
            const keep = cur !== '' && models.includes(cur) ? cur : ''
            const fallback = (saved && models.includes(saved) ? saved : '')
              || (preferred && models.includes(preferred) ? preferred : '')
              || (models[0] ?? '')
            return { ...sel, [p.id]: keep || fallback }
          })
        }
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
    const model = (pickedModel[p.id] ?? '').trim()
    if (model) body.model = model
    setBusy(p.id)
    fetch('/api/wizard/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => {
        if (r.ok) {
          setFlash(model ? `${p.label} key saved · default model ${model}.` : `${p.label} key saved.`)
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

  // One combined view across every provider whose models have been loaded.
  const availableModels = providers.flatMap((p) =>
    (modelsByProvider[p.id] ?? []).map((m) => ({ id: `${p.id}/${m}`, provider: p.label, model: m })))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
        Configure API keys for the providers Anton supports. Enter a key, load its models, and pick the default — all in one place.
        {cloudModel && <> Current default model: <strong>{cloudModel}</strong>.</>}
      </p>
      {providers.map((p) => {
        const models = modelsByProvider[p.id] ?? []
        return (
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
              placeholder={haveKey[p.id] ? 'Saved — enter a new key to replace' : (p.keyHint ?? `Enter ${p.label} key…`)}
              style={inputStyle}
            />
            {models.length > 0 && (
              <select
                aria-label={`${p.label} model`}
                value={pickedModel[p.id] ?? ''}
                onChange={(e) => setPickedModel((sel) => ({ ...sel, [p.id]: e.target.value }))}
                style={inputStyle}
              >
                {!pickedModel[p.id] && <option value="">Pick a model…</option>}
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}{`${p.id}/${m}` === cloudModel ? ' · current default' : ''}
                  </option>
                ))}
              </select>
            )}
            {models.length > 0 && (
              <span style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                {models.length} models available for this key
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
                  Save key{pickedModel[p.id] ? ' + model' : ''}
                </button>
              )}
            </div>
          </div>
        )
      })}
      {flash && <span style={{ fontSize: 12.5, color: 'var(--dsw-alias-state-success-primary)' }}>{flash}</span>}
      {availableModels.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
          <label style={{ fontWeight: 500 }}>
            Available models
            {' '}
            <span style={{ fontSize: 11.5, fontWeight: 400, color: 'var(--text-secondary)' }}>
              · across all configured providers ({availableModels.length})
            </span>
          </label>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            {availableModels.map(({ id, provider, model }) => (
              <div key={id} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 12.5, color: 'var(--dsw-alias-label-primary)' }}>
                <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>{model}</span>
                <span style={{
                  flex: 'none', fontSize: 10.5, padding: '1px 6px',
                  border: '1px solid var(--dsw-alias-border-l2)', borderRadius: 999,
                  color: 'var(--dsw-alias-label-secondary)',
                }}
                  >
                  {provider}
                </span>
                {id === cloudModel && (
                  <span style={{ fontSize: 10.5, color: 'var(--dsw-alias-state-success-primary)' }}>· default</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
