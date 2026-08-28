import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import bp from '../blueprint.module.css'

type Conn = { id: string; name: string; category: string; transport: string; what?: string; url?: string; auth?: string; bridge?: string }

/**
 * Claude-style abundant connections grid, rendered at the top of Add-ons.
 * Backed by GET /api/connections/catalog (bundled + MCP registry sync +
 * Composio/Nango bridge apps when configured).
 *
 * Honesty contract (the "everything connects instantly" bug): a plain
 * connect only REGISTERS the entry server-side — it is shown as "Saved" with
 * the truth that authentication happens at first tool use, never as
 * "Connected". Hosted-OAuth bridge entries DO connect for real: clicking
 * starts the provider's actual OAuth consent flow and the card flips to
 * Connected only when that flow completes.
 */
export function ConnectionsCatalog({ onConnected }: { onConnected?: (c: { id: string; name: string }) => void }) {
  const [conns, setConns] = useState<Conn[]>([])
  const [bridges, setBridges] = useState<{ composio?: boolean; nango?: boolean }>({})
  const [filter, setFilter] = useState('')
  const [connectedIds, setConnectedIds] = useState<Set<string>>(new Set())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  // Mirror of busyId readable inside the OAuth status poll's closures (the
  // setState value is stale there; a superseded click must stop its poll).
  const busyRef = useRef<string | null>(null)

  const load = () => {
    // A failed catalog load must be visible, not a silently empty grid:
    // under authz the apiproxy's scoped credential used to 403 here and the
    // Add-ons page rendered with no connectors and no explanation.
    fetch('/api/connections/catalog')
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => { if (d?.connections) setConns(d.connections); if (d?.bridges) setBridges(d.bridges); setLoadError('') })
      .catch((e) => { setLoadError(`Couldn't load the connector catalog (${e?.message ?? e}). Manual setup below still works.`) })
    fetch('/api/wizard/mcp')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (Array.isArray(d)) setConnectedIds(new Set(d.map((m: { id: string }) => m.id))) })
      .catch(() => {})
  }
  useEffect(load, [])

  const connect = (c: Conn) => {
    setBusyId(c.id)
    busyRef.current = c.id
    setError('')
    if (c.bridge) {
      // Real hosted-OAuth: open the provider's consent page, poll until the
      // bridge reports the connection active. Never fake success — on error
      // or timeout the card stays actionable with the reason shown.
      const slug = c.id.split(':')[1] ?? c.id
      fetch('/api/integrations/connect/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bridge: c.bridge, provider: slug }),
      }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
        .then((d) => {
          if (!d?.url || !d?.state) throw new Error('no consent URL returned')
          window.open(d.url, '_blank', 'noopener')
          const deadline = Date.now() + 5 * 60_000
          const poll = () => {
            if (busyRef.current !== c.id) return // superseded/unmounted
            fetch(`/api/integrations/connect/status?state=${encodeURIComponent(d.state)}`)
              .then((r) => (r.ok ? r.json() : null))
              .then((s) => {
                if (!busyRef.current) return // superseded/unmounted
                if (s?.status === 'active') {
                  setConnectedIds((set) => new Set([...set, c.id]))
                  onConnected?.({ id: c.id, name: c.name })
                  setBusyId(null)
                  busyRef.current = null
                } else if (Date.now() < deadline && busyRef.current === c.id) {
                  setTimeout(poll, 2000)
                } else if (busyRef.current === c.id) {
                  setError(`Consent didn't complete for ${c.name} within 5 minutes — try again.`)
                  setBusyId(null)
                  busyRef.current = null
                }
              })
              .catch(() => { setError(`Lost contact while waiting for ${c.name}'s consent.`); setBusyId(null) })
          }
          setTimeout(poll, 2000)
        })
        .catch((e) => { setError(String(e.message ?? e)); setBusyId(null); busyRef.current = null })
      return
    }
    fetch('/api/connections/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: c.id, name: c.name, what: c.what ?? '', url: c.url ?? '', auth: c.auth ?? '', bridge: c.bridge ?? '' }),
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setConnectedIds((s) => new Set([...s, c.id]))
      onConnected?.({ id: c.id, name: c.name })
    }).catch((e) => setError(String(e.message ?? e)))
      .finally(() => setBusyId(null))
  }

  // Search matches name, description, and category so e.g. "finance" or
  // "developer" narrows the grid the same way a service name does.
  const q = filter.trim().toLowerCase()
  const shown = conns.filter((c) => !q
    || c.name.toLowerCase().includes(q)
    || (c.what ?? '').toLowerCase().includes(q)
    || c.category.toLowerCase().includes(q))

  const cardStyle: CSSProperties = {
    display: 'flex', flexDirection: 'column', gap: 4, padding: '10px 12px',
    border: '1px solid var(--dsw-alias-border-l2)', borderRadius: 8, background: 'var(--dsw-alias-bg-base)', minWidth: 0,
  }

  return (
    <div style={{ marginBottom: 22 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <div className={bp.kicker} style={{ margin: 0 }}>CONNECTORS ({shown.length})</div>
        <span style={{ flex: 1 }} />
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search connectors…"
          style={{ padding: '6px 10px', fontSize: 12.5, fontFamily: 'inherit', border: '1px solid var(--dsw-alias-border-l2)', background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', width: 180 }}
        />
      </div>
      {!bridges.composio && !bridges.nango && (
        <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 8 }}>
          Tip: set <code>bridges.composio.api_key</code> or <code>bridges.nango.secret_key</code> in config.yaml to unlock hundreds more hosted-OAuth SaaS connectors (QuickBooks, Gmail, Slack…).
        </div>
      )}
      {error && <div style={{ fontSize: 12, color: '#c0392b', marginBottom: 8 }}>{error}</div>}
      {(bridges.composio || bridges.nango) && (
        <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 8 }}>
          Hosted-OAuth connectors open their real consent flow; everything else saves now and authenticates at first use.
        </div>
      )}
      {loadError && conns.length === 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-state-warn-label)', border: '1px solid var(--dsw-alias-border-l2)', borderRadius: 8, padding: '10px 12px', marginBottom: 8 }}>
          No connectors to show -- {loadError}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 8 }}>
        {shown.map((c) => {
          const isConnected = connectedIds.has(c.id)
          return (
            <div key={c.id} style={cardStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</span>
                <span style={{ flex: 1 }} />
                {isConnected && <span style={{ fontSize: 10.5, color: c.bridge ? 'var(--dsw-alias-state-success-primary)' : 'var(--dsw-alias-label-secondary)' }}>{c.bridge ? 'connected' : 'saved'}</span>}
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', lineHeight: 1.4, minHeight: 32 }}>{c.what}</div>
              <button
                onClick={() => connect(c)}
                disabled={isConnected || busyId === c.id}
                style={{
                  marginTop: 2, padding: '5px 0', fontSize: 12, cursor: isConnected ? 'default' : 'pointer', fontFamily: 'inherit',
                  background: isConnected ? 'transparent' : 'var(--dsw-alias-state-business-primary)',
                  color: isConnected ? 'var(--dsw-alias-state-success-primary)' : 'var(--dsw-alias-bg-base)',
                  border: isConnected ? 'none' : 'none', borderRadius: 5,
                }}
              >
                {isConnected ? (c.bridge ? '✓ Connected' : '✓ Saved') : busyId === c.id ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
