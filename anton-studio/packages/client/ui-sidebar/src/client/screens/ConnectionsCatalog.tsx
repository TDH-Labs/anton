import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import bp from '../blueprint.module.css'

type Conn = { id: string; name: string; category: string; transport: string; what?: string; url?: string; auth?: string; bridge?: string }

/**
 * Claude-style abundant connections grid, rendered at the top of Add-ons.
 * Backed by GET /api/connections/catalog (bundled + MCP registry sync +
 * Composio/Nango bridge apps when configured). One click = connected;
 * remote-http entries store URL+auth, stdio entries store their command,
 * bridge entries record ownership. Existing manual forms stay below.
 */
export function ConnectionsCatalog({ onConnected }: { onConnected?: (c: { id: string; name: string }) => void }) {
  const [conns, setConns] = useState<Conn[]>([])
  const [bridges, setBridges] = useState<{ composio?: boolean; nango?: boolean }>({})
  const [filter, setFilter] = useState('')
  const [connectedIds, setConnectedIds] = useState<Set<string>>(new Set())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const load = () => {
    fetch('/api/connections/catalog')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d?.connections) setConns(d.connections); if (d?.bridges) setBridges(d.bridges) })
      .catch(() => {})
    fetch('/api/wizard/mcp')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (Array.isArray(d)) setConnectedIds(new Set(d.map((m: { id: string }) => m.id))) })
      .catch(() => {})
  }
  useEffect(load, [])

  const connect = (c: Conn) => {
    setBusyId(c.id)
    setError('')
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

  const q = filter.trim().toLowerCase()
  const shown = conns.filter((c) => !q || c.name.toLowerCase().includes(q) || (c.what ?? '').toLowerCase().includes(q))

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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 8 }}>
        {shown.map((c) => {
          const isConnected = connectedIds.has(c.id)
          return (
            <div key={c.id} style={cardStyle}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</span>
                <span style={{ flex: 1 }} />
                {isConnected && <span style={{ fontSize: 10.5, color: 'var(--dsw-alias-state-success-primary)' }}>connected</span>}
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
                {isConnected ? '✓ Connected' : busyId === c.id ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
