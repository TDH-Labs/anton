/**
 * The Ops Center's screen list and the shell's active-screen state.
 *
 * Replaces the vendored harness's slot-registered nav store: one component
 * tree owns the screen now, so a plain useState in App is the whole
 * mechanism. Screen ids are the URL hash, so a reload and a bookmark both
 * land where the operator left off.
 */

export type ScreenId =
  | 'right-now'
  | 'approvals'
  | 'alerts'
  | 'automations'
  | 'schedule'
  | 'memory'
  | 'learning'
  | 'addons'
  | 'settings'
  | 'setup'

/** One nav row. `group` is the small-caps heading it sits under. */
export interface NavEntry {
  id: ScreenId
  label: string
  group: 'watch' | 'run' | 'know' | 'setup'
}

/**
 * Plain-English labels, matching the product's existing voice: a screen is
 * named for what the operator wants ("What went wrong"), not for the table
 * behind it.
 */
export const NAV: NavEntry[] = [
  { id: 'right-now', label: 'Right now', group: 'watch' },
  { id: 'approvals', label: 'Waiting on you', group: 'watch' },
  { id: 'alerts', label: 'What went wrong', group: 'watch' },
  { id: 'automations', label: 'Automations', group: 'run' },
  { id: 'schedule', label: 'Schedule', group: 'run' },
  { id: 'memory', label: 'Memory', group: 'know' },
  { id: 'learning', label: 'Learning', group: 'know' },
  { id: 'addons', label: 'Add-ons', group: 'setup' },
  { id: 'settings', label: 'Settings', group: 'setup' },
]

export const GROUP_LABEL: Record<NavEntry['group'], string> = {
  watch: 'Watch',
  run: 'Run',
  know: 'Know',
  setup: 'Set up',
}

const IDS = new Set<string>([...NAV.map(e => e.id), 'setup'])

/** The screen named by the current URL hash, or Right Now. */
export function screenFromHash(): ScreenId {
  const raw = window.location.hash.replace(/^#\/?/, '')
  return IDS.has(raw) ? (raw as ScreenId) : 'right-now'
}
