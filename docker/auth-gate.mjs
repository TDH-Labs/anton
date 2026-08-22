#!/usr/bin/env node
// anton auth-gate: the only process bound to a non-loopback interface in
// this container. dsh web itself refuses --host 0.0.0.0 (no auth/TLS/origin
// policy on that surface — an RCE-capable coding agent), so it stays on
// ANTON_WEB_INTERNAL_PORT/127.0.0.1, untouched, exactly as its own CLI
// requires. This process is the thing that's actually safe to publish: a
// cookie-session gate in front of a plain reverse proxy, no new npm
// dependencies (node:http/crypto/fs only).
//
// First-boot UX: the generated password is shown once, directly on the
// login page, until the first successful login — then never shown again.
// That's the one concession to "no log-diving for a non-technical user"
// without leaving the password visible to anyone who visits later.

import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import path from 'node:path'

const LISTEN_PORT = Number(process.env.ANTON_WEB_PORT || 3080)
const TARGET_PORT = Number(process.env.ANTON_WEB_INTERNAL_PORT || 3079)
const DATA_DIR = process.env.ANTON_DATA_DIR || '/data'

const TOKEN_PATH = path.join(DATA_DIR, 'web-token')
const CLAIMED_PATH = path.join(DATA_DIR, 'web-token-claimed')
const SESSION_SECRET_PATH = path.join(DATA_DIR, 'web-session-secret')

function readOrCreate(filePath, generate) {
  try {
    const existing = fs.readFileSync(filePath, 'utf8').trim()
    if (existing) return existing
  } catch { /* not created yet */ }
  const value = generate()
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, value, { mode: 0o600 })
  return value
}

const TOKEN = process.env.ANTON_WEB_TOKEN || readOrCreate(TOKEN_PATH, () => crypto.randomBytes(9).toString('base64url'))
const SESSION_SECRET = readOrCreate(SESSION_SECRET_PATH, () => crypto.randomBytes(32).toString('hex'))

function isClaimed() {
  return fs.existsSync(CLAIMED_PATH)
}

function markClaimed() {
  try { fs.writeFileSync(CLAIMED_PATH, new Date().toISOString()) } catch { /* best-effort */ }
}

// Rate limiting on login attempts: defense in depth, not the primary
// protection -- the generated password itself is 9 random bytes (72 bits),
// already infeasible to brute-force. In-memory, per-source-IP, resets on a
// container restart; that's an acceptable tradeoff for a single-tenant
// small-business install, not something worth a persistent store for.
const MAX_ATTEMPTS = 5
const LOCKOUT_MS = 15 * 60 * 1000
const attemptWindow = new Map() // ip -> { count, lockedUntil }

function clientIp(req) {
  return req.socket.remoteAddress || 'unknown'
}

function isLockedOut(ip) {
  const entry = attemptWindow.get(ip)
  return entry !== undefined && entry.lockedUntil !== null && entry.lockedUntil > Date.now()
}

function recordFailedAttempt(ip) {
  const entry = attemptWindow.get(ip) || { count: 0, lockedUntil: null }
  entry.count += 1
  if (entry.count >= MAX_ATTEMPTS) {
    entry.lockedUntil = Date.now() + LOCKOUT_MS
    entry.count = 0
  }
  attemptWindow.set(ip, entry)
}

function recordSuccessfulLogin(ip) {
  attemptWindow.delete(ip)
}

function timingSafeEqualStr(a, b) {
  const bufA = Buffer.from(a)
  const bufB = Buffer.from(b)
  if (bufA.length !== bufB.length) return false
  return crypto.timingSafeEqual(bufA, bufB)
}

function sessionMac() {
  return crypto.createHmac('sha256', SESSION_SECRET).update(TOKEN).digest('hex')
}

function hasValidSession(req) {
  const cookie = req.headers.cookie || ''
  const match = /(?:^|;\s*)anton_session=([a-f0-9]+)/.exec(cookie)
  if (!match) return false
  return timingSafeEqualStr(match[1], sessionMac())
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}

// Matches the Ops Center's own "blueprint" design system (anton-platform.css's
// --dsw-alias-* tokens, blueprint.module.css's kicker/hairline/registration-mark
// motif) so this — the actual first pixel a new user sees — isn't a third,
// unrelated visual identity in the same login-to-dashboard journey. Values are
// copied literally (not @import'd) since this page renders before any session
// exists and can't rely on the upstream app's own stylesheet being reachable
// through the not-yet-authenticated proxy.
const corner = pos => `<span class="corner corner-${pos}"></span>`

function loginPage({ error, lockedOut }) {
  const passwordBlock = isClaimed() ? '' : `
    <div class="pw blueprint">
      ${corner('tl')}${corner('tr')}${corner('bl')}${corner('br')}
      <div class="pw-label">First time here — your password</div>
      <div class="pw-value">${escapeHtml(TOKEN)}</div>
      <div class="pw-note">Shown once. After you log in, this page won't show it again — write it down or use a password manager.</div>
    </div>`
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>Anton</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg-base: #f2f2f3; --label-primary: #1d1f20; --label-secondary: rgba(29,31,32,.55);
    --border-l2: rgba(29,31,32,.16); --registration-mark: rgba(29,31,32,.5);
    --business-primary: #5980a6; --accent-strong: #416180;
    --warn-label: #8a5a10; --warn-tertiary: rgba(245,158,11,.16);
    --error-primary: #a6452f; --hover: rgba(29,31,32,.05);
  }
  * { box-sizing: border-box; }
  body {
    font-family: 'Barlow', system-ui, sans-serif; background: var(--bg-base);
    color: var(--label-primary); max-width: 380px; margin: 14vh auto 0; padding: 0 20px;
  }
  h1 {
    font-family: 'Barlow Condensed', system-ui, sans-serif; font-weight: 600;
    font-size: 32px; line-height: 1; margin: 0 0 6px;
  }
  .kicker {
    font-size: 10px; letter-spacing: .14em; text-transform: uppercase;
    color: var(--business-primary); margin-bottom: 4px;
  }
  .sub { color: var(--label-secondary); font-size: 14px; margin-bottom: 28px; }
  .blueprint { position: relative; border: 1px solid var(--border-l2); border-radius: 0; }
  .corner { position: absolute; width: 11px; height: 11px; }
  .corner::before, .corner::after { content: ''; position: absolute; background: var(--registration-mark); }
  .corner::before { left: 5px; top: 0; width: 1px; height: 100%; }
  .corner::after { top: 5px; left: 0; width: 100%; height: 1px; }
  .corner-tl { top: -6px; left: -6px; } .corner-tr { top: -6px; right: -6px; }
  .corner-bl { bottom: -6px; left: -6px; } .corner-br { bottom: -6px; right: -6px; }
  .pw { background: var(--warn-tertiary); padding: 16px; margin-bottom: 20px; }
  .pw-label { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--warn-label); margin-bottom: 8px; }
  .pw-value { font-family: ui-monospace, Menlo, monospace; font-size: 17px; font-weight: 600; letter-spacing: .02em; }
  .pw-note { font-size: 12px; color: var(--warn-label); margin-top: 10px; line-height: 1.5; }
  .err { color: var(--error-primary); font-size: 13.5px; margin-bottom: 14px; }
  form { border: 1px solid var(--border-l2); border-radius: 0; padding: 20px; background: #fff; }
  input {
    width: 100%; padding: 11px 12px; margin-bottom: 14px; font-size: 16px;
    font-family: inherit; color: var(--label-primary);
    border: 1px solid var(--border-l2); border-radius: 0; background: var(--bg-base);
  }
  input:focus { outline: none; border-color: var(--business-primary); }
  button {
    width: 100%; padding: 12px; font-family: inherit; font-size: 14px; font-weight: 500;
    letter-spacing: .02em; border: none; border-radius: 0; background: var(--business-primary);
    color: #fff; cursor: pointer;
  }
  button:hover { background: var(--accent-strong); }
</style></head>
<body>
  <div class="kicker">Anton</div>
  <h1>Ops Center</h1>
  <div class="sub">Sign in to continue.</div>
  ${passwordBlock}
  ${error ? '<div class="err">Incorrect password.</div>' : ''}
  ${lockedOut
    ? '<div class="err">Too many attempts — try again in a few minutes.</div>'
    : `<form method="POST" action="/__anton_login">
    <input type="password" name="password" placeholder="Password" autofocus required>
    <button type="submit">Log in</button>
  </form>`}
</body></html>`
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    req.on('data', c => chunks.push(c))
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

function proxyThrough(req, res) {
  const proxyReq = http.request({
    host: '127.0.0.1',
    port: TARGET_PORT,
    path: req.url,
    method: req.method,
    headers: req.headers,
  }, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers)
    proxyRes.pipe(res)
  })
  proxyReq.on('error', () => {
    res.writeHead(502, { 'Content-Type': 'text/plain' })
    res.end('anton auth-gate: upstream unavailable')
  })
  req.pipe(proxyReq, { end: true })
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'POST' && req.url === '/__anton_login') {
    const ip = clientIp(req)
    if (isLockedOut(ip)) {
      res.writeHead(429, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(loginPage({ error: false, lockedOut: true }))
      return
    }
    const body = await readBody(req)
    const submitted = new URLSearchParams(body).get('password') || ''
    if (timingSafeEqualStr(submitted, TOKEN)) {
      recordSuccessfulLogin(ip)
      markClaimed()
      res.writeHead(302, {
        Location: '/',
        'Set-Cookie': `anton_session=${sessionMac()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000`,
      })
      res.end()
    } else {
      recordFailedAttempt(ip)
      res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' })
      res.end(loginPage({ error: true, lockedOut: isLockedOut(ip) }))
    }
    return
  }

  if (!hasValidSession(req)) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    res.end(loginPage({ error: false, lockedOut: isLockedOut(clientIp(req)) }))
    return
  }

  proxyThrough(req, res)
})

// dsh's live event transport (/api/events.mux, /api/events.host) is a real
// WebSocket upgrade, discovered live (the blanket socket.destroy() this
// replaced broke it silently — no HTTP error, just a failed WS connection
// in the browser console). Same session-cookie gate as the plain HTTP path,
// then raw two-way piping to the upstream: an upgrade never reaches
// http.createServer's request handler, so it needs its own auth check here.
server.on('upgrade', (req, clientSocket, head) => {
  if (!hasValidSession(req)) {
    clientSocket.destroy()
    return
  }
  const upstream = net.connect(TARGET_PORT, '127.0.0.1', () => {
    const requestLine = `${req.method} ${req.url} HTTP/1.1\r\n`
    const headerLines = Object.entries(req.headers)
      .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
      .join('\r\n')
    upstream.write(`${requestLine}${headerLines}\r\n\r\n`)
    if (head && head.length > 0) upstream.write(head)
    upstream.pipe(clientSocket)
    clientSocket.pipe(upstream)
  })
  upstream.on('error', () => { clientSocket.destroy() })
  clientSocket.on('error', () => { upstream.destroy() })
})

server.listen(LISTEN_PORT, '0.0.0.0', () => {
  console.log(`anton auth-gate: 0.0.0.0:${LISTEN_PORT} -> 127.0.0.1:${TARGET_PORT}`)
})
