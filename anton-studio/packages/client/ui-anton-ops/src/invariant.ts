/**
 * Package-owned invariant companion for `@deepseek-ai/dsh-client-ui-anton-ops`.
 * @module @deepseek-ai/dsh-client-ui-anton-ops/invariant
 */

import type { Context } from '@deepseek-ai/cordis'
import type { InvariantInstaller } from '@deepseek-ai/dsh-invariants'

/** Cordis companion plugin name. */
export const name = 'ui-anton-ops-invariant'
/** Services required before the companion can register. */
export const inject = ['invariants']

/** No runtime invariant: the Ops Center owns no relationship the harness does
 * not already pin through slot-kind and store-scope validation. */
const install: InvariantInstaller = () => {}

/**
 * Register the intentionally empty invariant contribution.
 * @param ctx - Cordis context carrying the invariant service.
 */
export const apply = (ctx: Context): Promise<() => void> =>
  Promise.resolve(ctx.invariants.register(name, install))