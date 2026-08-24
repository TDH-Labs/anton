/**
 * The apiproxy's own authz identity toward the Anton FastAPI dashboard
 * (:8799). Under authz mode every proxied request must resolve to a
 * principal — the browser only holds the auth-gate cookie, which is a
 * disjoint secret from FastAPI bearer sessions, so the proxy presents its
 * OWN scoped machine credential (minted by anton/authz/provision.py,
 * confined by guards.MACHINE_TOKEN_SCOPES["apiproxy"]). Fail-closed: when
 * no credential is available requests go out unauthenticated and are denied
 * downstream exactly as before this identity existed.
 */

import { readFileSync, statSync } from 'node:fs'
import type { IncomingHttpHeaders } from 'node:http'

interface CachedToken {
  token: string
  mtimeMs: number
}

let cachedFileToken: CachedToken | null = null

/**
 * Resolves the scoped bearer token for the :8799 hop. Preference order:
 *  1. ANTON_APIPROXY_TOKEN env var (operator-managed rotation),
 *  2. $ANTON_DATA_DIR/authz/apiproxy.token — the dashboard-provisioned
 *     file, re-read whenever its mtime changes so dashboard-side rotation
 *     is picked up without restarting this process.
 */
export function antonProxyToken(): string | null {
  const fromEnv = (process.env.ANTON_APIPROXY_TOKEN ?? '').trim()
  if (fromEnv !== '') return fromEnv

  const dataDir = process.env.ANTON_DATA_DIR
  if (!dataDir) return null
  const path = `${dataDir}/authz/apiproxy.token`
  try {
    const mtimeMs = statSync(path).mtimeMs
    if (cachedFileToken !== null && cachedFileToken.mtimeMs === mtimeMs) return cachedFileToken.token
    const token = readFileSync(path, 'utf-8').trim()
    cachedFileToken = token === '' ? null : { token, mtimeMs }
    return cachedFileToken?.token ?? null
  } catch {
    return null
  }
}

/**
 * Authorization header pair for the :8799 hop — empty when unprovisioned
 * (the downstream 401 is the fail-closed signal, never a bypass).
 */
export function antonProxyAuthorizationHeader(): Record<string, string> {
  const token = antonProxyToken()
  return token === null ? {} : { authorization: `Bearer ${token}` }
}

/**
 * Headers for forwarding a browser request to :8799 via proxyHandler: the
 * caller's headers (array values joined per RFC 9110 §5.2), with any
 * client-supplied Authorization REPLACED by the proxy's own scoped machine
 * credential. The browser's cookie/gate session and FastAPI bearers are
 * disjoint secrets by design — one must never impersonate the other.
 */
export function antonProxyForwardHeaders(reqHeaders: IncomingHttpHeaders): Record<string, string> {
  const headers: Record<string, string> = {}
  for (const [key, value] of Object.entries(reqHeaders)) {
    if (value === undefined) continue
    headers[key] = Array.isArray(value) ? value.join(', ') : value
  }
  delete headers.authorization // the proxy's identity, not the browser's
  return { ...headers, ...antonProxyAuthorizationHeader() }
}
