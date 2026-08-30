import { useEffect, useState } from 'react'
import bp from './blueprint.module.css'
import { useOpsApi } from './useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

/** Matches GET /api/n8n/config -> { base_url: string | null }. */
type N8nConfig = { base_url: string | null }

/**
 * Settings section for connecting Anton to an operator-run n8n instance
 * (dashboard.py's /api/n8n/config). n8n's own editor stays the place to
 * build a workflow — this is only where Anton is told where to find it, so
 * the Automations screen's "Draw it" tile can open straight into it and
 * N8NExecutor-backed jobs have somewhere to dispatch.
 */
export function N8nSettingsSection() {
  const { data, loading, error, refetch } = useOpsApi<N8nConfig>('/api/n8n/config')
  const [url, setUrl] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (data === null || dirty) return
    setUrl(data.base_url ?? '')
  }, [data, dirty])

  const save = () => {
    setSaving(true)
    setSaveError(false)
    setSaved(false)
    fetch('/api/n8n/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: url.trim() }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`/api/n8n/config: ${r.status}`)
        setDirty(false)
        setSaved(true)
        refetch()
      })
      .catch(() => { setSaveError(true) })
      .finally(() => { setSaving(false) })
  }

  return (
    <div style={{ padding: '22px 26px 30px', display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 640 }}>
      <div>
        <div className={bp.kicker}>AUTOMATION ENGINE</div>
        <div className={bp.screenTitle} style={{ fontSize: 19 }}>n8n</div>
      </div>
      <div style={{ fontSize: 13.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)' }}>
        Anton dispatches automations to your own n8n instance rather than rebuilding its connectors — n8n's
        own editor is where a workflow actually gets built. Point Anton at a reachable n8n instance below;
        an install sharing this Docker host reaches it by container name, e.g. <span className={bp.mono}>http://n8n_server_1:5678</span>.
      </div>
      {loading && <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>Loading…</div>}
      {error && <div style={{ fontSize: 13, color: 'var(--dsw-alias-state-error-primary)' }}>Couldn't reach Anton.</div>}
      {!loading && !error && (
        <>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
            <span style={{ color: 'var(--dsw-alias-label-secondary)' }}>n8n base URL</span>
            <input
              type="text"
              value={url}
              placeholder="http://n8n_server_1:5678"
              onChange={(e) => { setUrl(e.target.value); setDirty(true); setSaved(false) }}
              style={{
                padding: '8px 10px', border: LN, background: 'var(--dsw-alias-bg-base)',
                color: 'var(--dsw-alias-label-primary)', fontSize: 13.5, fontFamily: 'inherit',
              }}
            />
          </label>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <button
              onClick={save}
              disabled={saving}
              style={{
                padding: '7px 16px', background: 'var(--dsw-alias-state-business-primary)',
                color: 'var(--dsw-alias-bg-base)', border: 'none', fontSize: 13,
                cursor: saving ? 'default' : 'pointer', fontFamily: 'inherit',
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            {saved && <span style={{ fontSize: 12.5, color: 'var(--dsw-alias-state-success-primary)' }}>Saved.</span>}
            {saveError && <span style={{ fontSize: 12.5, color: 'var(--dsw-alias-state-error-primary)' }}>Couldn't save — try again.</span>}
          </div>
        </>
      )}
    </div>
  )
}
