import type { EditorLink, EditorNode } from './automationGraph.ts'

/**
 * Shared draft plumbing for the two surfaces that create automations from a
 * model draft: the Automations screen ("Describe it" / "Upload a doc") and
 * the setup wizard's step-1 "Describe it" box (diagnose:setup-automations).
 * Both save through the same honest path — PUT /api/automations/:id with
 * state awaiting_approval — never running, never a fabricated lastRun;
 * activation stays a separate, explicit act in the row's editor.
 */

export type DraftTrigger = { kind: 'cron' | 'event' | 'interval' | null; display: string | null; expr: string | null }
export type AutomationDraft = {
  name: string
  plain: string
  trigger?: DraftTrigger
  steps: { text: string; assignee: 'agent' | 'human' | null }[]
}

export const slugify = (name: string): string =>
  name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'drafted-automation'

/** Turn a validated draft into the same node graph the "Draw it" editor
 * saves: a leading trigger node, then one node per step ("Ask a human" for
 * steps the model assigned to a person). Saved as awaiting_approval — a draft
 * is never activated on its own; turning it on stays with the row's editor. */
export function draftToNodes(draft: AutomationDraft): { nodes: EditorNode[]; links: EditorLink[] } {
  const triggerText = draft.trigger?.display || 'When you tell it to run'
  const nodes: EditorNode[] = [
    { id: 'n0', kind: 'trigger', x: 24, y: 24, text: triggerText },
    ...draft.steps.map((s, i) => ({
      id: `n${i + 1}`,
      kind: (s.assignee === 'human' ? 'human' : 'step') as EditorNode['kind'],
      x: 24 + ((i + 1) % 3) * 40,
      y: 24 + ((i + 1) % 4) * 96,
      text: s.text,
      ...(s.assignee === 'human' ? { assignee: 'you' } : {}),
    })),
  ]
  const links: EditorLink[] = nodes.slice(1).map((_, i) => [`n${i}`, `n${i + 1}`] as EditorLink)
  return { nodes, links }
}
