import { useState } from 'react'
import css from './GeneralSection.module.css'

export function ApiProvidersSection() {
  const [keys, setKeys] = useState({ openai: '', anthropic: '', gemini: '', deepseek: '' })

  const handleSave = () => {
    const payload: any = {}
    if (keys.openai) payload.openai = { api_key: keys.openai }
    if (keys.anthropic) payload.anthropic = { api_key: keys.anthropic }
    if (keys.gemini) payload.gemini = { api_key: keys.gemini }
    if (keys.deepseek) payload.deepseek = { api_key: keys.deepseek }

    globalThis.fetch('/api/wizard/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(() => alert("Providers saved successfully!")).catch(() => alert("Error saving providers"))
  }

  return (
    <div className={css.section} style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '24px' }}>
      <h2 style={{ fontSize: '1.2rem', fontWeight: 600 }}>API Providers</h2>
      <p style={{ color: 'var(--text-secondary)' }}>Configure the API keys for the providers Anton supports.</p>
      
      {['openai', 'anthropic', 'gemini', 'deepseek'].map(provider => (
        <div key={provider} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontWeight: 500, textTransform: 'capitalize' }}>{provider} API Key</label>
          <input 
            type="password" 
            value={(keys as any)[provider]} 
            onChange={e => setKeys(k => ({ ...k, [provider]: e.target.value }))}
            placeholder={`Enter ${provider} key...`}
            style={{ 
              padding: '8px 12px', borderRadius: '6px', border: '1px solid var(--border-default)', 
              background: 'var(--bg-pane)', color: 'var(--text-main)', width: '100%', maxWidth: '400px' 
            }} 
          />
        </div>
      ))}

      <button 
        onClick={handleSave}
        style={{
          marginTop: '16px', padding: '10px 16px', background: 'var(--primary)', color: '#fff', 
          border: 'none', borderRadius: '6px', fontWeight: 600, cursor: 'pointer', width: 'fit-content'
        }}
      >
        Save Providers
      </button>
    </div>
  )
}
