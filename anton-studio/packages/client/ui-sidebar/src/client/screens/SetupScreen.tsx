import { useState } from 'react'
import type { CSSProperties } from 'react'
import bp from '../blueprint.module.css'

/**
 * README §11: "Steps: Pick the work → Connect it → Set the leash → Review
 * the plan." A step-0 "Connect your AI" precedes those: without a provider
 * key, Anton has nothing to draft automations with. It POSTs to
 * /api/wizard/providers (dashboard.py's save_provider_key) — that endpoint
 * already existed and already persisted a key to secrets.yaml, but nothing
 * in the UI ever called it and nothing on the backend ever read the saved
 * key back into the executor's environment (see anton/cli.py's
 * _load_secrets_into_env). Skippable: a fresh install still boots and the
 * rest of the wizard still works without a key, pi just fails cleanly on
 * its own until one is entered later (Add-ons, or re-running Set up).
 */
const STEPS = ['Connect your AI', 'Pick the work', 'Connect it', 'Set the leash', 'Review the plan']

type Provider = { id: string; label: string; keyHint: string; signupUrl: string }

const PROVIDERS: Provider[] = [
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
  const [provider, setProvider] = useState<string>('anthropic')
  const [apiKey, setApiKey] = useState('')
  const [keySaved, setKeySaved] = useState(false)

  const stepCards = step === 1 ? WORK : step === 2 ? SYSTEMS : step === 3 ? LEASH : []
  const stepPicked = stepCards.filter(c => picks.has(c.id)).length

  const advancePastConnectAi = () => {
    if (!apiKey.trim()) { setStep(1); return }
    fetch('/api/wizard/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key: apiKey.trim() }),
    }).then(() => { setKeySaved(true) })
      .catch(() => { /* Anton still boots; pi just fails cleanly until a key is saved */ })
      .finally(() => { setStep(1) })
  }

  const finish = () => {
    fetch('/api/setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step: 'review', picks: [...picks] }),
    }).catch(() => { /* the wizard still closes; nothing was picked up server-side */ })
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
    ? 'Anton drafts and runs automations through a model you bring the key for. Add one now, or skip and add it later from Add-ons — Anton still boots either way, it just can\'t do real work until a key is saved.'
    : step === 1
      ? 'Pick as many as you like — Anton drafts each one as a diagram you can review before anything runs.'
      : step === 2
        ? 'Name the systems Anton should watch and connect to. You can add more later from Add-ons.'
        : step === 3
          ? 'This sets the default — you can loosen or tighten it per automation later.'
          : picks.size === 0
            ? "You didn't pick anything to start with — that's fine, Anton still boots. Add automations any time from Add-ons or by re-running Set up."
            : `Anton will draft roughly ${picks.size} automation${picks.size === 1 ? '' : 's'} from what you picked, and wait for your OK before any of it runs.`

  const cardStyle = (active: boolean): CSSProperties => ({
    display: 'flex',
    gap: 10,
    padding: '12px 14px',
    cursor: 'pointer',
    border: `1px solid ${active ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`,
    background: active ? 'var(--dsw-alias-state-business-tertiary)' : 'transparent',
  })

  return (
    <div className={bp.blueprint} style={{ width: 'min(920px, 100%)', maxHeight: '100%', display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)', boxShadow: '0 12px 32px rgba(29,31,32,.22)' }}>
      <span className={`${bp.corner} ${bp.cornerTl}`} />
      <span className={`${bp.corner} ${bp.cornerTr}`} />
      <span className={`${bp.corner} ${bp.cornerBl}`} />
      <span className={`${bp.corner} ${bp.cornerBr}`} />

      <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 12, padding: '20px 24px', borderBottom: '1px solid var(--dsw-alias-border-l2)' }}>
        <img src="/anton_logo.jpg" alt="" style={{ width: 22, height: 22, flex: 'none' }} />
        <div style={{ minWidth: 0 }}>
          <div className={bp.screenTitle} style={{ fontSize: 21 }}>Set up Anton</div>
          <div className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>Step {step + 1} of {STEPS.length} · about four minutes</div>
        </div>
      </div>

      <div style={{ flex: 'none', display: 'flex', gap: 1, background: 'var(--dsw-alias-border-l2)', margin: '18px 24px 0' }}>
        {STEPS.map((s, i) => (
          <div key={s} style={{ flex: 1, padding: '9px 12px', background: i === step ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-bg-base)' }}>
            <div className={bp.kicker} style={{ margin: 0, color: i === step ? 'var(--dsw-alias-bg-base)' : 'var(--dsw-alias-label-secondary)' }}>STEP {i + 1}</div>
            <div style={{ fontSize: 12.5, fontWeight: 500, color: i === step ? 'var(--dsw-alias-bg-base)' : 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>{s}</div>
          </div>
        ))}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '28px 24px' }}>
        <div className={bp.screenTitle} style={{ fontSize: 24, marginBottom: 8 }}>{question}</div>
        <div style={{ fontSize: 13.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)', maxWidth: '70ch', marginBottom: step < 4 ? 22 : 0 }}>{paragraph}</div>

        {step === 0 && (
          <div style={{ maxWidth: 420 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 16 }}>
              {PROVIDERS.map((p) => {
                const active = provider === p.id
                return (
                  <div key={p.id} onClick={() => { setProvider(p.id) }} style={cardStyle(active)}>
                    <div style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{p.label}</div>
                  </div>
                )
              })}
            </div>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => { setApiKey(e.target.value); setKeySaved(false) }}
              placeholder={PROVIDERS.find(p => p.id === provider)?.keyHint ?? 'API key'}
              style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', fontSize: 13.5, fontFamily: 'inherit', border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)' }}
            />
            <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 8, lineHeight: 1.5 }}>
              Don't have one? <a href={PROVIDERS.find(p => p.id === provider)?.signupUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--dsw-alias-state-business-primary)' }}>Get a {PROVIDERS.find(p => p.id === provider)?.label} key</a> — this is billed by {PROVIDERS.find(p => p.id === provider)?.label} based on how much Anton actually uses, typically a few dollars a month for one small business. Anton never sees this bill directly; check the provider's own dashboard for usage and spending limits.
            </div>
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
