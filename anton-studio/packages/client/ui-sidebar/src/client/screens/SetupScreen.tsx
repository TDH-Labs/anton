import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import bp from '../blueprint.module.css'
import { draftToNodes, slugify, type AutomationDraft } from './automationDraft.ts'

/**
 * README §11: "Steps: Pick the work → Connect it → Set the leash → Review
 * the plan." A step-0 "Connect your AI" precedes those: without a provider
 * key, Anton has nothing to draft automations with.
 *
 * The provider list comes from the backend's /api/wizard/catalog and the
 * step-1 suggestion cards from /api/wizard/work-catalog — both backend-
 * served single sources of truth, each with a trimmed client fallback only
 * until/unless the fetch fails (diagnose:setup-automations).
 *
 * Honesty contract: picks and described drafts never become finished rows.
 * Picks are materialized server-side by POST /api/setup as awaiting_approval
 * drafts; a "Describe it" draft is reviewed here, then saved through the same
 * PUT /api/automations/:id path AutomationsScreen uses — state stays
 * awaiting_approval, lastRun stays null, and nothing runs until you approve
 * it in Automations.
 */
type Provider = { id: string; label: string; keyHint?: string; signupUrl?: string; baseUrl?: string; custom?: boolean; defaultModel?: string }

type PickCard = { id: string; label: string; sub: string }
type WorkCategory = { id: string; label: string; cards: PickCard[] }

// Rendered only until the backend catalog arrives (or if it fails to).
const FALLBACK_PROVIDERS: Provider[] = [
  { id: 'anthropic', label: 'Anthropic', keyHint: 'sk-ant-…', signupUrl: 'https://console.anthropic.com/settings/keys' },
  { id: 'openai', label: 'OpenAI', keyHint: 'sk-…', signupUrl: 'https://platform.openai.com/api-keys' },
  { id: 'deepseek', label: 'DeepSeek', keyHint: 'sk-…', signupUrl: 'https://platform.deepseek.com/api_keys' },
  { id: 'openrouter', label: 'OpenRouter', keyHint: 'sk-or-…', signupUrl: 'https://openrouter.ai/keys' },
]

// Rendered only until the backend catalog arrives (or if it fails to).
const FALLBACK_WORK: WorkCategory[] = [
  {
    id: 'suggestions', label: 'Suggestions', cards: [
      { id: 'weekly-report', label: 'Weekly summary email', sub: 'Rounds up the week for whoever needs to see it' },
      { id: 'appointment-reminders', label: 'Appointment reminders', sub: 'Nudges customers ahead of a booking' },
      { id: 'inbox-triage', label: 'Inbox triage', sub: 'Flags the messages that actually need a reply' },
      { id: 'renewal-checker', label: 'Renewal / expiry checker', sub: 'Flags anything due within 30 days' },
      { id: 'backup-check', label: 'Backup check', sub: "Confirms last night's backups actually finished" },
      { id: 'doc-filing', label: 'Document filing', sub: 'Files new documents and notes where everything landed' },
    ],
  },
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
  const [workCats, setWorkCats] = useState<WorkCategory[]>(FALLBACK_WORK)
  const [provider, setProvider] = useState<string>('anthropic')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [model, setModel] = useState('')
  const [modelError, setModelError] = useState<string | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [keySaved, setKeySaved] = useState(false)
  // Step-1 "Describe it": plain English -> POST /api/automations/draft -> a
  // reviewable card -> saved via PUT /api/automations/:id as awaiting_approval.
  const [description, setDescription] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState<string | null>(null)
  const [draft, setDraft] = useState<AutomationDraft | null>(null)
  const [savingDraft, setSavingDraft] = useState(false)
  const [draftedNames, setDraftedNames] = useState<{ id: string; name: string }[]>([])

  useEffect(() => {
    // Single source of truth: the same backend catalog the settings page
    // renders from, so wizard and settings can never drift apart again.
    fetch('/api/wizard/catalog')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.providers?.length) setProviders(d.providers) })
      .catch(() => { /* fallback list already set */ })
    fetch('/api/wizard/work-catalog')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (Array.isArray(d?.categories) && d.categories.length > 0) {
          setWorkCats(d.categories as WorkCategory[])
        }
      })
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

  const workCards = workCats.flatMap(c => c.cards)
  const allKnownCards = [...workCards, ...SYSTEMS, ...LEASH]
  const stepCards = step === 2 ? SYSTEMS : step === 3 ? LEASH : []
  const workPicked = workCards.filter(c => picks.has(c.id)).length
  const stepPicked = step === 1 ? workPicked : stepCards.filter(c => picks.has(c.id)).length
  const stepTotal = step === 1 ? workCards.length : stepCards.length

  const requestDraft = () => {
    if (!description.trim() || drafting) return
    setDrafting(true)
    setDraftError(null)
    fetch('/api/automations/draft', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: description.trim() }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}`)
        return r.json() as Promise<AutomationDraft>
      })
      .then((d) => { setDescription(''); setDraft(d) })
      .catch(() => setDraftError("Anton couldn't finish that draft — you can still pick cards above and try again later."))
      .finally(() => setDrafting(false))
  }

  const saveDraft = () => {
    if (draft === null || savingDraft) return
    const current = draft
    const id = slugify(current.name)
    const { nodes, links } = draftToNodes(current)
    setSavingDraft(true)
    // Same persistence path as AutomationsScreen.confirmDraft: the row files
    // as awaiting_approval with no lastRun — activation stays a separate,
    // explicit act in Automations.
    fetch(`/api/automations/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: current.name, plain: current.plain, nodes, links, state: 'awaiting_approval' }),
    })
      .then(() => {
        setDraftedNames(prev => (prev.some(p => p.id === id) ? prev : [...prev, { id, name: current.name }]))
        setDraft(null)
      })
      .finally(() => setSavingDraft(false))
  }

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
    // POST /api/setup records the picks AND materializes each one server-side
    // as an awaiting_approval draft (never running, lastRun null). The wizard
    // itself never fabricates finished rows.
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

  const totalDrafted = picks.size + draftedNames.length
  const paragraph = step === 0
    ? 'Anton drafts and runs automations through a model you bring the key for. Enter a key, then load the models it can use and pick one. Or skip and add it later from Settings — Anton still boots either way, it just can\'t do real work until a key is saved.'
    : step === 1
      ? 'Pick as many as you like — each pick becomes a draft waiting for your review in Automations, never a running job. Nothing runs until you approve it. Or describe your own below and Anton will draft that too.'
      : step === 2
        ? 'Name the systems Anton should watch and connect to. You can add more later from Add-ons.'
        : step === 3
          ? 'This sets the default — you can loosen or tighten it per automation later.'
          : totalDrafted === 0
            ? "You didn't pick anything to start with — that's fine, Anton still boots. Add automations any time from Add-ons or by re-running Set up."
            : `Anton filed ${totalDrafted} automation${totalDrafted === 1 ? '' : 's'} as drafts waiting for your review — nothing runs until you approve each one in Automations.`

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
          <div>
            {step === 1 && workCats.map((cat) => (
              <div key={cat.id} style={{ marginBottom: 18 }}>
                <div className={bp.kicker} style={{ margin: '0 0 8px' }}>{cat.label}</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
                  {cat.cards.map((c) => <PickToggle key={c.id} card={c} active={picks.has(c.id)} onToggle={togglePick} />)}
                </div>
              </div>
            ))}
            {step > 1 && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {stepCards.map((c) => <PickToggle key={c.id} card={c} active={picks.has(c.id)} onToggle={togglePick} />)}
              </div>
            )}
            {step === 1 && (
              <div style={{ border: '1px solid var(--dsw-alias-border-l2)', padding: 16, marginTop: 4 }}>
                <div className={bp.kicker} style={{ margin: '0 0 8px' }}>DESCRIBE IT</div>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="e.g. Every weekday at 7 AM, pull yesterday's job costs from the accounting file and email me anything over budget."
                  rows={3}
                  style={{ width: '100%', marginBottom: 10, border: '1px solid var(--dsw-alias-border-l2)', background: 'transparent', color: 'var(--dsw-alias-label-primary)', fontFamily: 'inherit', fontSize: 13, padding: 10, resize: 'vertical', boxSizing: 'border-box' }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button
                    onClick={requestDraft}
                    disabled={drafting || !description.trim()}
                    style={{ background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 12.5, padding: '7px 16px', cursor: drafting || !description.trim() ? 'default' : 'pointer', opacity: drafting || !description.trim() ? 0.55 : 1, fontFamily: 'inherit' }}
                  >{drafting ? 'Drafting…' : 'Draft it'}</button>
                  <span style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>You review the draft before anything is saved.</span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Reviewable "Describe it" result (any step ≥ 1): nothing is saved
            until you confirm, and confirming files it as awaiting_approval —
            never running. Same pattern as AutomationsScreen's draft card. */}
        {step >= 1 && step < 4 && draft !== null && !drafting && (
          <div style={{ border: '1px solid var(--dsw-alias-state-warn-label)', padding: 14, marginTop: 14 }}>
            <div className={bp.kicker} style={{ margin: '0 0 6px', color: 'var(--dsw-alias-state-warn-label)' }}>DRAFT — PENDING YOUR REVIEW</div>
            <div style={{ fontSize: 14, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{draft.name}</div>
            <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>{draft.plain}</div>
            <ol style={{ margin: '8px 0', paddingLeft: 18, fontSize: 12.5, color: 'var(--dsw-alias-label-primary)', lineHeight: 1.6 }}>
              {draft.steps.map((s, i) => (
                <li key={i}>{s.text}{s.assignee === 'human' && <span style={{ color: 'var(--dsw-alias-state-warn-label)' }}> · needs your OK</span>}</li>
              ))}
            </ol>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setDraft(null)} disabled={savingDraft} style={{ background: 'none', border: '1px solid var(--dsw-alias-border-l2)', color: 'var(--dsw-alias-label-primary)', fontSize: 12, padding: '4px 10px', cursor: 'pointer', fontFamily: 'inherit' }}>Discard</button>
              <button onClick={saveDraft} disabled={savingDraft} style={{ background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 12, padding: '4px 10px', cursor: savingDraft ? 'default' : 'pointer', opacity: savingDraft ? 0.55 : 1, fontFamily: 'inherit' }}>{savingDraft ? 'Saving…' : 'Save for review'}</button>
            </div>
          </div>
        )}
        {draftError && <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-state-error-primary)', marginTop: 12 }}>{draftError}</div>}

        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
            {[...picks].map((id) => {
              const card = allKnownCards.find(c => c.id === id)
              if (card === undefined) return null
              return (
                <div key={id} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 13, color: 'var(--dsw-alias-label-primary)' }}>
                  <span className={bp.mono} style={{ color: 'var(--dsw-alias-state-warn-label)' }}>+</span>
                  {card.label}
                </div>
              )
            })}
            {draftedNames.map(d => (
              <div key={d.id} style={{ display: 'flex', alignItems: 'baseline', gap: 8, fontSize: 13, color: 'var(--dsw-alias-label-primary)' }}>
                <span className={bp.mono} style={{ color: 'var(--dsw-alias-state-warn-label)' }}>+</span>
                {d.name}
              </div>
            ))}
            {(picks.size > 0 || draftedNames.length > 0) && (
              <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-warn-label)', marginTop: 6 }}>
                Drafted — waiting for your review. Approve each one in Automations before it runs.
              </div>
            )}
          </div>
        )}
      </div>

      <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 14, padding: '16px 24px', borderTop: '1px solid var(--dsw-alias-border-l2)' }}>
        {step >= 1 && step < 4 && (
          <span className={bp.mono} style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)' }}>
            {stepPicked} of {stepTotal} picked
            {step === 1 && ` · Anton will draft roughly ${workPicked + draftedNames.length} automation${workPicked + draftedNames.length === 1 ? '' : 's'}`}
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

/** One tappable suggestion card (step 1 categories and the systems/leash
 * grids all render the same control). */
function PickToggle({ card, active, onToggle }: { card: PickCard; active: boolean; onToggle: (id: string) => void }) {
  return (
    <div onClick={() => { onToggle(card.id) }} style={cardStyle(active)}>
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
        <div style={{ fontSize: 13.5, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{card.label}</div>
        <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 2 }}>{card.sub}</div>
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
