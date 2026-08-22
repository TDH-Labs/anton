import { useEffect, useRef, useState } from 'react'
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import bp from '../blueprint.module.css'

export type NodeKind = 'trigger' | 'step' | 'question' | 'human'
export type EditorNode = { id: string; kind: NodeKind; x: number; y: number; text: string; assignee?: string; notify?: ('sms' | 'inbox' | 'email')[] }
export type EditorLink = [string, string]

const LN = '1px solid var(--dsw-alias-border-l2)'
const NODE_WIDTH = 208

const KIND_META: Record<NodeKind, { label: string; color: string; palette: string; paletteSub: string }> = {
  trigger: { label: 'When this happens', color: 'var(--dsw-alias-label-secondary)', palette: 'When this happens', paletteSub: 'A time or an event' },
  step: { label: 'Anton does this', color: 'var(--dsw-alias-state-business-primary)', palette: 'Anton does this', paletteSub: 'A job to run' },
  question: { label: 'Anton checks', color: 'var(--dsw-alias-state-success-primary)', palette: 'Anton checks', paletteSub: 'Splits two ways' },
  human: { label: 'Ask a human', color: 'var(--dsw-alias-state-warn-label)', palette: 'Ask a human', paletteSub: 'Stops until someone says yes' },
}

const PALETTE_ORDER: NodeKind[] = ['step', 'question', 'human', 'trigger']

let nextId = 1
function makeId() { return `n${nextId++}` }

/**
 * The node editor (README §4): three panes in one blueprint frame — a
 * step-kind palette, a drag/connect canvas, and a per-node inspector.
 * Interaction model (README "Node editor") implemented verbatim: header-only
 * pointer-capture drag, right-port click-to-arm connect with dedup, node
 * click select/edit, delete cascades links, add appends staggered + selects.
 * No zoom, pan, minimap, or snapping — the canvas holds six to ten steps.
 */
export function NodeEditorScreen(props: {
  automationId: string
  automationName: string
  initialNodes: EditorNode[]
  initialLinks: EditorLink[]
  onDone: () => void
}) {
  const [nodes, setNodes] = useState<EditorNode[]>(props.initialNodes)
  const [links, setLinks] = useState<EditorLink[]>(props.initialLinks)
  const [sel, setSel] = useState<string | null>(null)
  const [linkFrom, setLinkFrom] = useState<string | null>(null)
  const canvasRef = useRef<HTMLDivElement | null>(null)
  const drag = useRef<{ id: string; offsetX: number; offsetY: number } | null>(null)
  const dragCleanup = useRef<(() => void) | null>(null)

  // Detach the in-flight drag's window listeners if this screen unmounts
  // mid-gesture (e.g. the user navigates away while still holding a node) —
  // otherwise pointermove/pointerup stay bound to window past the
  // component's lifetime.
  useEffect(() => () => { dragCleanup.current?.() }, [])

  const selectedNode = nodes.find(n => n.id === sel) ?? null

  const addNode = (kind: NodeKind) => {
    const idx = nodes.length
    const id = makeId()
    const node: EditorNode = {
      id, kind,
      x: 24 + (idx % 3) * 40,
      y: 24 + (idx % 4) * 96,
      text: '',
      ...(kind === 'human' ? { assignee: 'the plant manager', notify: ['sms', 'inbox'] as ('sms' | 'inbox' | 'email')[] } : {}),
    }
    setNodes(prev => [...prev, node])
    setSel(id)
  }

  const removeNode = (id: string) => {
    setNodes(prev => prev.filter(n => n.id !== id))
    setLinks(prev => prev.filter(([a, b]) => a !== id && b !== id))
    setSel(s => (s === id ? null : s))
    setLinkFrom(f => (f === id ? null : f))
  }

  const setKind = (id: string, kind: NodeKind) => {
    setNodes(prev => prev.map((n) => {
      if (n.id !== id) return n
      if (kind === 'human' && n.kind !== 'human') {
        return { ...n, kind, assignee: n.assignee ?? 'the plant manager', notify: n.notify ?? ['sms', 'inbox'] }
      }
      return { ...n, kind }
    }))
  }

  const setText = (id: string, text: string) => {
    setNodes(prev => prev.map(n => (n.id === id ? { ...n, text } : n)))
  }

  const setAssignee = (id: string, assignee: string) => {
    setNodes(prev => prev.map(n => (n.id === id ? { ...n, assignee } : n)))
  }

  const toggleNotify = (id: string, channel: 'sms' | 'inbox' | 'email') => {
    setNodes(prev => prev.map((n) => {
      if (n.id !== id) return n
      const has = new Set(n.notify ?? [])
      if (has.has(channel)) has.delete(channel)
      else has.add(channel)
      return { ...n, notify: [...has] }
    }))
  }

  const onHeaderPointerDown = (e: ReactPointerEvent<HTMLDivElement>, node: EditorNode) => {
    e.preventDefault()
    e.stopPropagation()
    setSel(node.id)
    const canvas = canvasRef.current
    if (canvas === null) return
    const rect = canvas.getBoundingClientRect()
    drag.current = { id: node.id, offsetX: e.clientX - rect.left - node.x, offsetY: e.clientY - rect.top - node.y }

    const onMove = (ev: PointerEvent) => {
      if (drag.current === null) return
      const r = canvas.getBoundingClientRect()
      const nx = Math.max(0, ev.clientX - r.left - drag.current.offsetX)
      const ny = Math.max(0, ev.clientY - r.top - drag.current.offsetY)
      setNodes(prev => prev.map(n => (n.id === drag.current?.id ? { ...n, x: nx, y: ny } : n)))
    }
    const detach = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      dragCleanup.current = null
    }
    const onUp = () => {
      drag.current = null
      detach()
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    dragCleanup.current = detach
  }

  const onPortClick = (e: ReactMouseEvent<HTMLDivElement>, id: string) => {
    e.stopPropagation()
    if (linkFrom === id) { setLinkFrom(null); return }
    if (linkFrom === null) { setLinkFrom(id); return }
    const a = linkFrom
    const b = id
    setLinks(prev => (prev.some(([x, y]) => x === a && y === b) ? prev : [...prev, [a, b]]))
    setLinkFrom(null)
  }

  const onNodeClick = (id: string) => {
    if (linkFrom !== null && linkFrom !== id) {
      setLinks(prev => (prev.some(([x, y]) => x === linkFrom && y === id) ? prev : [...prev, [linkFrom, id]]))
      setLinkFrom(null)
      return
    }
    setSel(id)
  }

  const gateNodes = nodes.filter(n => n.kind === 'human')
  const plainEnglish = nodes.filter(n => n.text.trim() !== '').map(n => n.text.trim()).join('. ')

  const approve = () => {
    fetch(`/api/automations/${props.automationId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: props.automationName, plain: plainEnglish, nodes, links, state: 'running' }),
    }).catch(() => { /* the editor still closes; the draft did not persist server-side */ })
      .finally(() => { props.onDone() })
  }

  return (
    <div className={bp.blueprint} style={{ display: 'flex', flexDirection: 'column', background: 'var(--dsw-alias-bg-base)' }}>
      <span className={`${bp.corner} ${bp.cornerTl}`} />
      <span className={`${bp.corner} ${bp.cornerTr}`} />
      <span className={`${bp.corner} ${bp.cornerBl}`} />
      <span className={`${bp.corner} ${bp.cornerBr}`} />

      <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: LN }}>
        <button onClick={props.onDone} style={{ background: 'none', border: LN, color: 'var(--dsw-alias-label-primary)', fontSize: 12.5, padding: '5px 10px', cursor: 'pointer', fontFamily: 'inherit' }}>← Automations</button>
        <div style={{ fontSize: 15, fontWeight: 500, color: 'var(--dsw-alias-label-primary)' }}>{props.automationName}</div>
        <span style={{ flex: 1 }} />
        <button onClick={approve} style={{ background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 12.5, padding: '7px 16px', cursor: 'pointer', fontFamily: 'inherit' }}>Approve and turn it on</button>
      </div>

      <div style={{ display: 'flex' }}>
        {/* Left palette */}
        <div style={{ flex: 'none', width: 172, borderRight: LN, padding: '16px 14px' }}>
          <div className={bp.kicker}>Add a step</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 16 }}>
            {PALETTE_ORDER.map((kind) => {
              const meta = KIND_META[kind]
              return (
                <div key={kind} onClick={() => { addNode(kind) }} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 9px', border: LN, cursor: 'pointer' }}>
                  <span style={{ flex: 'none', width: 9, height: 9, marginTop: 3, background: meta.color }} />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-primary)' }}>{meta.palette}</div>
                    <div style={{ fontSize: 10.5, color: 'var(--dsw-alias-label-secondary)', marginTop: 1 }}>{meta.paletteSub}</div>
                  </div>
                </div>
              )
            })}
          </div>
          <div style={{ fontSize: 11.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)' }}>
            Click a step to add it to the canvas, drag it into place by its header,
            then click the right-edge square to connect it to what runs next.
          </div>
        </div>

        {/* Canvas */}
        <div
          ref={canvasRef}
          style={{
            flex: 1, height: 460, position: 'relative', overflow: 'hidden',
            backgroundImage: 'radial-gradient(var(--dsw-alias-border-l2) 1px, transparent 1px)',
            backgroundSize: '22px 22px',
          }}
          onClick={() => { setSel(null) }}
        >
          <svg style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'visible' }}>
            {links.map(([a, b], i) => {
              const from = nodes.find(n => n.id === a)
              const to = nodes.find(n => n.id === b)
              if (from === undefined || to === undefined) return null
              const x1 = from.x + NODE_WIDTH
              const y1 = from.y + 19
              const x2 = to.x
              const y2 = to.y + 19
              const c = Math.max(40, Math.abs(x2 - x1) * 0.45)
              return (
                <path
                  key={i}
                  d={`M ${x1} ${y1} C ${x1 + c} ${y1}, ${x2 - c} ${y2}, ${x2} ${y2}`}
                  fill="none"
                  stroke="var(--dsw-alias-border-l2)"
                  strokeWidth={1.5}
                />
              )
            })}
          </svg>

          {nodes.map((n) => {
            const meta = KIND_META[n.kind]
            const active = sel === n.id
            const armed = linkFrom === n.id
            return (
              <div
                key={n.id}
                onClick={(e) => { e.stopPropagation(); onNodeClick(n.id) }}
                style={{
                  position: 'absolute', left: n.x, top: n.y, width: NODE_WIDTH,
                  background: 'var(--dsw-alias-bg-base)',
                  border: `1px solid ${active ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`,
                  boxShadow: active ? '0 0 0 2px var(--dsw-alias-state-business-tertiary)' : 'none',
                  cursor: 'pointer',
                }}
              >
                <div
                  onPointerDown={(e) => { onHeaderPointerDown(e, n) }}
                  style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '7px 9px', borderBottom: LN, cursor: 'grab' }}
                >
                  <span style={{ flex: 'none', width: 9, height: 9, background: meta.color }} />
                  <span className={bp.kicker} style={{ margin: 0, flex: 1 }}>{meta.label}</span>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" style={{ color: 'var(--dsw-alias-label-secondary)', opacity: 0.6 }}><circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" /><circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" /><circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" /></svg>
                </div>
                <div style={{ padding: '8px 9px 9px', fontSize: 12, lineHeight: 1.4, color: 'var(--dsw-alias-label-primary)', minHeight: 20 }}>
                  {n.text.trim() === '' ? <span style={{ color: 'var(--dsw-alias-label-secondary)' }}>Say what should happen here, in your own words</span> : n.text}
                  {n.kind === 'human' && (
                    <div className={bp.mono} style={{ fontSize: 10.5, marginTop: 6, color: 'var(--dsw-alias-state-warn-label)' }}>asks {n.assignee ?? 'someone'} · plant manager</div>
                  )}
                </div>
                {/* Left port: decorative */}
                <span style={{ position: 'absolute', left: -5, top: 14, width: 10, height: 10, background: 'var(--dsw-alias-bg-base)', border: LN }} />
                {/* Right port: connection handle */}
                <div
                  onClick={(e) => { onPortClick(e, n.id) }}
                  style={{
                    position: 'absolute', right: -5, top: 14, width: 10, height: 10, cursor: 'crosshair',
                    background: armed ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-bg-base)',
                    border: `1px solid ${armed ? 'var(--dsw-alias-state-business-primary)' : 'var(--dsw-alias-border-l2)'}`,
                  }}
                />
              </div>
            )
          })}
        </div>

        {/* Right inspector */}
        <div style={{ flex: 'none', width: 286, borderLeft: LN, padding: '16px 18px', display: 'flex', flexDirection: 'column' }}>
          {selectedNode ? (
            <>
              <div className={bp.kicker}>Editing one step</div>
              <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
                {(['trigger', 'step', 'question', 'human'] as NodeKind[]).map((kind) => {
                  const active = selectedNode.kind === kind
                  const chipLabel = kind === 'trigger' ? 'When' : kind === 'step' ? 'Do' : kind === 'question' ? 'Check' : 'Ask a human'
                  return (
                    <span
                      key={kind}
                      onClick={() => { setKind(selectedNode.id, kind) }}
                      style={{
                        padding: '5px 9px', fontSize: 11.5, cursor: 'pointer',
                        background: active ? 'var(--dsw-alias-state-business-primary)' : 'transparent',
                        color: active ? 'var(--dsw-alias-bg-base)' : 'var(--dsw-alias-label-primary)',
                        border: active ? 'none' : LN,
                      }}
                    >
                      {chipLabel}
                    </span>
                  )
                })}
              </div>

              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', marginBottom: 8 }}>What should happen here?</div>
              <textarea
                value={selectedNode.text}
                onChange={(e) => { setText(selectedNode.id, e.target.value) }}
                style={{ minHeight: 88, padding: '9px 10px', border: LN, background: 'transparent', color: 'var(--dsw-alias-label-primary)', fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit', resize: 'vertical' }}
              />
              <div style={{ fontSize: 11, color: 'var(--dsw-alias-label-secondary)', marginTop: 6, marginBottom: 16 }}>
                Plain English is fine. Anton turns it into the actual commands and shows you what it will run before anything happens.
              </div>

              {selectedNode.kind === 'human' && (
                <div style={{ padding: '12px 13px', background: 'var(--dsw-alias-state-warn-tertiary)', marginBottom: 16 }}>
                  <div className={bp.kicker} style={{ margin: '0 0 8px', color: 'var(--dsw-alias-state-warn-label)' }}>Who has to decide</div>
                  <input
                    value={selectedNode.assignee ?? ''}
                    onChange={(e) => { setAssignee(selectedNode.id, e.target.value) }}
                    style={{ width: '100%', boxSizing: 'border-box', padding: '7px 9px', border: LN, background: 'var(--dsw-alias-bg-base)', color: 'var(--dsw-alias-label-primary)', fontSize: 12.5, fontFamily: 'inherit', marginBottom: 10 }}
                  />
                  {([
                    ['sms', 'Text message · the moment it stops'],
                    ['inbox', 'A card in Waiting on you'],
                    ['email', 'Email the office as well'],
                  ] as [('sms' | 'inbox' | 'email'), string][]).map(([channel, label]) => {
                    const on = (selectedNode.notify ?? []).includes(channel)
                    return (
                      <div key={channel} onClick={() => { toggleNotify(selectedNode.id, channel) }} style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '5px 0', fontSize: 12, cursor: 'pointer', color: on ? 'var(--dsw-alias-state-warn-label)' : 'var(--dsw-alias-label-secondary)' }}>
                        <span style={{ flex: 'none', width: 13, height: 13, border: `1px solid ${on ? 'var(--dsw-alias-state-warn-label)' : 'var(--dsw-alias-border-l2)'}`, background: on ? 'var(--dsw-alias-state-warn-label)' : 'transparent' }} />
                        {label}
                      </div>
                    )
                  })}
                  <div style={{ fontSize: 11, lineHeight: 1.4, color: 'var(--dsw-alias-state-warn-label)', marginTop: 8 }}>
                    Anton stops dead here. It will wait as long as it takes and never guess on your behalf.
                  </div>
                </div>
              )}

              <span style={{ flex: 1 }} />
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <button onClick={() => { removeNode(selectedNode.id) }} style={{ background: 'none', border: '1px solid var(--dsw-alias-state-error-primary)', color: 'var(--dsw-alias-state-error-primary)', fontSize: 12, padding: '7px 12px', cursor: 'pointer', fontFamily: 'inherit' }}>Remove this step</button>
                <button onClick={() => { setSel(null) }} style={{ background: 'var(--dsw-alias-state-business-primary)', border: 'none', color: 'var(--dsw-alias-bg-base)', fontSize: 12, padding: '7px 16px', cursor: 'pointer', fontFamily: 'inherit' }}>Done</button>
              </div>
            </>
          ) : (
            <>
              <div className={bp.kicker}>Draft provenance</div>
              <div style={{ fontSize: 12.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 16 }}>Drafted by Anton from the chat. Nothing runs until you approve it.</div>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', marginBottom: 6 }}>In plain English</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)', marginBottom: 16 }}>
                {plainEnglish === '' ? 'Add a step to describe what this automation does.' : `${plainEnglish}.`}
              </div>
              <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', marginBottom: 6 }}>People in the loop</div>
              <div style={{ fontSize: 12.5, lineHeight: 1.5, color: 'var(--dsw-alias-label-secondary)' }}>
                {gateNodes.length === 0
                  ? 'Nobody. This automation runs start to finish on its own — add an "Ask a human" step if that is too much rope.'
                  : gateNodes.map(g => g.assignee ?? 'someone').join(', ')}
              </div>
            </>
          )}
        </div>
      </div>

      <div style={{ flex: 'none', padding: '8px 18px', fontSize: 10.5, color: 'var(--dsw-alias-label-secondary)' }} className={bp.mono}>
        {linkFrom !== null
          ? 'now click the step it should run next — or click the square again to cancel'
          : `${nodes.length} steps · ${links.length} connections · ${gateNodes.length} human checkpoint${gateNodes.length === 1 ? '' : 's'}`}
      </div>

      <div style={{ flex: 'none', display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 1, background: 'var(--dsw-alias-border-l2)', borderTop: LN }}>
        {[
          { title: 'Why the gate is here', body: gateNodes.length > 0 ? 'A human step stops the run until someone confirms it should continue.' : 'No gate on this draft — it runs start to finish on its own.' },
          { title: 'What it can touch', body: 'Only the systems this automation was drafted against — nothing else.' },
          { title: 'If it fails', body: 'Anton logs the failure to memory and surfaces it in What went wrong.' },
        ].map((note, i) => (
          <div key={i} style={{ background: 'var(--dsw-alias-bg-base)', padding: '12px 14px' }}>
            <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--dsw-alias-label-primary)', marginBottom: 4 }}>{note.title}</div>
            <div style={{ fontSize: 11.5, lineHeight: 1.4, color: 'var(--dsw-alias-label-secondary)' }}>{note.body}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
