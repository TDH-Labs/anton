import { useCallback, useEffect, useRef, useState } from 'react'
import bp from '../blueprint.module.css'
import { useOpsApi } from '../useOpsApi.ts'

const LN = '1px solid var(--dsw-alias-border-l2)'

type Session = { id: string; title: string | null; updated_at: string | null }
type Message = { role: string; content: string; ts: string }

function newSessionId(): string {
  // The browser owns the id so a first message can stream immediately; the
  // host inserts the session row on demand.
  const c: Crypto | undefined = typeof crypto === 'undefined' ? undefined : crypto
  if (c !== undefined && typeof c.randomUUID === 'function') return c.randomUUID().replace(/-/g, '')
  return `s${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

/**
 * Ask Anton: a durable conversation over the same executor jobs dispatch to.
 *
 * The stream carries progress, not tokens -- no executor can emit partial
 * output -- so a pending turn shows elapsed seconds rather than a growing
 * reply. That distinction is deliberate and visible: "Working… 4s" is honest
 * about a blocking dispatch in a way a fake typing cursor would not be.
 */
export function AskAntonScreen() {
  const sessions = useOpsApi<{ sessions: Session[] }>('/api/chat/sessions')
  const [active, setActive] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  const loadSession = useCallback((id: string) => {
    setActive(id)
    setError(null)
    fetch(`/api/chat/sessions/${encodeURIComponent(id)}`)
      .then(r => r.json() as Promise<{ messages: Message[] }>)
      .then(body => { setMessages(body.messages) })
      .catch(() => { setMessages([]) })
  }, [])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, pending])

  const send = () => {
    const prompt = draft.trim()
    if (prompt === '' || pending) return
    const sid = active ?? newSessionId()
    setActive(sid)
    setDraft('')
    setError(null)
    setElapsed(0)
    setPending(true)
    setMessages(prev => [...prev, { role: 'user', content: prompt, ts: '' }])

    fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, session_id: sid }),
    })
      .then(async (response) => {
        if (!response.ok || response.body === null) {
          throw new Error(`chat stream: ${response.status}`)
        }
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          // SSE frames are separated by a blank line; keep the tail, which
          // may be a partial frame.
          const frames = buffer.split('\n\n')
          buffer = frames.pop() ?? ''
          for (const frame of frames) {
            const eventLine = frame.split('\n').find(l => l.startsWith('event: '))
            const dataLine = frame.split('\n').find(l => l.startsWith('data: '))
            if (eventLine === undefined || dataLine === undefined) continue
            const event = eventLine.slice(7).trim()
            const data = JSON.parse(dataLine.slice(6)) as Record<string, unknown>
            if (event === 'tick') setElapsed(Number(data.elapsed_seconds ?? 0))
            if (event === 'result') {
              setMessages(prev => [...prev,
                { role: 'assistant', content: String(data.reply ?? ''), ts: '' }])
            }
            if (event === 'error') setError(String(data.message ?? 'dispatch failed'))
          }
        }
      })
      .catch(() => { setError("Couldn't reach Anton.") })
      .finally(() => { setPending(false); sessions.refetch() })
  }

  const rows = sessions.data?.sessions ?? []

  return (
    <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex', background: 'var(--dsw-alias-bg-base)' }}>
      {/* Conversations */}
      <div style={{ flex: 'none', width: 200, borderRight: LN, display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '14px 14px 10px', borderBottom: LN }}>
          <button
            onClick={() => { setActive(null); setMessages([]); setError(null) }}
            style={{ width: '100%', padding: '6px 10px', border: LN, background: 'transparent', color: 'var(--dsw-alias-label-primary)', fontSize: 12.5, fontFamily: 'inherit', cursor: 'pointer' }}
          >New conversation</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {rows.length === 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', padding: '4px 14px' }}>
              No conversations yet.
            </div>
          )}
          {rows.map(s => (
            <button
              key={s.id}
              onClick={() => { loadSession(s.id) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left', padding: '7px 14px',
                border: 'none', fontSize: 12.5, fontFamily: 'inherit', cursor: 'pointer',
                background: active === s.id ? 'var(--dsw-alias-bg-layer-2)' : 'transparent',
                color: 'var(--dsw-alias-label-primary)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
            >{s.title ?? 'Untitled'}</button>
          ))}
        </div>
      </div>

      {/* Thread */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 'none', padding: '18px 26px 14px', borderBottom: LN }}>
          <div className={bp.kicker}>ASK ANTON ANYTHING ABOUT YOUR BUSINESS</div>
          <div className={bp.screenTitle}>Ask Anton</div>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '20px 26px' }}>
          {messages.length === 0 && !pending && (
            <div style={{ fontSize: 13.5, color: 'var(--dsw-alias-label-secondary)', maxWidth: 560 }}>
              Anton answers with the same agent that runs your automations, so it can
              read what it has learned and what it has done. It will not take an action
              that touches money or sends something outward without asking you first.
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} style={{ marginBottom: 18, maxWidth: 720 }}>
              <div className={bp.kicker} style={{ marginBottom: 4 }}>
                {m.role === 'user' ? 'YOU' : m.role === 'error' ? 'FAILED' : 'ANTON'}
              </div>
              <div style={{
                fontSize: 13.5, lineHeight: 1.55, whiteSpace: 'pre-wrap',
                color: m.role === 'error'
                  ? 'var(--dsw-alias-state-error-primary)'
                  : 'var(--dsw-alias-label-primary)',
              }}>{m.content}</div>
            </div>
          ))}
          {pending && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-label-secondary)' }}>
              Working{elapsed > 0 ? ` — ${elapsed}s` : '…'}
            </div>
          )}
          {error !== null && (
            <div style={{ fontSize: 13, color: 'var(--dsw-alias-state-error-primary)' }}>{error}</div>
          )}
          <div ref={endRef} />
        </div>

        <div style={{ flex: 'none', borderTop: LN, padding: '14px 26px' }}>
          <div style={{ display: 'flex', gap: 8, maxWidth: 760 }}>
            <textarea
              value={draft}
              onChange={(e) => { setDraft(e.target.value) }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
              }}
              rows={2}
              placeholder="Ask about the business, or what Anton has been doing…"
              style={{
                flex: 1, padding: '9px 11px', border: LN, background: 'var(--dsw-alias-bg-base)',
                color: 'var(--dsw-alias-label-primary)', fontSize: 13.5, fontFamily: 'inherit',
                resize: 'vertical',
              }}
            />
            <button
              onClick={send}
              disabled={pending || draft.trim() === ''}
              style={{
                padding: '8px 18px', border: 'none', fontSize: 13, fontFamily: 'inherit',
                background: 'var(--dsw-alias-state-business-primary)', color: 'var(--dsw-alias-bg-base)',
                cursor: pending || draft.trim() === '' ? 'default' : 'pointer',
                opacity: pending || draft.trim() === '' ? 0.55 : 1,
              }}
            >{pending ? 'Working…' : 'Ask'}</button>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 6 }}>
            Enter to send, Shift+Enter for a new line.
          </div>
        </div>
      </div>
    </div>
  )
}
