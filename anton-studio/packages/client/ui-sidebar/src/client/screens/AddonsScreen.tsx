import { useState } from 'react'
import { ConnectionsCatalog } from './ConnectionsCatalog.tsx'
import type { CSSProperties } from 'react'
import bp from '../blueprint.module.css'
import { Blueprint } from '../Blueprint.tsx'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/wizard/mcp -> Addon[] (README, Data Contracts). */
type Addon = { id: string; name: string; what: string; permissions: string[]; status: string }

type ConnectType = 'oauth' | 'mcp' | 'api_key' | 'login'

/** Matches the backend's OAUTH_AUTHORIZE_URLS keys (dashboard.py) -- a
 * provider only actually connects once an operator has registered a real
 * OAuth app for it (oauth.<provider>.client_id in config.yaml); until then
 * /api/wizard/oauth/start says so plainly rather than pretending. */
const OAUTH_PROVIDERS = [
  { id: 'quickbooks', label: 'QuickBooks' },
  { id: 'google', label: 'Google' },
  { id: 'slack', label: 'Slack' },
  { id: 'github', label: 'GitHub' },
]

const inputStyle: CSSProperties = {
  width: '100%', boxSizing: 'border-box', padding: '10px 12px', fontSize: 13.5,
  fontFamily: 'inherit', border: LN, background: 'var(--dsw-alias-bg-base)',
  color: 'var(--dsw-alias-label-primary)',
}

/** Connect-something-new modal: picks the right mechanism per service
 * (OAuth / MCP / a plain API key) instead of forcing every connection
 * through the same field -- replaces what used to be two chained native
 * window.prompt() dialogs with a real form, per each type's actual
 * requirements. */
function ConnectModal({ onClose, onConnected }: { onClose: () => void; onConnected: (a: Addon) => void }) {
  const [type, setType] = useState<ConnectType>('mcp')
  const [name, setName] = useState('')
  const [what, setWhat] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [oauthProvider, setOauthProvider] = useState('quickbooks')
  const [oauthStatus, setOauthStatus] = useState<'idle' | 'listening' | 'not_configured'>('idle')
  const [loginUrl, setLoginUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [successSelector, setSuccessSelector] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [usernameSelector, setUsernameSelector] = useState('input[type=email], input[type=text]')
  const [passwordSelector, setPasswordSelector] = useState('input[type=password]')
  const [submitSelector, setSubmitSelector] = useState('button[type=submit]')
  const [loginResult, setLoginResult] = useState<{ status: string; detail: string } | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const submitConnection = () => {
    if (!name.trim()) { setError('Give it a name.'); return }
    setSaving(true)
    setError('')
    fetch('/api/wizard/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, command: 'n/a', what, permissions: [], api_key: type === 'api_key' ? apiKey : '' }),
    }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`)
      return r.json() as Promise<{ id: string; name: string }>
    }).then((saved) => {
      onConnected({ id: saved.id, name: saved.name, what, permissions: [], status: 'active' })
      onClose()
    }).catch(() => { setError("Couldn't save that -- try again.") })
      .finally(() => { setSaving(false) })
  }

  const startOauth = () => {
    setSaving(true)
    setError('')
    fetch(`/api/wizard/oauth/start?provider=${oauthProvider}`)
      .then((r) => r.json() as Promise<{ status: string; auth_url?: string; detail?: string }>)
      .then((body) => {
        if (body.status === 'listening' && body.auth_url) {
          setOauthStatus('listening')
          window.open(body.auth_url, '_blank', 'noopener')
        } else {
          setOauthStatus('not_configured')
        }
      })
      .catch(() => { setError("Couldn't reach Anton.") })
      .finally(() => { setSaving(false) })
  }

  const submitBrowserLogin = () => {
    if (!name.trim()) { setError('Give it a name.'); return }
    if (!loginUrl.trim() || !username.trim() || !password.trim()) { setError('Login URL, username, and password are all required.'); return }
    if (!successSelector.trim()) { setError("Need one thing that's only there once you're logged in (a CSS selector) -- Anton uses it to confirm the login actually worked."); return }
    setSaving(true)
    setError('')
    setLoginResult(null)
    fetch('/api/wizard/browser-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name, login_url: loginUrl, username, password, what,
        username_selector: usernameSelector, password_selector: passwordSelector,
        submit_selector: submitSelector, success_selector: successSelector,
      }),
    }).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`)
      return r.json() as Promise<{ status: string; detail: string; id: string; name: string }>
    }).then((saved) => {
      setLoginResult({ status: saved.status, detail: saved.detail })
      if (saved.status === 'success') {
        onConnected({ id: saved.id, name: saved.name, what, permissions: [], status: 'active' })
        onClose()
      }
      // needs_human / error / no_credential: leave the modal open so the
      // operator sees why, same as the OAuth tab's not_configured state --
      // never claim success that didn't happen.
    }).catch(() => { setError("Couldn't reach Anton.") })
      .finally(() => { setSaving(false) })
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, background: 'rgba(29,31,32,.55)' }} onClick={onClose}>
      <div className={bp.blueprint} style={{ width: 'min(480px, 100%)', background: 'var(--dsw-alias-bg-base)', boxShadow: '0 12px 32px rgba(29,31,32,.22)' }} onClick={(e) => { e.stopPropagation() }}>
        <span className={`${bp.corner} ${bp.cornerTl}`} /><span className={`${bp.corner} ${bp.cornerTr}`} />
        <span className={`${bp.corner} ${bp.cornerBl}`} /><span className={`${bp.corner} ${bp.cornerBr}`} />

        <div style={{ padding: '20px 24px', borderBottom: LN }}>
          <div className={bp.kicker}>CONNECT SOMETHING NEW</div>
          <div className={bp.screenTitle} style={{ fontSize: 21 }}>What should Anton connect to?</div>
        </div>

        <div style={{ padding: '20px 24px' }}>
          <div style={{ display: 'flex', gap: 1, background: 'var(--dsw-alias-border-l2)', marginBottom: 18 }}>
            {([['mcp', 'MCP'], ['oauth', 'OAuth'], ['api_key', 'API key'], ['login', 'Login']] as [ConnectType, string][]).map(([t, label]) => (
              <div key={t} onClick={() => { setType(t); setError('') }} style={{ flex: 1, textAlign: 'center', padding: '9px 8px', fontSize: 12.5, fontWeight: 500, cursor: 'pointer', background: type === t ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-bg-base)', color: type === t ? 'var(--dsw-alias-bg-base)' : 'var(--dsw-alias-label-secondary)' }}>
                {label}
              </div>
            ))}
          </div>

          {type === 'oauth' ? (
            <div>
              <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 10 }}>
                Anton signs in through the service's own login -- nothing to type here.
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginBottom: 14 }}>
                {OAUTH_PROVIDERS.map((p) => (
                  <div key={p.id} onClick={() => { setOauthProvider(p.id); setOauthStatus('idle') }} style={{ padding: '9px 12px', border: LN, cursor: 'pointer', fontSize: 13, background: oauthProvider === p.id ? 'var(--dsw-alias-state-business-tertiary)' : 'transparent', borderColor: oauthProvider === p.id ? 'var(--dsw-alias-state-business-primary)' : undefined }}>
                    {p.label}
                  </div>
                ))}
              </div>
              {oauthStatus === 'not_configured' && (
                <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-warn-label)', marginBottom: 12 }}>
                  Not set up yet -- this deployment hasn't registered a {OAUTH_PROVIDERS.find(p => p.id === oauthProvider)?.label} OAuth app.
                </div>
              )}
              {oauthStatus === 'listening' && (
                <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-success-primary)', marginBottom: 12 }}>
                  Opened in a new tab -- finish signing in there.
                </div>
              )}
              <button onClick={startOauth} disabled={saving} style={{ width: '100%', padding: '11px', fontFamily: 'inherit', fontSize: 13.5, fontWeight: 500, border: 'none', background: 'var(--dsw-alias-state-business-primary)', color: '#fff', cursor: 'pointer' }}>
                {saving ? 'Connecting…' : `Connect via ${OAUTH_PROVIDERS.find(p => p.id === oauthProvider)?.label}`}
              </button>
            </div>
          ) : type === 'login' ? (
            <div>
              <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 10 }}>
                For a site with no API of its own -- Anton signs in and stays signed in.
                The password is encrypted and never leaves this install.
              </div>
              <input placeholder="Name" value={name} onChange={(e) => { setName(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
              <input placeholder="Login page URL" value={loginUrl} onChange={(e) => { setLoginUrl(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
              <input placeholder="Username or email" value={username} onChange={(e) => { setUsername(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
              <div style={{ position: 'relative', marginBottom: 10 }}>
                <input type={showPassword ? 'text' : 'password'} placeholder="Password" value={password} onChange={(e) => { setPassword(e.target.value) }} style={{ ...inputStyle, paddingRight: 60 }} />
                <button onClick={() => { setShowPassword(v => !v) }} style={{ position: 'absolute', right: 8, top: 8, background: 'none', border: 'none', fontSize: 11, color: 'var(--dsw-alias-label-secondary)', cursor: 'pointer', fontFamily: 'inherit' }}>
                  {showPassword ? 'Hide' : 'Show'}
                </button>
              </div>
              <input placeholder="Something only visible once logged in (CSS selector)" value={successSelector} onChange={(e) => { setSuccessSelector(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
              <div onClick={() => { setShowAdvanced(v => !v) }} style={{ fontSize: 12, color: 'var(--dsw-alias-state-business-primary)', cursor: 'pointer', marginBottom: showAdvanced ? 10 : 16 }}>
                {showAdvanced ? '– Hide advanced fields' : '+ Adjust the login form fields'}
              </div>
              {showAdvanced && (
                <div style={{ marginBottom: 6 }}>
                  <input placeholder="Username field selector" value={usernameSelector} onChange={(e) => { setUsernameSelector(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
                  <input placeholder="Password field selector" value={passwordSelector} onChange={(e) => { setPasswordSelector(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
                  <input placeholder="Submit button selector" value={submitSelector} onChange={(e) => { setSubmitSelector(e.target.value) }} style={{ ...inputStyle, marginBottom: 16 }} />
                </div>
              )}
              {loginResult && loginResult.status !== 'success' && (
                <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-warn-label)', marginBottom: 12 }}>
                  {loginResult.status === 'needs_human'
                    ? "Couldn't finish automatically -- this looks like it needs a 2-factor code or a CAPTCHA."
                    : loginResult.detail || "Couldn't log in -- double-check the fields above."}
                </div>
              )}
              {error && <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-error-primary)', marginBottom: 12 }}>{error}</div>}
              <button onClick={submitBrowserLogin} disabled={saving} style={{ width: '100%', padding: '11px', fontFamily: 'inherit', fontSize: 13.5, fontWeight: 500, border: 'none', background: 'var(--dsw-alias-state-business-primary)', color: '#fff', cursor: 'pointer' }}>
                {saving ? 'Signing in…' : 'Sign in and connect'}
              </button>
            </div>
          ) : (
            <div>
              <input placeholder="Name" value={name} onChange={(e) => { setName(e.target.value) }} style={{ ...inputStyle, marginBottom: 10 }} />
              <input placeholder="What should it be allowed to do?" value={what} onChange={(e) => { setWhat(e.target.value) }} style={{ ...inputStyle, marginBottom: type === 'api_key' ? 10 : 16 }} />
              {type === 'api_key' && (
                <div style={{ position: 'relative', marginBottom: 16 }}>
                  <input type={showKey ? 'text' : 'password'} placeholder="API key" value={apiKey} onChange={(e) => { setApiKey(e.target.value) }} style={{ ...inputStyle, paddingRight: 60 }} />
                  <button onClick={() => { setShowKey(v => !v) }} style={{ position: 'absolute', right: 8, top: 8, background: 'none', border: 'none', fontSize: 11, color: 'var(--dsw-alias-label-secondary)', cursor: 'pointer', fontFamily: 'inherit' }}>
                    {showKey ? 'Hide' : 'Show'}
                  </button>
                </div>
              )}
              {error && <div style={{ fontSize: 12, color: 'var(--dsw-alias-state-error-primary)', marginBottom: 12 }}>{error}</div>}
              <button onClick={submitConnection} disabled={saving} style={{ width: '100%', padding: '11px', fontFamily: 'inherit', fontSize: 13.5, fontWeight: 500, border: 'none', background: 'var(--dsw-alias-state-business-primary)', color: '#fff', cursor: 'pointer' }}>
                {saving ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** Add-ons (README §8): connected tools and permissions, backed by mcp_servers. */
export function AddonsScreen() {
  const { data, loading, error } = useOpsApi<Addon[]>('/api/wizard/mcp')
  const [added, setAdded] = useState<Addon[]>([])
  const [showModal, setShowModal] = useState(false)

  const addons = [...(data ?? []), ...added]

  return (
    <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <div style={{ flex: 'none', display: 'flex', alignItems: 'flex-end', gap: 16, padding: '18px 26px 14px', borderBottom: LN }}>
        <div>
          <div className={bp.kicker}>CONNECTED TOOLS AND PERMISSIONS</div>
          <div className={bp.screenTitle}>Add-ons</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        <div style={{ padding: '18px 26px 0' }}>
          <ConnectionsCatalog onConnected={(c) => setAdded((prev) => [...prev.filter((x) => x.id !== c.id), { id: c.id, name: c.name, what: '', permissions: [], status: 'active' as const }])} />
        </div>
        <div style={{ padding: '4px 26px 30px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, alignContent: 'start' }}>
          <div style={{ gridColumn: '1 / -1', fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)' }}>MANUAL SETUP</div>
          {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
          {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Couldn't reach Anton.</div>}
          {addons.map((a) => {
            const connected = a.status === 'active'
            const color = connected ? 'var(--dsw-alias-state-success-primary)' : 'var(--dsw-alias-label-secondary)'
            return (
              <Blueprint key={a.id} style={{ background: 'var(--dsw-alias-bg-layer-2)', padding: '16px 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                  <div className={bp.screenTitle} style={{ flex: 1, fontSize: 16 }}>{a.name}</div>
                  <span className={bp.kicker} style={{ display: 'flex', alignItems: 'center', gap: 5, margin: 0, color }}>
                    <span style={{ width: 6, height: 6, background: color }} />
                    {connected ? 'CONNECTED' : 'AVAILABLE'}
                  </span>
                </div>
                {a.what !== '' && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)', lineHeight: 1.4, marginBottom: 12 }}>{a.what}</div>}
                {a.permissions.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 14 }}>
                    {a.permissions.map((p, j) => (
                      <div key={j} style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)' }}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--dsw-alias-state-success-primary)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
                        {p}
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
                  <button style={{ background: 'none', border: 'none', color: 'var(--dsw-alias-state-error-primary)', fontSize: 12, cursor: 'pointer', textDecoration: 'underline', fontFamily: 'inherit', padding: 0 }}>{connected ? 'Turn off' : 'Add to Anton'}</button>
                </div>
              </Blueprint>
            )
          })}
          {/* Add new card */}
          <div onClick={() => { setShowModal(true) }} style={{ background: 'transparent', border: LN, padding: '16px 18px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 9, cursor: 'pointer', color: 'var(--dsw-alias-label-secondary)', minHeight: 120 }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14" /></svg>
            <span style={{ fontSize: 13.5 }}>Connect something new</span>
          </div>
        </div>
      </div>
      {showModal && (
        <ConnectModal
          onClose={() => { setShowModal(false) }}
          onConnected={(a) => { setAdded(prev => [...prev, a]) }}
        />
      )}
    </div>
  )
}
