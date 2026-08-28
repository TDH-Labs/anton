/**
 * @deepseek-ai/dsh-host-apiproxy — the API gateway every client shape shares:
 * the ApiProxy contract (api/: types + zod schemas, browser-safe), the fetch
 * carrier pair (fetch/: toFetchHandler on the host side, AbstractApiClient +
 * platform subclasses on the client side), and the host-side implementation
 * (api-proxy.ts: createApiProxy + the ApiProxyService gateway plugin providing
 * `ctx.apiProxy`). Transport-agnostic by design: this package registers no
 * routes — physical carriers wrap `ctx.apiProxy` themselves.
 *
 * The gateway consumes `ctx.agentDefaultModel`, the transport-independent default
 * shared with direct entry points. Switching models persists through that
 * service; sessions that have already logged a selection remain unchanged.
 */

import type { IncomingMessage, ServerResponse } from 'node:http'
import { Context, Service } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import type {} from '@deepseek-ai/dsh-agent-default-model'
import type {} from '@deepseek-ai/dsh-host-webserver'
import type { ApiProxy, RpcRequest } from './api/index.ts'
import { createApiProxy, DEFAULT_COLD_BLANK_PROBE_MAX_BYTES } from './api-proxy.ts'
import { antonProxyAuthorizationHeader, antonProxyForwardHeaders } from './anton-auth.ts'
import {
  DEFAULT_SESSION_LOG_COMPRESSION_LEVEL,
  type SessionLogCompressionLevel,
} from './session-export.ts'

export type * from './api/index.ts'
export { RpcId } from './api/rpc.ts'
export { toFetchHandler } from './fetch/handler.ts'
export { AbstractApiClient, InProcessApiClient } from './fetch/client.ts'
export type { IApiClient } from './fetch/client.ts'
export { createApiProxy } from './api-proxy.ts'
export type { ApiProxyDefaults } from './api-proxy.ts'

declare module '@deepseek-ai/cordis' {
  interface Context {
    /** The host-side ApiProxy implementation (the transport-agnostic gateway face). */
    apiProxy: ApiProxy
  }
}

/** Gateway plugin configuration. */
export interface Config {
  /**
   * Whether this deployment can hand paths to a native desktop opener —
   * the `hasDocument` capability the agent-preset roster reports. Absent,
   * the platform is asked (macOS/Windows/WSL yes; Linux only with a display
   * server); set it explicitly where detection misleads, e.g. `false` in a
   * container whose DISPLAY points nowhere a user can see.
   */
  nativeOpen?: boolean
  /**
   * DEFLATE level for every session-log ZIP entry: `0` stores without
   * compression, `1` favors CPU/latency, and `9` favors archive size.
   * @default 6
   */
  sessionExportCompressionLevel?: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9
  /**
   * Maximum physical size of a cold Session artifact eligible for blankness
   * verification. Zero disables probes.
   * @default 1024
   */
  coldBlankProbeMaxBytes?: number
}

/**
 * The API gateway service: implements the ApiProxy contract over the composed
 * host context and provides it as `ctx.apiProxy`. The Host cwd is the default
 * project directory.
 */
import { AntonFastApiAdapter } from './anton-bridge.ts'

export class ApiProxyService extends Service implements ApiProxy {
  static inject = [
    'agentDefaultModel', 'agents', 'attachments', 'directoryPicker', 'llm', 'sessions', 'subagents', 'sessionQuery',
    'tools', 'userQuestions', 'workspaceRegistry', 'webServer',
  ]

  static Config: z<Config> = z.object({
    nativeOpen: z.boolean(),
    sessionExportCompressionLevel: z.number().step(1).min(0).max(9)
      .default(DEFAULT_SESSION_LOG_COMPRESSION_LEVEL) as z<SessionLogCompressionLevel>,
    coldBlankProbeMaxBytes: z.natural().default(DEFAULT_COLD_BLANK_PROBE_MAX_BYTES),
  })

  readonly sessions: ApiProxy['sessions']
  readonly subagents: ApiProxy['subagents']
  readonly workspace: ApiProxy['workspace']
  readonly host: ApiProxy['host']
  readonly goals: ApiProxy['goals']
  readonly skills: ApiProxy['skills']
  readonly agentPresets: ApiProxy['agentPresets']
  readonly settings: ApiProxy['settings']
  readonly credentials: ApiProxy['credentials']
  readonly llm: ApiProxy['llm']
  readonly events: ApiProxy['events']
  readonly downloads: ApiProxy['downloads']
  readonly respond: ApiProxy['respond']

  constructor(ctx: Context, config: Config) {
    super(ctx, 'apiProxy')

    ctx.llm.registerAdapter(['anton'], new AntonFastApiAdapter())
    ctx.llm.registerConfigurableProviders([
      { provider: 'anton', displayName: 'Anton', settingsNs: 'anton', settingsPath: [] },
    ])

    // Reverse-proxies to the anton/ Python backend (dashboard.py +
    // ops_api.py), FastAPI on :8799. Node's global fetch needs a body cast
    // (IncomingMessage isn't a structural BodyInit) and the response body
    // arrives as an async-iterable stream, not a typed ReadableStream.
    // `duplex: 'half'` is required whenever body is a stream (undici throws
    // "RequestInit: duplex option is required when sending a body"
    // otherwise) — every non-GET/HEAD request here streams the client's
    // IncomingMessage straight through, so it always applies.
    const proxyHandler = async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
      try {
        const url = new URL(req.url ?? '/', 'http://localhost')
        const targetUrl = `http://localhost:8799${url.pathname}${url.search}`
        const method = req.method ?? 'GET'
        const hasBody = !['GET', 'HEAD'].includes(method)
        // The browser carries only the auth-gate cookie — no FastAPI bearer —
        // so forward with the proxy's OWN scoped machine credential
        // (anton-auth.ts). Fail-closed downstream when unprovisioned.
        const targetRes = await globalThis.fetch(targetUrl, {
          method,
          headers: antonProxyForwardHeaders(req.headers),
          body: hasBody ? (req as unknown as BodyInit) : null,
          ...hasBody && { duplex: 'half' },
        })
        res.writeHead(targetRes.status, Object.fromEntries(targetRes.headers.entries()))
        if (targetRes.body) {
          for await (const chunk of targetRes.body as unknown as AsyncIterable<Uint8Array>) res.write(chunk)
        }
        res.end()
      } catch (err) {
        res.writeHead(500)
        res.end(String(err))
      }
    }

    ctx.inject(['webServer'], (ctx2: Context) => {
      ctx2.webServer.register({ kind: 'prefix', path: '/api/mode', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/vault', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/wizard', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'exact', path: '/api/logo', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'exact', path: '/api/logo/son-of-anton', handler: proxyHandler })
      // Ops Center backend routes (anton/dashboard.py + anton/ops_api.py) —
      // these existed server-side (initiatives/jobs/approvals) or were
      // added (systems/agent/learning/incidents/automations/setup) to match
      // the design handoff's Data Contracts, but were never forwarded here.
      ctx2.webServer.register({ kind: 'exact', path: '/api/initiatives', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'exact', path: '/api/jobs', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/approvals', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/systems', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/agent', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'exact', path: '/api/learning', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'exact', path: '/api/incidents', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/automations', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'exact', path: '/api/setup', handler: proxyHandler })
      // Add-ons connectors (dashboard.py /api/connections/* + the Composio/
      // Nango bridge surfaces /api/integrations/*). Without these forwards
      // the browser's catalog fetch 404s and Add-ons shows no connector grid.
      // The matching machine-token scopes live in anton/authz/guards.py —
      // keep the two lists in lockstep (see test_ci_t_cred_apiproxy.py).
      ctx2.webServer.register({ kind: 'prefix', path: '/api/connections', handler: proxyHandler })
      ctx2.webServer.register({ kind: 'prefix', path: '/api/integrations', handler: proxyHandler })
      // n8n connection settings (dashboard.py GET/POST /api/n8n/config) --
      // without this the Automations screen's "not connected" notice and the
      // Settings n8n section both 404 at this Node layer before ever
      // reaching Python, masquerading as "not configured".
      ctx2.webServer.register({ kind: 'prefix', path: '/api/n8n', handler: proxyHandler })
    })

    const api = createApiProxy(ctx, {
      defaultModelSelection: () => ctx.agentDefaultModel.currentSelection(),
      saveDefaultModelSelection: selection => ctx.agentDefaultModel.saveSelection(selection),
      cwd: process.cwd(),
      ...config.nativeOpen === undefined ? {} : { canOpenPath: () => config.nativeOpen as boolean },
      ...(config.sessionExportCompressionLevel === undefined
        ? {}
        : { sessionExportCompressionLevel: config.sessionExportCompressionLevel }),
      ...(config.coldBlankProbeMaxBytes === undefined
        ? {}
        : { coldBlankProbeMaxBytes: config.coldBlankProbeMaxBytes }),
    })
    this.sessions = api.sessions
    this.subagents = api.subagents
    this.workspace = api.workspace
    this.host = api.host
    this.goals = api.goals
    this.skills = api.skills
    this.agentPresets = api.agentPresets
    this.settings = api.settings
    this.credentials = api.credentials
    this.llm = api.llm
    this.events = api.events
    this.downloads = api.downloads
    // createApiProxy returns closures (no `this` capture), so the bind is
    // behavior-neutral.
    this.respond = api.respond.bind(api)

    const originalSettingsUpdate = this.settings.update.bind(this.settings)
    this.settings.update = async (request: RpcRequest<{ ns: string; patch: object; expectedRevision?: number }>) => {
      globalThis.fetch('http://localhost:8799/api/wizard/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...antonProxyAuthorizationHeader() },
        body: JSON.stringify(request.payload.patch),
      }).catch((err: unknown) => { ctx.logger.error('Failed to sync settings to Anton', err) })

      return originalSettingsUpdate(request)
    }
  }
}

export default ApiProxyService
