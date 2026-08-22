/** Registers the sidebar shell into the layout-owned slot. */
import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
// Type-only: pulls the locale plugin's Context merge (ctx.locale).
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type { SidebarRootInjected } from './contract/slots.ts'
import { SidebarRoot } from './SidebarRoot.tsx'
import { LiveStrip } from './LiveStrip.tsx'
import { en, zh, type SidebarKey } from './locales.ts'
import { OpsCockpit } from './OpsCockpit.tsx'
import { createNavScreenStore } from './nav-store.ts'

export type {
  SidebarBrandMarkOwnerProps, SidebarBrandNameOwnerProps, SidebarFooterActionOwnerProps,
  SidebarRootComponentProps, SidebarRootInjected, SidebarSectionOwnerProps, SidebarSettingsOwnerProps,
} from './contract/slots.ts'
export type { SidebarKey } from './locales.ts'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** Sidebar shell controls copy. */
    sidebar: SidebarKey
  }
}

/** Dictionary namespace owned by this plugin (shell controls copy). */
const NS = 'sidebar'

/** Services required by the sidebar plugin. */
export const inject = ['slots', 'layout', 'sessions', 'workspaces', 'locale']

/** Registers the sidebar shell and its service callbacks.
 * @param ctx - Client root context.
 */
export function apply(ctx: ClientContext): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'ui-sidebar: dictionaries')

  const injectProps = (): SidebarRootInjected => ({
    // The shell's New Session button rides the runtime's shared action
    // (current Session Workspace, then recent Workspace).
    startSession: (workspaceId) => { ctx.workspaces.startSession(workspaceId) },
    toggleSidebar: () => { ctx.layout.toggleSidebar() },
  })
  // Shared handle (not re-invoked per registration): the sidebar nav writes
  // the active screen, ops-cockpit reads it — same store, two occupants
  // ("Store handle... shared identity", ui-slots/src/store.d.ts).
  const navScreenStore = createNavScreenStore()
  ctx.effect(
    () => ctx.slots.register({
      name: 'sidebar',
      locale: NS,
      // The shell owns geometry; ui-workspace registers the whole browsing
      // region (header, search, session list, workspace dialogs), ui-settings
      // registers the foot trigger + settings panel.
      children: {
        'sidebar.brand.mark': { kind: 'single', scope: 'root' },
        'sidebar.brand.name': { kind: 'single', scope: 'root' },
        'sidebar.workspaces': { kind: 'single', scope: 'root' },
        'sidebar.settings': { kind: 'single', scope: 'root' },
        'sidebar.footer.action': { kind: 'list', scope: 'root' },
      },
      store: navScreenStore,
      inject: injectProps,
    }, SidebarRoot),
    'ui-sidebar: slot registration',
  )

  ctx.slots.inject('shell.rightSidebar', () => ctx.slots.register({ name: 'shell.rightSidebar', id: 'live-strip', order: 10 }, LiveStrip))

  ctx.slots.inject('shell.overlay', () => ctx.slots.register({
    name: 'shell.overlay',
    id: 'ops-cockpit',
    order: 5,
    store: navScreenStore,
  }, OpsCockpit))
}
