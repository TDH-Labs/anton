/**
 * The apiproxy's scoped machine-credential helper (anton-auth.ts): token
 * resolution order, mtime-based rotation pickup, and header forwarding
 * that REPLACES any client-supplied Authorization with the proxy's own
 * identity — the browser's gate cookie must never masquerade as a FastAPI
 * bearer.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { mkdtempSync, mkdirSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { antonProxyAuthorizationHeader, antonProxyForwardHeaders, antonProxyToken } from '../src/anton-auth.ts'

let dataDir: string

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), 'anton-auth-spec-'))
  mkdirSync(join(dataDir, 'authz'), { recursive: true })
})

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true })
  delete process.env.ANTON_APIPROXY_TOKEN
  delete process.env.ANTON_DATA_DIR
})

describe('antonProxyToken', () => {
  it('returns null when nothing is provisioned', () => {
    expect(antonProxyToken()).toBeNull()
  })

  it('prefers ANTON_APIPROXY_TOKEN over the file', () => {
    process.env.ANTON_DATA_DIR = dataDir
    writeFileSync(join(dataDir, 'authz', 'apiproxy.token'), 'amt_file-token')
    process.env.ANTON_APIPROXY_TOKEN = 'amt_env-token'
    expect(antonProxyToken()).toBe('amt_env-token')
    delete process.env.ANTON_APIPROXY_TOKEN
    expect(antonProxyToken()).toBe('amt_file-token')
  })

  it('reads the dashboard-provisioned file under ANTON_DATA_DIR', () => {
    process.env.ANTON_DATA_DIR = dataDir
    expect(antonProxyToken()).toBeNull()
    writeFileSync(join(dataDir, 'authz', 'apiproxy.token'), 'amt_token-1\n')
    // cache is mtime-guarded: same content visible immediately after write
    expect(antonProxyToken()).toBe('amt_token-1')
  })

  it('picks up rotation when the file mtime changes', () => {
    process.env.ANTON_DATA_DIR = dataDir
    const path = join(dataDir, 'authz', 'apiproxy.token')
    writeFileSync(path, 'amt_old')
    expect(antonProxyToken()).toBe('amt_old')
    writeFileSync(path, 'amt_new')
    const future = new Date(Date.now() + 5_000)
    utimesSync(path, future, future)
    expect(antonProxyToken()).toBe('amt_new')
  })
})

describe('antonProxyAuthorizationHeader', () => {
  it('is empty fail-closed pair when unprovisioned', () => {
    expect(antonProxyAuthorizationHeader()).toEqual({})
  })

  it('carries the scoped bearer once provisioned', () => {
    process.env.ANTON_APIPROXY_TOKEN = 'amt_scoped'
    expect(antonProxyAuthorizationHeader()).toEqual({ authorization: 'Bearer amt_scoped' })
  })
})

describe('antonProxyForwardHeaders', () => {
  it('forwards caller headers but replaces Authorization with the proxy identity', () => {
    process.env.ANTON_APIPROXY_TOKEN = 'amt_proxy'
    const out = antonProxyForwardHeaders({
      'content-type': 'application/json',
      cookie: 'anton_session=gate-cookie-value',
      authorization: 'Bearer browser-supplied',
      'x-multi': ['a', 'b'],
    })
    expect(out.authorization).toBe('Bearer amt_proxy')
    expect(out['content-type']).toBe('application/json')
    expect(out.cookie).toBe('anton_session=gate-cookie-value')
    expect(out['x-multi']).toBe('a, b')
  })

  it('strips a client Authorization entirely when unprovisioned', () => {
    const out = antonProxyForwardHeaders({ authorization: 'Bearer browser-supplied' })
    expect(out.authorization).toBeUndefined()
  })
})
