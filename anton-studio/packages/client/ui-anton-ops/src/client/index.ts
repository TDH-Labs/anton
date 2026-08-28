/**
 * Anton Ops Center — first-party product UI, slot-registered (never edits
 * vendored harness files). Owns: the Ops cockpit (`shell.overlay`), the
 * live strip (`shell.rightSidebar`), the Ops nav groups (`sidebar.nav`),
 * Anton branding (the generic `sidebar.brand.*` seats — a deployment has
 * exactly one brand, so ui-brand-official is dropped from the roster), and
 * the Son-of-Anton footer actions (`sidebar.footer.action`).
 *
 * The nav-screen store handle is constructed here once and declared on both
 * the nav seat and the cockpit overlay registrations, so a sidebar nav click
 * drives the center-column screen (same store, two occupants).
 */
import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
import type {} from '@deepseek-ai/dsh-client-locale/client'
// Type-only: pulls ui-layout's SlotMap merge ('shell.overlay',
// 'shell.rightSidebar') into this program so PropsRuntime/slot keys resolve.
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
// Type-only: pulls the settings shell's SlotMap merge ('settings.section')
// into this program. Cross-plugin collaboration goes through the shared
// slot, never a value import (client bundle purity gate).
import type {} from '@deepseek-ai/dsh-client-ui-settings/client'
import { createNavScreenStore } from '@deepseek-ai/dsh-client-ui-sidebar/client'
import { LiveStrip } from './LiveStrip.tsx'
import { N8nSettingsSection } from './N8nSettingsSection.tsx'
import { OpsCockpit } from './OpsCockpit.tsx'
import { OpsNav } from './OpsNav.tsx'
import { AntonBrandMark, AntonBrandName, AntonFooterActions } from './Sidebar.tsx'

/** Services required by this plugin. */
export const inject = ['slots']

/**
 * Register every Anton Ops occupant into the harness slots.
 * @param ctx - Client root context.
 */
export function apply(ctx: ClientContext): void {
  // One handle, shared by the nav seat (writes the active screen) and the
  // cockpit overlay (reads it to pick the center-column screen).
  const navScreenStore = createNavScreenStore()

  ctx.slots.inject('shell.overlay', () => ctx.slots.register({
    name: 'shell.overlay',
    id: 'ops-cockpit',
    order: 5,
    store: navScreenStore,
  }, OpsCockpit))

  ctx.slots.inject('shell.rightSidebar', () => ctx.slots.register({
    name: 'shell.rightSidebar',
    id: 'ops-live-strip',
    order: 10,
  }, LiveStrip))

  // Sidebar seats — Anton branding (declared generic by ui-sidebar's shell).
  ctx.slots.inject('sidebar.brand.mark', () => ctx.slots.register({
    name: 'sidebar.brand.mark',
  }, AntonBrandMark))

  ctx.slots.inject('sidebar.brand.name', () => ctx.slots.register({
    name: 'sidebar.brand.name',
  }, AntonBrandName))

  ctx.slots.inject('sidebar.nav', () => ctx.slots.register({
    name: 'sidebar.nav',
    store: navScreenStore,
  }, OpsNav))

  ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
    name: 'sidebar.footer.action',
    id: 'ops-footer',
    order: 30,
    store: navScreenStore,
  }, AntonFooterActions))

  // n8n connection settings. No shared inject face -- the section fetches
  // its own state directly from dashboard.py, same as every other Ops
  // Center screen (useOpsApi), rather than joining the Host settings-
  // document system that ui-settings-models/-plugins use: n8n's base URL
  // lives in Anton's own config.yaml, not a cordis plugin's settings scope.
  ctx.slots.inject('settings.section', () => ctx.slots.register({
    name: 'settings.section',
    id: 'n8n',
    order: 20,
    label: () => 'n8n',
  }, N8nSettingsSection))
}