/**
 * Shape of a drafted automation's node graph.
 *
 * These types outlived the in-app canvas that used to draw them: Anton still
 * drafts a graph and `PUT /api/automations/{id}` still persists it, but the
 * editing surface is the operator's own n8n rather than a hand-built
 * imitation of it. Kept here, not in a screen, so nothing has to import a
 * canvas to name a node.
 */
export type NodeKind = 'trigger' | 'step' | 'question' | 'human'

export type EditorNode = {
  id: string
  kind: NodeKind
  x: number
  y: number
  text: string
  assignee?: string
  notify?: ('sms' | 'inbox' | 'email')[]
}

/** A directed edge, [fromNodeId, toNodeId]. */
export type EditorLink = [string, string]
