import type { ComponentType } from 'react'
import type { PropsStore } from '@deepseek-ai/dsh-client-ui-slots'
import type { createNavScreenStore, OpsScreen } from './nav-store.ts'
import { OpsNowScreen } from './OpsNowScreen.tsx'
import { SetupScreen } from './screens/SetupScreen.tsx'
import { ApprovalsScreen } from './screens/ApprovalsScreen.tsx'
import { AutomationsScreen } from './screens/AutomationsScreen.tsx'
import { ScheduleScreen } from './screens/ScheduleScreen.tsx'
import { MemoryScreen } from './screens/MemoryScreen.tsx'
import { LearningScreen } from './screens/LearningScreen.tsx'
import { AlertsScreen } from './screens/AlertsScreen.tsx'
import { AddonsScreen } from './screens/AddonsScreen.tsx'
import { useLiveStripUnpinned } from './responsive.ts'

/** Ops keys this component renders; 'ask' falls through to the real chat (renders null). */
const OPS_KEYS = new Set<OpsScreen>(['now', 'approvals', 'automations', 'schedule', 'memory', 'learning', 'alerts', 'addons', 'setup'])

// Static imports, not per-screen `import()`: this host's plugin loader
// (`@deepseek-ai/dsh-client-modules`) resolves each package to one prebuilt
// `client.js` via its own boot manifest — a rollup/tsdown-split runtime
// chunk that the manifest never declared fails at load time ("missed the
// module table"). No other package in this codebase uses a runtime dynamic
// import for this reason; per-screen code-splitting here would need each
// screen to be its own registered plugin package (see README Phase 4),
// which is a real, larger restructure, not a same-file fix.
const SCREENS: Partial<Record<OpsScreen, ComponentType>> = {
  now: OpsNowScreen,
  approvals: ApprovalsScreen,
  automations: AutomationsScreen,
  schedule: ScheduleScreen,
  memory: MemoryScreen,
  learning: LearningScreen,
  alerts: AlertsScreen,
  addons: AddonsScreen,
}

type OpsCockpitProps = PropsStore<ReturnType<typeof createNavScreenStore>>

/**
 * Ops shell content, registered into `shell.overlay`. The Setup wizard
 * (README §11) is the one screen the spec draws as a true full-viewport
 * modal, so it renders `position: fixed` over everything, backdrop included.
 * Every other ops screen is persistent chrome layered over the center
 * column only (README, "Screens / Views" — nav 242px | center flex-1 | live
 * strip 322px present on every screen): it reads the frame's own resolved
 * sidebar width off `--frame-sidebar-width` (AppFrame.tsx) so the nav column
 * and the 322px live strip (`shell.rightSidebar`) both stay visible and
 * clickable instead of being buried under an `inset: 0` slab.
 * When the active screen is 'ask' this renders nothing — the chat underneath
 * shows through and no DOM survives the switch.
 */
export function OpsCockpit({ useStore, actions }: OpsCockpitProps) {
  const screen = useStore(s => s.screen)
  const liveStripUnpinned = useLiveStripUnpinned()

  if (!OPS_KEYS.has(screen)) return null

  if (screen === 'setup') {
    return (
      <div style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
        background: 'rgba(29,31,32,.55)',
      }}
      >
        <SetupScreen onExit={() => { actions.setScreen('now') }} />
      </div>
    )
  }

  const Screen = SCREENS[screen]

  return (
    <div style={{
      position: 'absolute',
      top: 0,
      bottom: 0,
      left: 'var(--frame-sidebar-width, 0px)',
      // Matches the live strip's fixed width (LiveStrip.tsx) — 0 once it
      // unpins below ~1180px (README, "Responsive"), or it would leave a
      // blank 322px gap where the strip used to render.
      right: liveStripUnpinned ? 0 : 322,
      zIndex: 50,
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--dsw-alias-bg-base)',
      overflow: 'hidden',
    }}
    >
      {Screen && <Screen />}
    </div>
  )
}
