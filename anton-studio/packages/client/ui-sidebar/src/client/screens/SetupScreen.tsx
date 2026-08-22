import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import bp from '../blueprint.module.css'

/**
 * README §11: "Steps: Pick the work → Connect it → Set the leash → Review
 * the plan." A step-0 "Connect your AI" precedes those: without a provider
 * key, Anton has nothing to draft automations with.
 *
 * The provider list comes from the backend's /api/wizard/catalog — the same
 * source the settings API-keys section renders from, so the two can never
 * drift apart again. After a key is entered, /api/wizard/models live-lists
 * what that key can actually use (errors shown inline, never silent).
 * Custom OpenAI-compatible endpoints (vLLM, Ollama, LiteLLM proxies) are
 * first-class: pick "Custom", give a base URL.
 */
type Provider = { id: string; label: string; keyHint?: string; signupUrl?: string; baseUrl?: string; custom?: boolean; defaultModel?: string }

// Rendered only until the backend catalog arrives (or if it fails to).
const FALLBACK_PROVIDERS: Provider[] = [
  { id: 'anthropic', label: 'Anthropic', keyHint: 'sk-ant-…', signupUrl: 'https://console.anthropic.com/settings/keys' },
  { id: 'openai', label: 'OpenAI', keyHint: 'sk-…', signupUrl: 'https://platform.openai.com/api-keys' },
  { id: 'deepseek', label: 'DeepSeek', keyHint: 'sk-…', signupUrl: 'https://platform.deepseek.com/api_keys' },
  { id: 'openrouter', label: 'OpenRouter', keyHint: 'sk-or-…', signupUrl: 'https://openrouter.ai/keys' },
]

type PickCard = { id: string; label: string; sub: string }

const WORK: PickCard[] = [
  { id: 'bill-followup', label: 'Follow up on unpaid bills', sub: 'Sends a reminder a few days before something is due' },
  { id: 'invoice-reconciler', label: 'Invoice reconciler', sub: 'Cross-checks purchase orders against what actually arrived' },
  { id: 'weekly-report', label: 'Weekly summary email', sub: 'Rounds up the week for whoever needs to see it' },
  { id: 'reorder-check', label: 'Reorder check', sub: 'Watches stock levels against lead times' },
  { id: 'vendor-payment', label: 'Vendor payment check', sub: 'Confirms nothing is past terms' },
  { id: 'appointment-reminders', label: 'Appointment reminders', sub: 'Nudges customers ahead of a booking' },
  { id: 'expense-sorting', label: 'Expense and receipt sorting', sub: 'Files things under the right category as they come in' },
  { id: 'renewal-checker', label: 'Renewal / expiry checker', sub: 'Flags anything due within 30 days' },
]

const SYSTEMS: PickCard[] = [
  { id: 'quickbooks', label: 'QuickBooks', sub: 'Invoices, bills, payments' },
  { id: 'slack', label: 'Slack', sub: 'Approval and status pings' },
  { id: 'google-calendar', label: 'Google Calendar', sub: 'Bookings and reminders' },
  { id: 'github', label: 'GitHub', sub: 'Repos, issues, CI runs' },
]

const LEASH: PickCard[] = [
  { id: 'low-risk-auto', label: 'Low-risk steps run on their own', sub: 'No sign-off unless something looks off' },
  { id: 'medium-risk-ask', label: 'Medium and high risk always ask first', sub: 'Anton drafts, you approve before anything runs' },
  { id: 'notify-slack', label: 'Notify the team channel on every gate', sub: 'In addition to the Waiting on you inbox' },
]

const inputStyle: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '10px 12px', fontSize: 13.5, fontFamily: 'inherit',
  border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)',
}

/**
 * First-run wizard (README §11): a true full-viewport modal, not a routed
 * screen — the backdrop and dialog frame live in the caller (OpsCockpit),
 * this component is the dialog's own content. `onExit` leaves the wizard
 * (either "Do this later" or the final "Go to Right now") and routes to the
 * Right now screen.
 */
export function SetupScreen({ onExit }: { onExit?: () => void } = {}) {
  const [step, setStep] = useState(0)
  const [picks, setPicks] = useState<Set<string>>(new Set())
  const [providers, setProviders] = useState<Provider[]>(FALLBACK_PROVIDERS)
  const [provider, setProvider] = useState<string>('anthropic')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [modelError, setModelError] = useState<string | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [keySaved, setKeySaved] = useState(false)

  useEffect(() => {
    // Single source of truth: the same backend catalog the settings page
    // renders from, so wizard and settings can never drift apart again.
    fetch('/api/wizard/catalog')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.providers?.length) setProviders(d.providers) })
      .catch(() => { /* fallback list already set */ })
  }, [])

  const activeProvider = providers.find(p => p.id === provider)

  const loadModels = () => {
    if (!apiKey.trim()) return
    setLoadingModels(true)
    setModelError(null)
    const qs = new URLSearchParams({ provider, key: apiKey.trim() })
    if (provider === 'custom' && baseUrl.trim()) qs.set('base_url', baseUrl.trim())
    fetch(`/api/wizard/models?${qs.toString()}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        setModels(d.models ?? [])
        setModelError(d.error ?? null)
        if (d.models?.length && !model) {
          const preferred = activeProvider?.defaultModel
          setModel(preferred && d.models.includes(preferred) ? preferred : d.models[0])
        }
      })
      .catch((e) => setModelError(String(e.message ?? e)))
      .finally(() => setLoadingModels(false))
  }

  const stepCards = step === 1 ? WORK : step === 2 ? SYSTEMS : step === 3 ? LEASH : []
  const stepPicked = stepCards.filter(c => picks.has(c.id)).length

  const advancePastConnectAi = () => {
    if (!apiKey.trim()) { setStep(1); return }
    fetch('/api/wizard/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key: apiKey.trim(), base_url: baseUrl.trim(), model: model.trim() }),
    }).then((r) => { setKeySaved(r.ok) })
      .catch(() => { /* Anton still boots; pi just fails cleanly until a key is saved */ })
      .finally(() => { setStep(1) })
  }

  const finish = () => {
    fetch('/api/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: 'review', picks: [...picks] }),
    }).catch(() => { /* the wizard still closes */ })
      .finally(() => { onExit?.() })
  }

  const togglePick = (id: string) => {
    setPicks((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const question = step === 0
    ? 'What should Anton think with?'
    : step === 1
      ? 'What should Anton pick up first?'
      : step === 2
        ? 'What should Anton connect to?'
        : step === 3
          ? 'How much rope should Anton have?'
          : 'Here is the plan.'

  const paragraph = step === 0
    ? 'Anton drafts and runs automations through a model you bring the key for. Enter a key, then load the models it can use and pick one. Or skip and add it later from Settings — Anton still boots either way, it just can\'t do real work until a key is saved.'
    : step === 1
      ? 'Pick as many as you like — Anton drafts each one as a diagram you can review before anything runs.'
      : step === 2
        ? 'Name the systems Anton should watch and connect to. You can add more later from Add-ons.'
        : step === 3
          ? 'This sets the default — you can loosen or tighten it per automation later.'
          : picks.size === 0
            ? "You didn't pick anything to start with — that's fine, Anton still boots. Add automations any time from Add-ons or by re-running Set up."
            : `Anton will draft roughly ${picks.size} automation${picks.size === 1 ? '' : 's'} from what you picked, and wait for your OK before any of it runs.`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '28px 24px 12px' }}>
        <div className={bp.screenTitle} style={{ fontSize: 24, marginBottom: 8 }}>{question}</div>
        <div style={{ fontSize: 13.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)', maxWidth: '70ch', marginBottom: step < 4 ? 22 : 0 }}>{paragraph}</div>

        {step === 0 && (
          <div style={{ maxWidth: 460 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 16 }}>
              {providers.map((p) => {
                const active = provider === p.id
                return (
                  <div key={p.id} onClick={() => { setProvider(p.id); setModels([]); setModel(''); setModelError(null) }} style={cardStyle(active)}>
                    <div style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{p.label}</div>
                  </div>
                )
              })}
            </div>
            {activeProvider?.custom && (
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => { setBaseUrl(e.target.value); setModels([]); setModel('') }}
                placeholder="Base URL, e.g. http://192.168.1.10:11434/v1"
                style={{ ...inputStyle, marginBottom: 10 }}
              />
            )}
            <input
              type="password"
              value={apiKey}
              onChange={(e) => { setApiKey(e.target.value); setKeySaved(false) }}
              onBlur={() => { if (!activeProvider?.custom || baseUrl.trim()) loadModels() }}
              placeholder={activeProvider?.keyHint ?? 'API key'}
              style={inputStyle}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}>
              <button
                onClick={loadModels}
                disabled={!apiKey.trim() || loadingModels || (provider === 'custom' && !baseUrl.trim())}
                style={{ padding: '7px 14px', background: 'transparent', border: '1px solid var(--dsw-alias-border-l2)', color: 'var(--dsw-alias-label-primary)', fontSize: 12.5, cursor: 'pointer', fontFamily: 'inherit' }}
              >
                {loadingModels ? 'Loading…' : 'Load models'}
              </button>
              {models.length > 0 && <span style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>{models.length} models available</span>}
            </div>
            {modelError && (
              <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-danger-primary, #c0392b)', marginTop: 8, lineHeight: 1.45 }}>{modelError}</div>
            )}
            {!modelError && models.length > 0 && (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                style={{ ...inputStyle, marginTop: 10 }}
              >
                {!model && <option value="">Pick a model…</option>}
                {models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            )}
            {(models.length === 0 || model) && (
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="Model id (optional — e.g. claude-sonnet-4-5)"
                style={{ ...inputStyle, marginTop: 10 }}
              />
            )}
            {activeProvider?.signupUrl && (
              <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 8, lineHeight: 1.5 }}>
                Don't have one? <a href={activeProvider.signupUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--dsw-alias-state-business-primary)' }}>Get a {activeProvider.label} key</a> — this is billed by {activeProvider.label} based on how much Anton actually uses, typically a few dollars a month for one small business. Anton never sees this bill directly; check the provider's own dashboard for usage and spending limits.
              </div>
            )}
            {keySaved && <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-success-primary)', marginTop: 8 }}>Saved.</div>}
          </div>
        )}

        {step >= 1 && step < 4 && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {stepCards.map((c) => {
              const active = picks.has(c.id)
              return (
                <div key={c.id} onClick={() => { togglePick(c.id) }} style={cardStyle(active)}>
                  <span style={{
                    flex: 'none', width: 17, height: 17, marginTop: 1,
                    border: `1px solid ${active ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`,
                    background: active ? 'var(--dsw-alias-state-business-primary)' : 'transparent',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                  >
                    {active && <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--dsw-alias-bg-base)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{c.label}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>{c.sub}</div>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
            {[...picks].map((id) => {
              const card = [...WORK, ...SYSTEMS, ...LEASH].find(c => c.id === id)
              if (card === undefined) return null
              return (
                <div key={id} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 13, color: 'var(--dsw-alias-label-primary)' }}>
                  <span className={bp.mono} style={{ color: 'var(--dsw-alias-state-success-primary)' }}>+</span>
                  {card.label}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 14, padding: '16px 24px', borderTop: '1px solid var(--dsw-alias-border-l2)' }}>
        {step >= 1 && step < 4 && (
          <span className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>
            {stepPicked} of {stepCards.length} picked
            {step === 1 && ` · Anton will draft roughly ${Math.max(stepPicked, 0)} automation${stepPicked === 1 ? '' : 's'}`}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {step === 0 && (
          <button
            onClick={onExit}
            style={{ padding: '9px 4px', background: 'none', border: 'none', color: 'var(--dsw-alias-label-secondary)', fontSize: 13, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit' }}
          >
            Do this later
          </button>
        )}
        {step > 0 && (
          <button
            onClick={() => { setStep(s => s - 1) }}
            style={{ padding: '9px 18px', background: 'transparent', border: '1px solid var(--dsw-alias-border-l2)', color: 'var(--dsw-alias-label-primary)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            ← Back
          </button>
        )}
        {step === 0 ? (
          <button
            onClick={advancePastConnectAi}
            style={{ padding: '9px 18px', background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            {apiKey.trim() ? 'Save and continue' : 'Skip for now'}
          </button>
        ) : step < 4 ? (
          <button
            onClick={() => { setStep(s => s + 1) }}
            style={{ padding: '9px 18px', background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            Next — connect them
          </button>
        ) : (
          <button
            onClick={finish}
            style={{ padding: '9px 18px', background: 'var(--dsw-alias-state-success-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}
          >
            Go to Right now
          </button>
        )}
      </div>
    </div>
  )
}

function cardStyle(active: boolean): CSSProperties {
  return {
    display: 'flex', flexDirection: 'row', gap: 9, padding: '11px 13px', cursor: 'pointer',
    borderRadius: 8,
    border: `1px solid ${active ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`,
    background: active ? 'var(--dsw-alias-bg-raised, rgba(0,0,0,0.03))' : 'transparent',
  }
}
