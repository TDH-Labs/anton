"""FastAPI control plane dashboard + approvals API for Anton (M4)."""
from __future__ import annotations

import datetime as dt
import os
import secrets
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from .canary import compute_tripwires
from .digest import build_digest
from .scheduler import JobEngine

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANTON — Autonomous Studio & Control Plane</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/3d-force-graph"></script>
<style>
:root {
  --bg-main: #0c0e12;
  --bg-canvas: #101218;
  --bg-surface: #141720;
  --bg-card: #181b26;
  --bg-card-hover: #1f2330;
  --border: rgba(255, 255, 255, 0.08);
  --border-rim: inset 0 1px 0 rgba(255, 255, 255, 0.14);
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --text-dim: #64748b;
  --primary: #38bdf8;
  --accent: #6366f1;
  --success: #10b981;
  --success-bg: rgba(16, 185, 129, 0.12);
  --warning: #f59e0b;
  --warning-bg: rgba(245, 158, 11, 0.12);
  --danger: #ef4444;
  --danger-bg: rgba(239, 68, 68, 0.12);
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, Menlo, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-main);
  color: var(--text-main);
  min-height: 100vh;
  padding: 1.25rem 1.75rem 5rem 1.75rem;
  line-height: 1.5;
  overflow-x: hidden;
}

.app-container { max-width: 1560px; margin: 0 auto; }

/* Top Navbar */
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.9rem 1.5rem;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  box-shadow: var(--border-rim), 0 8px 32px rgba(0, 0, 0, 0.5);
  border-radius: 14px;
  margin-bottom: 1.25rem;
}
.brand { display: flex; align-items: center; gap: 12px; }
.brand-logo {
  width: 36px; height: 36px;
  background: #1e2230;
  border: 1px solid rgba(255,255,255,0.15);
  box-shadow: var(--border-rim);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem;
}
.brand-title { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.02em; }
.brand-badge {
  font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
  padding: 2px 8px; border-radius: 20px;
  background: rgba(56, 189, 248, 0.12); color: var(--primary);
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.header-actions { display: flex; align-items: center; gap: 16px; }

/* Son of Anton Mode Switch */
.son-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: #181b24;
  border: 1px solid var(--border);
  box-shadow: var(--border-rim);
  border-radius: 30px;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.son-toggle:hover { border-color: rgba(255,255,255,0.2); background: #202432; }
.son-toggle.active {
  background: rgba(245, 158, 11, 0.15);
  border-color: rgba(245, 158, 11, 0.5);
  color: #fbbf24;
  box-shadow: 0 0 16px rgba(245, 158, 11, 0.25);
}
.son-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #64748b; transition: all 0.2s ease;
}
.son-toggle.active .son-dot {
  background: #fbbf24;
  box-shadow: 0 0 8px #fbbf24;
  animation: pulse 1.5s infinite;
}

@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }

.beacon {
  display: flex; align-items: center; gap: 8px;
  font-size: 0.75rem; font-weight: 600; color: var(--success);
  padding: 5px 12px; background: var(--success-bg);
  border-radius: 20px; border: 1px solid rgba(16, 185, 129, 0.2);
}
.beacon-dot {
  width: 7px; height: 7px; background: var(--success);
  border-radius: 50%; box-shadow: 0 0 8px var(--success);
}

/* Nav Tabs */
.nav-tabs {
  display: flex; gap: 8px; margin-bottom: 1.25rem;
}
.tab-btn {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  box-shadow: var(--border-rim);
  color: var(--text-muted);
  padding: 8px 18px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  transition: all 0.15s ease;
}
.tab-btn:hover { background: var(--bg-card-hover); color: var(--text-main); }
.tab-btn.active {
  background: #222736;
  border-color: rgba(255, 255, 255, 0.2);
  color: var(--text-main);
  box-shadow: var(--border-rim), 0 4px 16px rgba(0,0,0,0.3);
}

/* Dot Grid Studio Canvas */
.studio-layout {
  display: grid;
  grid-template-columns: 260px 1fr 340px;
  gap: 16px;
  min-height: 700px;
}
.studio-pane {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  box-shadow: var(--border-rim);
  border-radius: 14px;
  padding: 1.25rem;
  overflow: hidden;
}

/* Canvas Area */
.canvas-container {
  background-color: var(--bg-canvas);
  background-image: radial-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 1px);
  background-size: 24px 24px;
  border-radius: 14px;
  border: 1px solid var(--border);
  box-shadow: var(--border-rim);
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.canvas-header {
  padding: 12px 18px;
  background: rgba(20, 23, 32, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
}
.canvas-title { font-size: 0.85rem; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; }

/* Visual Node Graph */
.nodes-area {
  flex: 1;
  position: relative;
  padding: 40px;
  display: flex;
  align-items: center;
  justify-content: space-around;
  gap: 24px;
  flex-wrap: wrap;
}
.node-card {
  background: #161922;
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: var(--border-rim), 0 8px 24px rgba(0, 0, 0, 0.4);
  border-radius: 12px;
  padding: 14px 18px;
  width: 185px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.node-card:hover { transform: translateY(-2px); border-color: rgba(255, 255, 255, 0.25); background: #1b1f2b; }
.node-tag {
  font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
  padding: 2px 6px; border-radius: 6px; display: inline-block; margin-bottom: 6px;
}
.tag-trigger { background: rgba(56, 189, 248, 0.15); color: #38bdf8; }
.tag-brain { background: rgba(168, 85, 247, 0.15); color: #c084fc; }
.tag-gate { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }
.tag-action { background: rgba(16, 185, 129, 0.15); color: #34d399; }
.node-title { font-size: 0.88rem; font-weight: 700; margin-bottom: 4px; }
.node-desc { font-size: 0.72rem; color: var(--text-dim); }

/* Executive Decision HUD (Right Column) */
.decision-card {
  background: #1a1e2a;
  border: 1px solid rgba(245, 158, 11, 0.3);
  box-shadow: var(--border-rim), 0 10px 30px rgba(0,0,0,0.5);
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
}
.decision-header {
  display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;
}
.decision-badge {
  font-size: 0.68rem; font-weight: 800; text-transform: uppercase;
  padding: 2px 8px; border-radius: 12px;
  background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);
}
.decision-title { font-size: 0.95rem; font-weight: 700; margin-bottom: 6px; }
.decision-desc { font-size: 0.78rem; color: var(--text-muted); margin-bottom: 14px; }
.decision-actions { display: flex; gap: 8px; }
.btn-approve {
  flex: 1; background: #10b981; color: #022c22; font-weight: 700; font-size: 0.8rem;
  padding: 8px 12px; border-radius: 8px; border: none; cursor: pointer;
  display: flex; align-items: center; justify-content: center; gap: 6px;
  transition: all 0.15s ease;
}
.btn-approve:hover { background: #34d399; }
.btn-deny {
  flex: 1; background: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 700; font-size: 0.8rem;
  padding: 8px 12px; border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.3); cursor: pointer;
  transition: all 0.15s ease;
}
.btn-deny:hover { background: rgba(239, 68, 68, 0.25); }
.key-badge {
  background: rgba(0,0,0,0.25); border-radius: 4px; padding: 1px 5px; font-size: 0.65rem; font-family: var(--font-mono);
}

/* Activity Feed */
.activity-list { display: flex; flex-direction: column; gap: 10px; }
.activity-item {
  display: flex; gap: 10px; font-size: 0.78rem; padding: 8px 10px;
  background: #141722; border: 1px solid var(--border); border-radius: 8px;
}
.activity-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--primary); margin-top: 6px; flex-shrink: 0; }
.activity-meta { font-size: 0.7rem; color: var(--text-dim); font-family: var(--font-mono); }

/* Floating Command Capsule (⌘K) */
.command-capsule {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(20, 24, 34, 0.88);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  box-shadow: var(--border-rim), 0 12px 40px rgba(0, 0, 0, 0.6);
  border-radius: 30px;
  padding: 8px 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  width: 520px;
  max-width: 90vw;
  z-index: 100;
  cursor: text;
}
.command-input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-main);
  font-family: var(--font-sans);
  font-size: 0.85rem;
  flex: 1;
}
.command-input::placeholder { color: var(--text-dim); }
.command-kbd {
  background: #222634;
  border: 1px solid rgba(255, 255, 255, 0.1);
  padding: 2px 6px;
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.7rem;
  color: var(--text-muted);
}

/* Modal Confirmation */
.modal-backdrop {
  position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
  background: rgba(0,0,0,0.7); backdrop-filter: blur(6px);
  display: none; align-items: center; justify-content: center; z-index: 200;
}
.modal-box {
  background: #161922; border: 1px solid rgba(245, 158, 11, 0.4);
  box-shadow: 0 16px 48px rgba(0,0,0,0.8);
  border-radius: 16px; padding: 24px; max-width: 460px; width: 90%;
}
.modal-title { font-size: 1.1rem; font-weight: 800; margin-bottom: 8px; color: #fbbf24; display: flex; align-items: center; gap: 8px; }
.modal-desc { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 20px; line-height: 1.6; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
th { text-align: left; padding: 8px 12px; color: var(--text-dim); font-size: 0.7rem; text-transform: uppercase; border-bottom: 1px solid var(--border); }
td { padding: 10px 12px; border-bottom: 1px solid var(--border); }
tr:hover td { background: var(--bg-card-hover); }

/* Graph Area */
#graph-container { width: 100%; height: 600px; background: var(--bg-canvas); border-radius: 12px; position: relative; }

.toast {
  position: fixed; bottom: 80px; right: 24px;
  background: #1c2130; border: 1px solid var(--border);
  box-shadow: 0 8px 24px rgba(0,0,0,0.5); padding: 10px 16px;
  border-radius: 10px; font-size: 0.8rem; font-weight: 600;
  display: none; z-index: 300;
}
</style>
</head>
<body>

<div class="app-container">
  <!-- Header -->
  <header>
    <div class="brand">
      <div class="brand-logo">⚡</div>
      <div>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="brand-title">ANTON</span>
          <span class="brand-badge">AUTONOMOUS OS v0.1.0</span>
        </div>
        <div style="font-size:0.72rem;color:var(--text-dim)">Cognitive Control Plane & Second Brain</div>
      </div>
    </div>
    
    <div class="header-actions">
      <!-- Son of Anton Mode Switch -->
      <button class="son-toggle" id="son-toggle-btn" onclick="toggleSonOfAnton()">
        <span class="son-dot"></span>
        <span id="son-label">⚡ SON OF ANTON [OFF]</span>
      </button>

      <div class="beacon">
        <span class="beacon-dot"></span>
        <span>DAEMON ONLINE</span>
      </div>
      <div style="font-family:var(--font-mono);color:var(--text-muted);font-size:0.8rem" id="clock-display">UTC --:--:--</div>
    </div>
  </header>

  <!-- Navigation Tabs -->
  <div class="nav-tabs">
    <button class="tab-btn active" onclick="switchTab('studio', event)">📐 Autonomous Studio Canvas</button>
    <button class="tab-btn" onclick="switchTab('neural', event)">🌌 3D Neural Second Brain</button>
    <button class="tab-btn" onclick="switchTab('telemetry', event)">📊 Telemetry & Audit Ledger</button>
    <button class="tab-btn" onclick="switchTab('wizard', event)">⚙️ Provider Bridges & Key Vault</button>
  </div>

  <!-- TAB 1: AUTONOMOUS STUDIO CANVAS -->
  <div id="tab-studio" class="tab-pane active">
    <div class="studio-layout">
      <!-- Left: Navigator Tree -->
      <div class="studio-pane">
        <div style="font-size:0.75rem;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:12px">Knowledge & Playbooks</div>
        <div style="display:flex;flex-direction:column;gap:6px;font-size:0.8rem">
          <div style="padding:6px 8px;border-radius:6px;background:#181c28;color:var(--primary);font-weight:600">📁 Active Workflows</div>
          <div style="padding:4px 8px;color:var(--text-muted);cursor:pointer">├ ⚡ bill-capture.yaml</div>
          <div style="padding:4px 8px;color:var(--text-muted);cursor:pointer">├ ⚡ notify-client.yaml</div>
          <div style="padding:4px 8px;color:var(--text-muted);cursor:pointer">└ ⚡ e2e-canary.yaml</div>
          <div style="padding:6px 8px;border-radius:6px;background:#181c28;color:#a855f7;font-weight:600;margin-top:8px">🧠 Learned Skills</div>
          <div style="padding:4px 8px;color:var(--text-muted);cursor:pointer">├ ✦ 100x-desktop-ide</div>
          <div style="padding:4px 8px;color:var(--text-muted);cursor:pointer">├ ✦ 100x-mobile-app</div>
          <div style="padding:4px 8px;color:var(--text-muted);cursor:pointer">└ ✦ elite-software-product</div>
        </div>
      </div>

      <!-- Center: Dot Grid Workflow Canvas -->
      <div class="canvas-container">
        <div class="canvas-header">
          <span class="canvas-title">Live Execution Pipeline</span>
          <span style="font-size:0.75rem;color:var(--text-dim);font-family:var(--font-mono)">60 FPS · Deterministic Gate Graph</span>
        </div>
        <div class="nodes-area">
          <div class="node-card">
            <span class="node-tag tag-trigger">Trigger</span>
            <div class="node-title">Incoming Webhook</div>
            <div class="node-desc">/hooks/bill-email (POST)</div>
          </div>

          <div class="node-card">
            <span class="node-tag tag-brain">AI Brain</span>
            <div class="node-title">Extract & Verify</div>
            <div class="node-desc">Local [REDACTED-LOCAL-INFERENCE] ➜ 98% Feasibility</div>
          </div>

          <div class="node-card" id="canvas-gate-node">
            <span class="node-tag tag-gate">Human Gate</span>
            <div class="node-title">Approval Lock</div>
            <div class="node-desc" id="canvas-gate-status">Fail-Closed Nonce (R1)</div>
          </div>

          <div class="node-card">
            <span class="node-tag tag-action">Outcome</span>
            <div class="node-title">Post to Ledger</div>
            <div class="node-desc">Atomically Commit Changes</div>
          </div>
        </div>
      </div>

      <!-- Right: Decision HUD & Activity -->
      <div class="studio-pane">
        <div style="font-size:0.75rem;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin-bottom:12px">Executive Decision HUD</div>
        
        <div id="decision-hud-container">
          <p style="font-size:0.8rem;color:var(--text-dim);text-align:center;padding:20px 0">No pending approval requests.<br>All gates secure.</p>
        </div>

        <div style="font-size:0.75rem;font-weight:700;color:var(--text-dim);text-transform:uppercase;margin:16px 0 10px 0">Live Activity Feed</div>
        <div class="activity-list" id="live-activity-feed">
          <!-- Activity entries populated via JS -->
        </div>
      </div>
    </div>
  </div>

  <!-- TAB 2: 3D NEURAL SECOND BRAIN -->
  <div id="tab-neural" class="tab-pane" style="display:none">
    <div class="studio-pane" style="padding:0">
      <div id="graph-container"></div>
    </div>
  </div>

  <!-- TAB 3: TELEMETRY & LEDGER -->
  <div id="tab-telemetry" class="tab-pane" style="display:none">
    <div class="studio-pane">
      <div style="font-size:0.85rem;font-weight:700;margin-bottom:12px">Execution & Audit Ledger (runs.jsonl)</div>
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Task</th>
            <th>Exit Code</th>
            <th>Flags & Route</th>
            <th>Model / Provider</th>
            <th>Duration / Cost</th>
          </tr>
        </thead>
        <tbody id="ledger-rows"></tbody>
      </table>
    </div>
  </div>

  <!-- TAB 4: PROVIDERS & WIZARD -->
  <div id="tab-wizard" class="tab-pane" style="display:none">
    <div class="studio-pane" style="max-width:800px;margin:0 auto">
      <h3 style="margin-bottom:16px;font-size:1.1rem">Capability Bridges & Key Vault</h3>
      <div style="display:flex;flex-direction:column;gap:16px">
        <div>
          <label style="font-size:0.75rem;color:var(--text-muted);display:block;margin-bottom:6px">Provider Selection</label>
          <select id="wiz-provider" style="width:100%;padding:10px;background:#181b24;border:1px solid var(--border);color:#fff;border-radius:8px">
            <option value="openrouter">OpenRouter (Claude 3.5 Sonnet / Llama 3)</option>
            <option value="anthropic">Anthropic Direct</option>
            <option value="openai">OpenAI Direct</option>
            <option value="ollama">Local Ollama Host</option>
          </select>
        </div>
        <div>
          <label style="font-size:0.75rem;color:var(--text-muted);display:block;margin-bottom:6px">API Key / Base URL</label>
          <input type="password" id="wiz-key" placeholder="sk-or-... or http://localhost:11434" style="width:100%;padding:10px;background:#181b24;border:1px solid var(--border);color:#fff;border-radius:8px">
        </div>
        <button onclick="saveProviderKey()" class="btn-approve" style="padding:10px">Save to 0600 Secure Vault</button>
      </div>
    </div>
  </div>
</div>

<!-- Floating Command Capsule (⌘K) -->
<div class="command-capsule" onclick="document.getElementById('cmd-input').focus()">
  <span style="color:var(--primary)">⚡</span>
  <input type="text" id="cmd-input" class="command-input" placeholder="Ask Anton, search notes, or run a recipe (e.g. 'reconcile July invoices')...">
  <span class="command-kbd">⌘K</span>
</div>

<!-- Son of Anton Confirmation Modal -->
<div class="modal-backdrop" id="son-modal">
  <div class="modal-box">
    <div class="modal-title">⚡ Activate Son of Anton Mode?</div>
    <div class="modal-desc">
      You are about to engage <strong>Permissionless Execution</strong>.<br><br>
      Anton will autonomously execute all workflows with human approval gates without halting for manual confirmation.
      All verify gates and budget caps remain enforced.
    </div>
    <div class="modal-actions">
      <button class="btn-deny" onclick="closeSonModal()">Cancel</button>
      <button class="btn-approve" style="background:#f59e0b;color:#000" onclick="confirmSonOfAnton()">⚡ Engage Son of Anton</button>
    </div>
  </div>
</div>

<div class="toast" id="toast-msg"></div>

<script>
const $ = id => document.getElementById(id);
let sonOfAntonActive = false;
let activeApprovalId = null;

function showToast(msg, type='info') {
  const t = $('toast-msg');
  t.textContent = msg;
  t.style.display = 'block';
  t.style.borderColor = type === 'success' ? '#10b981' : (type === 'error' ? '#ef4444' : '#f59e0b');
  setTimeout(() => t.style.display = 'none', 3500);
}

function updateClock() {
  const d = new Date();
  $('clock-display').textContent = 'UTC ' + d.toISOString().substring(11, 19);
}
setInterval(updateClock, 1000); updateClock();

function switchTab(tab, e) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
  e.target.classList.add('active');
  $('tab-' + tab).style.display = 'block';
  if (tab === 'neural' && !window.graphLoaded) initGraph();
}

async function checkMode() {
  try {
    const res = await fetch('/api/mode');
    const data = await res.json();
    sonOfAntonActive = !!data.son_of_anton_mode;
    updateSonUI();
  } catch (e) {}
}

function updateSonUI() {
  const btn = $('son-toggle-btn');
  const lbl = $('son-label');
  const gateStatus = $('canvas-gate-status');
  if (sonOfAntonActive) {
    btn.classList.add('active');
    lbl.textContent = '⚡ SON OF ANTON [ACTIVE]';
    if (gateStatus) gateStatus.textContent = 'Auto-Bypass Active ⚡';
  } else {
    btn.classList.remove('active');
    lbl.textContent = '⚡ SON OF ANTON [OFF]';
    if (gateStatus) gateStatus.textContent = 'Fail-Closed Nonce (R1)';
  }
}

function toggleSonOfAnton() {
  if (!sonOfAntonActive) {
    $('son-modal').style.display = 'flex';
  } else {
    setSonMode(false);
  }
}

function closeSonModal() {
  $('son-modal').style.display = 'none';
}

async function confirmSonOfAnton() {
  closeSonModal();
  await setSonMode(true);
}

async function setSonMode(active) {
  try {
    const res = await fetch('/api/mode/son-of-anton', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ son_of_anton_mode: active })
    });
    if (res.ok) {
      sonOfAntonActive = active;
      updateSonUI();
      showToast(active ? '⚡ Son of Anton Mode ENGAGED' : '🛡️ Standard Safe Mode Restored', active ? 'warning' : 'success');
    }
  } catch (e) {
    showToast('Mode change failed', 'error');
  }
}

async function loadOps() {
  try {
    const [l, a] = await Promise.all([
      fetch('/api/ledger').then(r => r.json()),
      fetch('/api/approvals').then(r => r.json())
    ]);

    // Render Approvals HUD
    if (a.length > 0) {
      const top = a[0];
      activeApprovalId = top.id;
      $('decision-hud-container').innerHTML = `
        <div class="decision-card">
          <div class="decision-header">
            <span class="decision-badge">Approval #${top.id}</span>
            <span style="font-size:0.7rem;font-family:var(--font-mono);color:var(--text-dim)">${top.nonce.substring(0,8)}...</span>
          </div>
          <div class="decision-title">Action: ${top.action}</div>
          <div class="decision-desc">Recipient: ${top.recipient || 'N/A'} · Amount: ${top.amount || '0.00'}</div>
          <div class="decision-actions">
            <button class="btn-approve" onclick="resolveApproval(${top.id}, 'approve')">
              ✓ Approve <span class="key-badge">↵</span>
            </button>
            <button class="btn-deny" onclick="resolveApproval(${top.id}, 'deny')">
              ✗ Deny <span class="key-badge">⎋</span>
            </button>
          </div>
        </div>
      `;
    } else {
      activeApprovalId = null;
      $('decision-hud-container').innerHTML = sonOfAntonActive 
        ? '<div style="padding:16px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:10px;text-align:center;font-size:0.8rem;color:#fbbf24">⚡ Son of Anton Mode is ACTIVE.<br>Human gates are auto-approved.</div>'
        : '<p style="font-size:0.8rem;color:var(--text-dim);text-align:center;padding:20px 0">No pending approval requests.<br>All gates secure.</p>';
    }

    // Render Live Activity Feed
    $('live-activity-feed').innerHTML = l.slice(-6).reverse().map(r => `
      <div class="activity-item">
        <span class="activity-dot" style="background:${r.exit === 0 ? '#10b981' : (r.exit === 5 ? '#f59e0b' : '#ef4444')}"></span>
        <div style="flex:1">
          <div style="font-weight:600">${r.task} (exit ${r.exit})</div>
          <div class="activity-meta">${r.flags || 'none'} · ${r.ts.substring(11,19)}</div>
        </div>
      </div>
    `).join('');

    // Render Ledger Table
    $('ledger-rows').innerHTML = l.slice(-50).reverse().map(r => `
      <tr>
        <td style="font-family:var(--font-mono);font-size:0.75rem">${r.ts}</td>
        <td style="font-weight:600">${r.task}</td>
        <td><span style="color:${r.exit === 0 ? '#10b981' : '#ef4444'};font-weight:700">${r.exit}</span></td>
        <td style="font-family:var(--font-mono);font-size:0.75rem">${r.flags || ''}</td>
        <td style="font-size:0.75rem">${r.model || 'local'} (${r.provider || 'local'})</td>
        <td style="font-family:var(--font-mono);font-size:0.75rem">${r.duration_ms || 0}ms / $${(r.cost_usd || 0).toFixed(4)}</td>
      </tr>
    `).join('');

  } catch (e) {}
}

async function resolveApproval(aid, decision) {
  try {
    const res = await fetch(`/api/approvals/${aid}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision })
    });
    if (res.ok) {
      showToast(`Approval #${aid} marked as ${decision.toUpperCase()}`, 'success');
      loadOps();
    }
  } catch (e) {
    showToast(e.message, 'error');
  }
}

// Global Keyboard Shortcuts
window.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    $('cmd-input').focus();
  } else if (e.key === 'Enter' && activeApprovalId && document.activeElement !== $('cmd-input')) {
    resolveApproval(activeApprovalId, 'approve');
  } else if (e.key === 'Escape' && activeApprovalId) {
    resolveApproval(activeApprovalId, 'deny');
  }
});

async function initGraph() {
  window.graphLoaded = true;
  try {
    const gData = await fetch('/api/vault/graph').then(r => r.json());
    const elem = $('graph-container');
    ForceGraph3D()(elem)
      .graphData(gData)
      .nodeLabel('title')
      .nodeColor(n => n.type === 'moc' ? '#a855f7' : (n.type === 'skill' ? '#10b981' : '#38bdf8'))
      .nodeVal('val')
      .linkWidth(1.2)
      .linkOpacity(0.4);
  } catch (e) {}
}

async function saveProviderKey() {
  const prov = $('wiz-provider').value;
  const key = $('wiz-key').value;
  if (!key) return showToast('Please enter an API key', 'error');
  const res = await fetch('/api/wizard/providers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: prov, key })
  });
  if (res.ok) {
    showToast(`Saved ${prov} key to 0600 vault`, 'success');
    $('wiz-key').value = '';
  }
}

checkMode();
loadOps();
setInterval(loadOps, 3500);
</script>
</body>
</html>"""

class ApprovalReq(BaseModel):
    action: str
    amount: str = "0.00"
    recipient: str = ""

class ResolveReq(BaseModel):
    decision: str

class ProviderReq(BaseModel):
    provider: str
    key: str

class MCPReq(BaseModel):
    name: str
    command: str
    room: str = "devops"

class ModeReq(BaseModel):
    son_of_anton_mode: bool

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
    token = (config.get("general") or {}).get("dashboard_token") or _os.environ.get("ANTON_DASHBOARD_TOKEN") or _os.environ.get("HARBOR_DASHBOARD_TOKEN") or ""
    if token:
        app.state.dashboard_token = token

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/mode")
    def get_mode():
        return {"son_of_anton_mode": engine.son_of_anton_mode}

    @app.post("/api/mode/son-of-anton")
    def set_mode(req: ModeReq, request: Request):
        _require_token(request, token)
        engine.son_of_anton_mode = req.son_of_anton_mode
        return {"status": "updated", "son_of_anton_mode": engine.son_of_anton_mode}

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
        vault_db_path = os.path.join(data_dir, "vault", "vault.db")
        if not os.path.exists(vault_db_path):
            return {
                "nodes": [
                    {"id": "mocs/operations", "title": "Operations MOC", "type": "moc", "val": 15},
                    {"id": "skills/100x-desktop-ide", "title": "100x Desktop IDE", "type": "skill", "val": 8}
                ],
                "links": []
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
        _require_token(request, token)
        return [
            {"name": "anton-mcp-core", "room": "devops", "status": "active"},
            {"name": "filesystem-mcp", "room": "devops", "status": "active"}
        ]

    @app.post("/api/wizard/mcp")
    def add_mcp(req: MCPReq, request: Request):
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

def _day_ago_iso() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
