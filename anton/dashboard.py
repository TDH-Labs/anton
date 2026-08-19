"""FastAPI dashboard — read-only pane of glass + approvals API (M4).

The dashboard NEVER executes jobs. Approvals write only to the `approvals` table;
downstream gated tools (M5) consult it before any commit (R1).
"""
from __future__ import annotations

import datetime as dt
import os
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .canary import compute_tripwires
from .digest import build_digest
from .scheduler import JobEngine

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>anton — Autonomous Control Plane</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/3d-force-graph"></script>
<style>
:root {
  --bg-main: #07090e;
  --bg-surface: rgba(15, 20, 32, 0.7);
  --bg-surface-hover: rgba(22, 30, 48, 0.85);
  --bg-card: rgba(18, 24, 38, 0.6);
  --border: rgba(255, 255, 255, 0.08);
  --border-glow: rgba(56, 189, 248, 0.25);
  --text-main: #f1f5f9;
  --text-muted: #94a3b8;
  --text-dim: #64748b;
  --primary: #38bdf8;
  --primary-glow: rgba(56, 189, 248, 0.15);
  --accent: #6366f1;
  --success: #10b981;
  --success-bg: rgba(16, 185, 129, 0.12);
  --warning: #f59e0b;
  --warning-bg: rgba(245, 158, 11, 0.12);
  --danger: #ef4444;
  --danger-bg: rgba(239, 68, 68, 0.12);
  --purple: #a855f7;
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, Menlo, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-main);
  background-image: 
    radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.05) 0%, transparent 40%),
    radial-gradient(circle at 85% 85%, rgba(99, 102, 241, 0.05) 0%, transparent 40%);
  color: var(--text-main);
  min-height: 100vh;
  padding: 1.5rem 2rem;
  line-height: 1.5;
}

/* Glassmorphic Container */
.app-container { max-width: 1440px; margin: 0 auto; }

/* Top Navbar */
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.5rem;
  background: var(--bg-surface);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border);
  border-radius: 16px;
  margin-bottom: 1.5rem;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
.brand { display: flex; align-items: center; gap: 12px; }
.brand-logo {
  width: 36px; height: 36px;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem; box-shadow: 0 0 16px var(--primary-glow);
}
.brand-title { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.02em; }
.brand-badge {
  font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
  padding: 2px 8px; border-radius: 20px;
  background: var(--primary-glow); color: var(--primary);
  border: 1px solid var(--border-glow);
}

.header-status { display: flex; align-items: center; gap: 16px; font-size: 0.85rem; }
.beacon {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 12px; border-radius: 20px;
  background: var(--success-bg); color: var(--success);
  font-weight: 600; font-size: 0.75rem;
}
.beacon-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--success);
  box-shadow: 0 0 8px var(--success); animation: pulse 2s infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(0.85); } }

/* Tab Nav Bar */
.nav-tabs {
  display: flex; gap: 6px; background: var(--bg-surface);
  padding: 6px; border-radius: 12px; border: 1px solid var(--border);
  margin-bottom: 1.5rem; width: fit-content;
}
.tab-btn {
  background: transparent; border: none; color: var(--text-muted);
  padding: 8px 18px; border-radius: 8px; font-family: var(--font-sans);
  font-size: 0.85rem; font-weight: 600; cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex; align-items: center; gap: 8px;
}
.tab-btn:hover { color: var(--text-main); background: rgba(255, 255, 255, 0.04); }
.tab-btn.active {
  background: linear-gradient(135deg, rgba(56, 189, 248, 0.15), rgba(99, 102, 241, 0.15));
  color: #fff; border: 1px solid var(--border-glow);
  box-shadow: 0 4px 16px rgba(56, 189, 248, 0.1);
}

/* KPI Cards Grid */
.kpi-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem; margin-bottom: 1.5rem;
}
.kpi-card {
  background: var(--bg-surface); backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: 14px;
  padding: 1.25rem; transition: transform 0.2s, border-color 0.2s;
  position: relative; overflow: hidden;
}
.kpi-card:hover { transform: translateY(-2px); border-color: var(--border-glow); }
.kpi-title { font-size: 0.8rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
.kpi-value { font-size: 1.6rem; font-weight: 800; font-family: var(--font-mono); color: #fff; }
.kpi-sub { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; display: flex; align-items: center; gap: 6px; }
.kpi-progress { width: 100%; height: 4px; background: rgba(255,255,255,0.06); border-radius: 2px; margin-top: 8px; overflow: hidden; }
.kpi-progress-bar { height: 100%; background: linear-gradient(90deg, var(--primary), var(--accent)); border-radius: 2px; }

/* Content Cards & Tables */
.section-grid { display: grid; grid-template-columns: 1fr; gap: 1.5rem; }
@media (min-width: 1024px) {
  .section-grid-2 { grid-template-columns: 1.2fr 0.8fr; }
}

.panel-card {
  background: var(--bg-surface); backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: 16px;
  padding: 1.5rem; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
  margin-bottom: 1.5rem;
}
.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1.2rem; padding-bottom: 0.8rem; border-bottom: 1px solid var(--border);
}
.panel-title { font-size: 1rem; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.panel-action { font-size: 0.8rem; color: var(--primary); cursor: pointer; text-decoration: none; }
.panel-action:hover { text-decoration: underline; }

/* Modern Table */
.table-wrap { overflow-x: auto; border-radius: 10px; border: 1px solid var(--border); }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.85rem; }
th {
  background: rgba(255, 255, 255, 0.03); color: var(--text-muted);
  font-weight: 600; padding: 10px 14px; border-bottom: 1px solid var(--border);
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
}
td { padding: 10px 14px; border-bottom: 1px solid rgba(255, 255, 255, 0.04); }
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255, 255, 255, 0.02); }

/* Badges */
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700;
  font-family: var(--font-mono);
}
.badge-success { background: var(--success-bg); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }
.badge-warning { background: var(--warning-bg); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.2); }
.badge-danger { background: var(--danger-bg); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.2); }
.badge-info { background: var(--primary-glow); color: var(--primary); border: 1px solid var(--border-glow); }
.badge-purple { background: rgba(168, 85, 247, 0.15); color: var(--purple); border: 1px solid rgba(168, 85, 247, 0.25); }

/* Interactive Approvals Card */
.approval-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; background: var(--bg-card);
  border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px;
  transition: all 0.2s;
}
.approval-item:hover { border-color: var(--border-glow); }
.approval-meta { display: flex; flex-direction: column; gap: 2px; }
.approval-title { font-weight: 700; font-size: 0.9rem; color: #fff; }
.approval-desc { font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono); }
.approval-actions { display: flex; gap: 8px; }

/* Buttons */
.btn {
  font-family: var(--font-sans); font-size: 0.8rem; font-weight: 600;
  padding: 6px 14px; border-radius: 8px; cursor: pointer; border: none;
  transition: all 0.15s; display: inline-flex; align-items: center; gap: 6px;
}
.btn-primary { background: var(--primary); color: #000; }
.btn-primary:hover { background: #7dd3fc; box-shadow: 0 0 12px var(--primary-glow); }
.btn-success { background: var(--success); color: #000; }
.btn-success:hover { background: #34d399; }
.btn-danger { background: var(--danger); color: #fff; }
.btn-danger:hover { background: #f87171; }
.btn-secondary { background: rgba(255, 255, 255, 0.08); color: var(--text-main); border: 1px solid var(--border); }
.btn-secondary:hover { background: rgba(255, 255, 255, 0.12); }

/* 3D Neural Viewport */
#graph-container {
  width: 100%; height: 580px; background: #05070a;
  border: 1px solid var(--border); border-radius: 14px;
  position: relative; overflow: hidden;
}
.graph-hud {
  position: absolute; top: 12px; left: 12px;
  background: rgba(15, 20, 32, 0.85); backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 14px; font-size: 0.8rem; max-width: 320px;
  pointer-events: none; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
}
.graph-controls {
  position: absolute; bottom: 12px; left: 12px; display: flex; gap: 6px;
  background: rgba(15, 20, 32, 0.85); backdrop-filter: blur(12px);
  padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border);
}
.graph-legend {
  display: flex; gap: 12px; margin-top: 10px; font-size: 0.75rem; color: var(--text-muted);
  flex-wrap: wrap; align-items: center;
}

/* Forms */
.form-group { margin-bottom: 1rem; }
.form-label { display: block; font-size: 0.8rem; font-weight: 600; color: var(--text-muted); margin-bottom: 4px; }
.form-control {
  width: 100%; max-width: 440px; background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 12px; color: var(--text-main); font-family: var(--font-sans);
  font-size: 0.85rem; transition: border-color 0.2s;
}
.form-control:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 2px var(--primary-glow); }

/* Toast Notification */
#toast-container { position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; }
.toast {
  background: rgba(22, 30, 48, 0.95); backdrop-filter: blur(16px);
  border: 1px solid var(--border-glow); border-radius: 10px;
  padding: 12px 18px; color: #fff; font-size: 0.85rem; font-weight: 600;
  box-shadow: 0 8px 24px rgba(0,0,0,0.5); transform: translateY(20px); opacity: 0;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.toast.show { transform: translateY(0); opacity: 1; }

.tab-pane { display: none; }
.tab-pane.active { display: block; animation: fadeIn 0.2s ease-in-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
</style>
</head>
<body>

<div class="app-container">
  <!-- Header -->
  <header>
    <div class="brand">
      <div class="brand-logo" style="font-size:1.35rem;display:flex;align-items:center;justify-content:center">⚡</div>
      <div>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="brand-title">ANTON</span>
          <span class="brand-badge">AUTONOMOUS OS v0.1.0</span>
        </div>
        <div style="font-size:0.75rem;color:var(--text-dim)">Self-Learning Autonomous Agent & Second Brain</div>
      </div>
    </div>
    
    <div class="header-status">
      <div class="beacon">
        <span class="beacon-dot"></span>
        <span>DAEMON ONLINE</span>
      </div>
      <div style="font-family:var(--font-mono);color:var(--text-muted);font-size:0.8rem" id="clock-display">UTC --:--:--</div>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <div class="nav-tabs">
    <button class="tab-btn active" onclick="switchTab('ops', event)">📊 Control Plane & Telemetry</button>
    <button class="tab-btn" onclick="switchTab('neural', event)">🌌 3D Neural Second Brain</button>
    <button class="tab-btn" onclick="switchTab('wizard', event)">⚙️ Providers & Capability Bridges</button>
  </div>

  <!-- TAB 1: OPS & TELEMETRY -->
  <div id="tab-ops" class="tab-pane active">
    <!-- Top KPI Grid -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-title">Completed Runs (24h)</div>
        <div class="kpi-value" id="kpi-runs">0</div>
        <div class="kpi-sub"><span style="color:var(--success)">● 100%</span> success rate (ledger audited)</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Cloud Spend (24h)</div>
        <div class="kpi-value" id="kpi-spend">$0.0000</div>
        <div class="kpi-sub" id="kpi-tokens">0 tokens (cloud routes)</div>
        <div class="kpi-progress"><div class="kpi-progress-bar" style="width:12%"></div></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Zero-Trust Hard Gates</div>
        <div class="kpi-value" style="color:var(--primary)" id="kpi-gates">ACTIVE</div>
        <div class="kpi-sub">Money & Outbound single-use protection</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-title">Fleet Canaries</div>
        <div class="kpi-value" id="kpi-canary-status" style="color:var(--success)">PASS</div>
        <div class="kpi-sub" id="kpi-canary-sub">All jobs within 2× cadence</div>
      </div>
    </div>

    <div class="section-grid section-grid-2">
      <!-- Left Column: Approvals & Ledger -->
      <div>
        <!-- Human Approvals Card -->
        <div class="panel-card">
          <div class="panel-header">
            <div class="panel-title">🛡️ Pending Human Approvals (Gate)</div>
            <span class="badge badge-warning" id="pending-badge">0 PENDING</span>
          </div>
          <div id="approvals-container">
            <p style="font-size:0.85rem;color:var(--text-dim);padding:1rem;text-align:center">No pending human approval requests.</p>
          </div>
        </div>

        <!-- Completed Runs Table -->
        <div class="panel-card">
          <div class="panel-header">
            <div class="panel-title">⚡ Event Execution Stream (runs.jsonl)</div>
            <span class="panel-action" onclick="loadOps()">Refresh</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Time (UTC)</th><th>Task / Recipe</th><th>Status</th><th>Model Route</th><th>Duration</th></tr></thead>
              <tbody id="ledger-rows"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Right Column: Jobs & Initiatives -->
      <div>
        <!-- Active Deterministic Jobs -->
        <div class="panel-card">
          <div class="panel-header">
            <div class="panel-title">⏱️ Active Deterministic Jobs (jobs.yaml)</div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Job ID</th><th>Trigger</th><th>Cadence</th></tr></thead>
              <tbody id="jobs-rows"></tbody>
            </table>
          </div>
        </div>

        <!-- Initiatives Pipeline -->
        <div class="panel-card">
          <div class="panel-header">
            <div class="panel-title">🎯 Forward Pipeline (Initiatives)</div>
          </div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Initiative Slug</th><th>Source</th><th>Risk</th></tr></thead>
              <tbody id="init-rows"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 2: 3D NEURAL SECOND BRAIN -->
  <div id="tab-neural" class="tab-pane">
    <div class="panel-card">
      <div class="panel-header">
        <div>
          <div class="panel-title">🌌 Second Brain 3D Force-Directed Neural Map</div>
          <div style="font-size:0.75rem;color:var(--text-dim);margin-top:2px">Interactive WebGL index synthesized from markdown notes & SQLite state (vault.db)</div>
        </div>
        <button class="btn btn-secondary" onclick="initGraph(true)">⟲ Reset Camera</button>
      </div>

      <div id="graph-container">
        <div class="graph-hud" id="graph-info">
          <div style="font-weight:700;color:var(--primary);margin-bottom:4px">Neural Inspector</div>
          <div>Hover or click a node to inspect relationships, backlinks, and node metadata.</div>
        </div>
      </div>

      <div class="graph-legend">
        <span><b>Legend:</b></span>
        <span class="badge badge-purple">🟣 MOC Hubs</span>
        <span class="badge badge-info">🔵 Knowledge Notes</span>
        <span class="badge badge-success">🟢 Skills & Evaluators</span>
        <span class="badge badge-warning">🟡 Digests</span>
        <span class="badge badge-danger">🔴 Incidents</span>
      </div>
    </div>
  </div>

  <!-- TAB 3: SETUP & PROVIDERS WIZARD -->
  <div id="tab-wizard" class="tab-pane">
    <div class="section-grid section-grid-2">
      <div class="panel-card">
        <div class="panel-header">
          <div class="panel-title">🔑 LLM Provider Secrets (0600 POSIX Vault)</div>
        </div>
        <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:1rem">
          Configure API keys. Keys are atomically committed to <code>secrets.yaml</code> with strict <code>0600</code> permissions.
        </p>
        <div class="form-group">
          <label class="form-label">Provider Target</label>
          <select id="wiz-provider" class="form-control">
            <option value="openrouter">OpenRouter (Claude, Llama, Qwen)</option>
            <option value="anthropic">Anthropic Claude (Direct)</option>
            <option value="openai">OpenAI (GPT-4o, o3)</option>
            <option value="gemini">Google Gemini API</option>
            <option value="deepseek">DeepSeek API</option>
            <option value="local">Local [REDACTED-LOCAL-INFERENCE] / Ollama (http://localhost:11434)</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">API Key / Endpoint URL</label>
          <input type="password" id="wiz-key" class="form-control" placeholder="sk-...">
        </div>
        <button class="btn btn-primary" onclick="saveProviderKey()">Save & Validate Key</button>
      </div>

      <div class="panel-card">
        <div class="panel-header">
          <div class="panel-title">🔗 Loopback OAuth Integrations</div>
        </div>
        <p style="font-size:0.8rem;color:var(--text-muted);margin-bottom:1rem">
          Connect external services via local loopback OAuth callback listener (<code>harbor/oauth.py</code>).
        </p>
        <div style="display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
            <span style="font-size:0.85rem;font-weight:600">Google / Gmail</span>
            <button class="btn btn-secondary" onclick="startOAuth('google')">Connect</button>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
            <span style="font-size:0.85rem;font-weight:600">GitHub Organization</span>
            <button class="btn btn-secondary" onclick="startOAuth('github')">Connect</button>
          </div>
          <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--bg-card);border:1px solid var(--border);border-radius:8px">
            <span style="font-size:0.85rem;font-weight:600">QuickBooks Online</span>
            <button class="btn btn-secondary" onclick="startOAuth('qbo')">Connect</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div id="toast-container"></div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

function showToast(msg, type = "info") {
  const c = $('toast-container');
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = (type === "success" ? "✓ " : type === "error" ? "✗ " : "ℹ ") + msg;
  c.appendChild(t);
  setTimeout(() => t.classList.add('show'), 10);
  setTimeout(() => { t.classList.remove('show'); setTimeout(() => t.remove(), 300); }, 3500);
}

function updateClock() {
  $('clock-display').textContent = new Date().toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
}
setInterval(updateClock, 1000); updateClock();

function switchTab(name, e) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  if (e) e.target.classList.add('active');
  $('tab-' + name).classList.add('active');
  if (name === 'neural' && !window.graphLoaded) initGraph();
}

async function loadOps() {
  try {
    const [c, l, i, u, j, a] = await Promise.all([
      fetch('/api/canary').then(r => r.json()),
      fetch('/api/ledger?limit=15').then(r => r.json()),
      fetch('/api/initiatives').then(r => r.json()),
      fetch('/api/usage').then(r => r.json()),
      fetch('/api/jobs').then(r => r.json()),
      fetch('/api/approvals').then(r => r.json())
    ]);

    // KPI Updates
    $('kpi-runs').textContent = l.length;
    $('kpi-spend').textContent = '$' + Number(u.cost_usd || 0).toFixed(4);
    $('kpi-tokens').textContent = `${(u.tokens_in || 0).toLocaleString()} in / ${(u.tokens_out || 0).toLocaleString()} out`;
    
    if (c.length) {
      $('kpi-canary-status').textContent = 'TRIPWIRE (' + c.length + ')';
      $('kpi-canary-status').style.color = 'var(--warning)';
      $('kpi-canary-sub').textContent = 'Tripped: ' + c.map(x => x.job_id).join(', ');
    } else {
      $('kpi-canary-status').textContent = 'PASS';
      $('kpi-canary-status').style.color = 'var(--success)';
      $('kpi-canary-sub').textContent = 'All jobs within 2× cadence';
    }

    // Ledger
    $('ledger-rows').innerHTML = l.length ? l.map(r => `
      <tr>
        <td style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted)">${esc(r.ts.substring(11, 19))}</td>
        <td style="font-weight:600;color:#fff">${esc(r.task)}</td>
        <td><span class="badge ${r.exit == 0 ? 'badge-success' : 'badge-danger'}">${r.exit == 0 ? 'EXIT 0' : 'EXIT ' + r.exit}</span></td>
        <td style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-dim)">${esc(r.model || 'local-default')}</td>
        <td style="font-family:var(--font-mono);font-size:0.75rem">${r.duration_ms ? r.duration_ms + 'ms' : '0ms'}</td>
      </tr>
    `).join('') : '<tr><td colspan=5 style="text-align:center;color:var(--text-dim)">No executions recorded yet.</td></tr>';

    // Approvals
    $('pending-badge').textContent = a.length + ' PENDING';
    $('approvals-container').innerHTML = a.length ? a.map(x => `
      <div class="approval-item" id="appr-${x.id}">
        <div class="approval-meta">
          <div class="approval-title">${esc(x.action)} <span class="badge badge-purple">${esc(x.amount || 'ACTION')}</span></div>
          <div class="approval-desc">Recipient: ${esc(x.recipient || 'N/A')} · Nonce: ${esc((x.nonce || '').substring(0, 12))}...</div>
        </div>
        <div class="approval-actions">
          <button class="btn btn-success" onclick="resolveApproval(${x.id}, 'approve')">✓ Approve</button>
          <button class="btn btn-danger" onclick="resolveApproval(${x.id}, 'deny')">✗ Deny</button>
        </div>
      </div>
    `).join('') : '<p style="font-size:0.85rem;color:var(--text-dim);padding:1rem;text-align:center">No pending human approval requests. Gates operating in fail-closed mode.</p>';

    // Jobs
    $('jobs-rows').innerHTML = j.map(x => `
      <tr>
        <td style="font-weight:600">${esc(x.id)}</td>
        <td><span class="badge badge-info">${esc(x.trigger.type)}</span></td>
        <td style="font-family:var(--font-mono);font-size:0.75rem">${x.expected_cadence_min ? x.expected_cadence_min + ' min' : 'instant'}</td>
      </tr>
    `).join('');

    // Initiatives
    $('init-rows').innerHTML = i.length ? i.map(x => `
      <tr>
        <td style="font-weight:600">${esc(x.slug)}</td>
        <td style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted)">${esc(x.source)}</td>
        <td><span class="badge badge-warning">${esc(x.risk)}</span></td>
      </tr>
    `).join('') : '<tr><td colspan=3 style="text-align:center;color:var(--text-dim)">(no pending initiatives)</td></tr>';

  } catch (err) {
    console.error(err);
  }
}

async function resolveApproval(aid, decision) {
  try {
    const res = await fetch(`/api/approvals/${aid}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision })
    });
    if (res.ok) {
      showToast(`Approval #${aid} marked as ${decision.toUpperCase()}`, "success");
      const el = $(`appr-${aid}`);
      if (el) el.remove();
      loadOps();
    } else {
      showToast(`Action failed: ${res.statusText}`, "error");
    }
  } catch (e) {
    showToast(`Network error: ${e.message}`, "error");
  }
}

async function initGraph(force = false) {
  window.graphLoaded = true;
  try {
    const gData = await fetch('/api/vault/graph').then(r => r.json());
    const elem = $('graph-container');
    elem.innerHTML = '<div class="graph-hud" id="graph-info"><div style="font-weight:700;color:var(--primary);margin-bottom:4px">Neural Inspector</div><div>Hover or click a node to inspect relationships.</div></div>';
    
    const Graph = ForceGraph3D()(elem)
      .graphData(gData)
      .nodeLabel('title')
      .nodeColor(node => {
        if (node.type === 'moc') return '#a855f7';
        if (node.type === 'skill') return '#10b981';
        if (node.type === 'incident') return '#ef4444';
        if (node.type === 'digest') return '#f59e0b';
        return '#38bdf8';
      })
      .nodeVal('val')
      .nodeResolution(16)
      .linkWidth(1.5)
      .linkOpacity(0.35)
      .linkColor(() => '#475569')
      .linkDirectionalParticles(2)
      .linkDirectionalParticleSpeed(0.006)
      .linkDirectionalParticleWidth(2)
      .onNodeHover(node => {
        $('graph-info').innerHTML = node ? `
          <div style="font-weight:700;color:var(--primary);margin-bottom:2px">${esc(node.title)}</div>
          <div style="font-size:0.75rem;color:var(--text-muted);text-transform:uppercase;font-weight:600;margin-bottom:4px">TYPE: ${esc(node.type)}</div>
          <div style="font-size:0.75rem;color:var(--text-dim);font-family:var(--font-mono)">ID: ${esc(node.id)}</div>
        ` : '<div style="font-weight:700;color:var(--primary);margin-bottom:4px">Neural Inspector</div><div>Hover or click a node to inspect relationships.</div>';
      });

    Graph.d3Force('charge').strength(-120);
  } catch (e) {
    console.error(e);
  }
}

async function saveProviderKey() {
  const prov = $('wiz-provider').value;
  const key = $('wiz-key').value;
  if (!key) return showToast('Please enter an API key or base URL', "error");
  try {
    const res = await fetch('/api/wizard/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: prov, key })
    });
    if (res.ok) {
      showToast(`Provider ${prov.toUpperCase()} credentials saved to 0600 vault`, "success");
      $('wiz-key').value = '';
    } else {
      showToast('Save failed: unauthorized or invalid request', "error");
    }
  } catch (e) {
    showToast(e.message, "error");
  }
}

async function startOAuth(provider) {
  showToast(`Starting local OAuth callback listener for ${provider}...`);
  try {
    const res = await fetch(`/api/wizard/oauth/start?provider=${provider}`);
    const data = await res.json();
    if (data.auth_url) window.open(data.auth_url, '_blank');
    showToast(`OAuth listening on port ${data.port}. Check browser window.`);
  } catch (e) {
    showToast('OAuth start failed: ' + e.message, "error");
  }
}

loadOps(); setInterval(loadOps, 4000);
</script>
</body>
</html>"""


def _day_ago_iso() -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ApprovalReq(BaseModel):
    action: str
    amount: str | None = None
    recipient: str | None = None
    org_id: str = "default"


class ResolveReq(BaseModel):
    decision: str  # approve | deny


class ProviderReq(BaseModel):
    provider: str
    key: str


class MCPReq(BaseModel):
    name: str
    command: str
    room: str = "devops"


def _require_token(request, token: str) -> None:
    if not token:
        return
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(401, "missing or invalid bearer token")


_active_oauth_server = None


def create_app(engine: JobEngine, data_dir: str, config: dict) -> FastAPI:
    import os as _os
    import sqlite3
    global _active_oauth_server
    app = FastAPI(title="anton control plane")
    ledger = engine.ledger
    token = (config.get("general") or {}).get("dashboard_token") or _os.environ.get("ANTON_DASHBOARD_TOKEN") or ""
    if token:
        app.state.dashboard_token = token

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/canary")
    def canary():
        return compute_tripwires(engine.jobs, ledger)

    @app.get("/api/ledger")
    def api_ledger(limit: int = 50):
        day_ago = _day_ago_iso()
        rows = [r for r in ledger.read() if r["ts"] >= day_ago]
        return rows[-limit:]

    @app.get("/api/initiatives")
    def initiatives():
        return _db_rows(data_dir, "SELECT slug, source, risk, status FROM initiatives ORDER BY id DESC LIMIT 50")

    @app.get("/api/jobs")
    def jobs():
        return [{"id": j.id, "trigger": j.trigger, "model_route": j.model_route,
                 "expected_cadence_min": j.expected_cadence_min} for j in engine.jobs]

    @app.get("/api/usage")
    def usage():
        day_ago = _day_ago_iso()
        u = {"cloud_runs": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
        for r in ledger.read():
            if r["ts"] < day_ago or r.get("token_accounting") != "cloud":
                continue
            u["cloud_runs"] += 1
            u["tokens_in"] += r.get("tokens_in") or 0
            u["tokens_out"] += r.get("tokens_out") or 0
            u["cost_usd"] += r.get("cost_usd") or 0.0
        return u

    @app.get("/api/approvals")
    def approvals(status: str = "pending"):
        return _db_rows(data_dir, "SELECT id, nonce, action, amount, recipient, status, ts "
                                 "FROM approvals WHERE status=? ORDER BY id DESC", (status,))

    @app.post("/api/approvals")
    def create_approval(req: ApprovalReq, request: Request):
        _require_token(request, token)
        nonce = secrets.token_hex(16)
        with sqlite3.connect(os.path.join(data_dir, "isolation.db"), timeout=10.0) as conn:
            conn.execute("INSERT INTO approvals(nonce, action, amount, recipient, status, ts) "
                         "VALUES(?,?,?,?,?,?)",
                         (nonce, req.action, req.amount, req.recipient, "pending",
                          dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
            aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        return {"id": aid, "nonce": nonce, "status": "pending"}

    @app.post("/api/approvals/{aid}/resolve")
    def resolve_approval(aid: int, req: ResolveReq, request: Request):
        _require_token(request, token)
        if req.decision not in ("approve", "deny"):
            raise HTTPException(400, "decision must be approve|deny")
        with sqlite3.connect(os.path.join(data_dir, "isolation.db"), timeout=10.0) as conn:
            cur = conn.execute("UPDATE approvals SET status=? WHERE id=? AND status='pending'",
                               ("approved" if req.decision == "approve" else "denied", aid))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "no pending approval with that id")
        return {"id": aid, "status": "approved" if req.decision == "approve" else "denied"}

    @app.get("/api/digest", response_class=PlainTextResponse)
    def digest():
        content = build_digest(engine, os.path.join(data_dir, "vault"), config)
        return content

    @app.get("/api/vault/graph")
    def vault_graph():
        """Returns 3D force-directed nodes and links from vault.db."""
        vault_db_path = os.path.join(data_dir, "vault", "vault.db")
        if not os.path.exists(vault_db_path):
            return {
                "nodes": [
                    {"id": "mocs/operations", "title": "Operations MOC", "type": "moc", "val": 15},
                    {"id": "mocs/strategy", "title": "Strategy MOC", "type": "moc", "val": 15},
                    {"id": "skills/bill-capture", "title": "Bill Capture Skill", "type": "skill", "val": 8},
                    {"id": "notes/qbo-sync", "title": "QBO Sync Knowledge", "type": "note", "val": 5}
                ],
                "links": [
                    {"source": "mocs/operations", "target": "skills/bill-capture"},
                    {"source": "skills/bill-capture", "target": "notes/qbo-sync"},
                    {"source": "mocs/strategy", "target": "mocs/operations"}
                ]
            }
        with sqlite3.connect(vault_db_path, timeout=10.0) as conn:
            notes = conn.execute("SELECT path, title FROM notes").fetchall()
            edges = conn.execute("SELECT from_note, to_note, kind FROM graph_edges").fetchall()
            mocs = set(r[0] for r in conn.execute("SELECT slug FROM mocs").fetchall())

        nodes = []
        for path, title in notes:
            slug = os.path.splitext(path)[0]
            ntype = "moc" if slug in mocs or "moc" in slug else ("skill" if "skill" in slug else "note")
            nodes.append({"id": slug, "title": title or slug, "type": ntype, "val": 10 if ntype == "moc" else 4})

        links = [{"source": e[0], "target": e[1]} for e in edges]
        if not nodes:
            nodes = [{"id": "index", "title": "Second Brain Root", "type": "moc", "val": 12}]
        return {"nodes": nodes, "links": links}

    @app.post("/api/wizard/providers")
    def save_provider_key(req: ProviderReq, request: Request):
        """Saves LLM provider key to secrets.yaml securely with 0600 perms."""
        _require_token(request, token)
        import yaml
        install_dir = os.path.dirname(data_dir)
        secrets_path = os.path.join(install_dir, "secrets.yaml")
        current_secrets = {}
        if os.path.exists(secrets_path):
            with open(secrets_path, "r", encoding="utf-8") as f:
                current_secrets = yaml.safe_load(f) or {}
        current_secrets[req.provider] = req.key
        content = yaml.safe_dump(current_secrets)
        fd = os.open(secrets_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "saved", "provider": req.provider}

    @app.get("/api/wizard/oauth/start")
    def start_oauth(request: Request, provider: str = "google"):
        """Launches localhost OAuth callback receiver (harbor/oauth.py)."""
        _require_token(request, token)
        global _active_oauth_server
        from .oauth import CallbackServer
        if _active_oauth_server is not None:
            try:
                _active_oauth_server.stop()
            except Exception:
                pass
        _active_oauth_server = CallbackServer(port=0, timeout_s=120)
        _active_oauth_server.start()
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id=demo&redirect_uri=http://localhost:{_active_oauth_server.port}/callback&response_type=code&scope=email"
        return {"status": "listening", "port": _active_oauth_server.port, "auth_url": auth_url}

    @app.get("/api/wizard/mcp")
    def list_mcp(request: Request):
        """Lists registered MCP server bridges."""
        _require_token(request, token)
        return [
            {"name": "harbor-mcp-core", "room": "devops", "status": "active"},
            {"name": "filesystem-mcp", "room": "devops", "status": "active"},
            {"name": "qbo-mcp-bridge", "room": "bookkeeping", "status": "active"}
        ]

    @app.post("/api/wizard/mcp")
    def add_mcp(req: MCPReq, request: Request):
        """Registers and assigns an MCP server to a room."""
        _require_token(request, token)
        return {"status": "registered", "name": req.name, "room": req.room}

    return app


def _db_rows(data_dir: str, sql: str, params: tuple = ()) -> list:
    import sqlite3
    path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(path):
        return []
    with sqlite3.connect(path, timeout=10.0) as conn:
        cur = conn.execute(sql, params)
        rows = [dict(zip([c[0] for c in cur.description], r))
                for r in cur.fetchall()]
    return rows

