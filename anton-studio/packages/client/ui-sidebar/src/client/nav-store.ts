/**
 * Ops-nav screen-selection store (README, "State Management" — `screen`,
 * owner `ui-ops-nav` store, "a new store... following `ui-layout/src/client/
 * stores.ts` exactly"). Module level exports the factory only — a
 * module-level handle would pin the store's identity in the module cache (a
 * de-facto singleton surviving plugin reloads). apply() (index.ts)
 * constructs one handle and shares it as the `store` declaration on both the
 * sidebar nav registration (writes the active screen) and the ops-cockpit
 * registration (reads it to decide which screen renders center column).
 */
import { defineStore, type EngineStoreHandle } from '@deepseek-ai/dsh-client-runtime/client'

/** Every screen key the ops shell can route to; 'ask' is the front door (Ask Anton). */
export type OpsScreen =
  | 'ask' | 'now' | 'approvals' | 'automations' | 'schedule'
  | 'memory' | 'learning' | 'alerts' | 'addons' | 'setup'

/** Ops-nav store state: the single active center-column screen. */
type NavState = { screen: OpsScreen }

/**
 * Annotation twin of the actions literal below (the export needs a declared
 * return type); drift fails assignability at the defineStore call.
 */
type NavActions = {
  setScreen: (draft: NavState, screen: OpsScreen) => void
}

/**
 * Create the ops-nav screen store handle.
 * @returns the store handle (spec + type + identity + factory in one).
 */
export function createNavScreenStore(): EngineStoreHandle<NavState, NavActions> {
  return defineStore({
    init: (): NavState => ({ screen: 'ask' }),
    actions: {
      setScreen: (d, screen: OpsScreen) => { d.screen = screen },
    },
  })
}
