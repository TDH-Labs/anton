"""FastAPI control plane dashboard + approvals API for Anton (M4)."""
from __future__ import annotations

import datetime as dt
import os
import secrets
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, FileResponse

from .canary import compute_tripwires
from .digest import build_digest
from .scheduler import JobEngine

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANTON — Autonomous Pro Studio & IDE</title>
<link rel="icon" type="image/jpeg" href="/api/logo">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<!-- Monaco Editor CDN -->
<link rel="stylesheet" data-name="vs/editor/editor.main" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/editor/editor.main.min.css">
<!-- Markdown Parser -->
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<!-- 3D Force Graph -->
<script src="https://unpkg.com/3d-force-graph"></script>

<style>
:root {
  --bg-app: #090b10;
  --bg-sidebar: #0e1117;
  --bg-editor: #131620;
  --bg-card: #181c28;
  --bg-card-hover: #202636;
  --border: rgba(255, 255, 255, 0.08);
  --border-active: rgba(56, 189, 248, 0.4);
  --border-rim: inset 0 1px 0 rgba(255, 255, 255, 0.12);
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --text-dim: #64748b;
  --primary: #38bdf8;
  --accent: #818cf8;
  --success: #10b981;
  --warning: #f59e0b;
  --danger: #ef4444;
  --purple: #c084fc;
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, Menlo, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-app);
  color: var(--text-main);
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* 1. TOP UTILITY BAR (48px) */
.top-bar {
  height: 48px;
  background: var(--bg-sidebar);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  z-index: 100;
  box-shadow: var(--border-rim);
}
.brand-group { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.brand-logo-img {
  width: 28px; height: 28px;
  border-radius: 6px; object-fit: cover;
  border: 1px solid rgba(255,255,255,0.18);
  box-shadow: 0 2px 8px rgba(0,0,0,0.5);
  transition: all 0.25s ease;
}
.brand-name { font-size: 0.95rem; font-weight: 800; letter-spacing: -0.02em; }
.breadcrumb { font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono); }

/* Header Actions */
.top-actions { display: flex; align-items: center; gap: 12px; }
.son-toggle {
  display: flex; align-items: center; gap: 6px; padding: 4px 12px;
  background: #161a24; border: 1px solid var(--border);
  border-radius: 20px; cursor: pointer; font-size: 0.68rem; font-weight: 800;
  text-transform: uppercase; color: var(--text-muted); transition: all 0.2s ease;
}
.son-toggle:hover { border-color: rgba(255,255,255,0.2); }
.son-toggle.active {
  background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.6);
  color: #fbbf24; box-shadow: 0 0 14px rgba(245, 158, 11, 0.25);
}
.son-dot { width: 7px; height: 7px; border-radius: 50%; background: #64748b; }
.son-toggle.active .son-dot { background: #fbbf24; box-shadow: 0 0 8px #fbbf24; }

/* 2. MAIN 3-PANE WORKBENCH */
.workbench {
  flex: 1;
  display: grid;
  grid-template-columns: 260px 1fr 380px;
  overflow: hidden;
  position: relative;
}

/* LEFT PANE: NAVIGATOR */
.nav-pane {
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.nav-header {
  padding: 10px 14px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase;
  color: var(--text-dim); letter-spacing: 0.04em; border-bottom: 1px solid var(--border);
}
.tree-container { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
.tree-section { font-size: 0.68rem; font-weight: 700; color: var(--text-dim); text-transform: uppercase; padding: 8px 6px 4px 6px; }
.tree-node {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px; border-radius: 6px; font-size: 0.78rem; cursor: pointer;
  color: var(--text-muted); transition: all 0.15s ease; user-select: none;
}
.tree-node:hover { background: #161a26; color: var(--text-main); }
.tree-node.active { background: #1e2436; color: var(--primary); font-weight: 600; }
.tree-pill { font-size: 0.62rem; font-family: var(--font-mono); padding: 1px 5px; border-radius: 4px; background: rgba(255,255,255,0.06); }

/* CENTER PANE: WORKSPACE & MONACO */
.editor-pane {
  background: var(--bg-editor);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}
/* Tab Bar */
.editor-tabs {
  height: 38px;
  background: var(--bg-sidebar);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  overflow-x: auto;
  z-index: 10;
}
.tab {
  display: flex; align-items: center; gap: 8px; padding: 0 12px; height: 100%;
  font-size: 0.78rem; color: var(--text-muted); border-right: 1px solid var(--border);
  cursor: pointer; background: #0e1117; user-select: none; transition: background 0.15s ease;
  white-space: nowrap;
}
.tab:hover { background: #141722; color: var(--text-main); }
.tab.active { background: var(--bg-editor); color: var(--text-main); font-weight: 600; border-bottom: 2px solid var(--primary); }
.tab-close-btn {
  font-size: 0.75rem; color: var(--text-dim); border-radius: 4px; padding: 2px 4px;
  line-height: 1; transition: all 0.15s ease;
}
.tab-close-btn:hover { background: rgba(239, 68, 68, 0.25); color: #f87171; }

/* Editor / Preview Content */
.editor-body { flex: 1; position: relative; overflow: hidden; }
#monaco-container { width: 100%; height: 100%; display: none; }
#markdown-container { width: 100%; height: 100%; overflow-y: auto; padding: 32px 48px 100px 48px; display: none; }
#graph-tab-container { width: 100%; height: 100%; display: none; background: #0c0e14; }

/* Markdown Styling */
.md-view h1, .md-view h2, .md-view h3 { color: #f8fafc; margin: 20px 0 12px 0; }
.md-view p { color: #cbd5e1; line-height: 1.7; margin-bottom: 14px; font-size: 0.9rem; }
.md-view table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.82rem; }
.md-view th, .md-view td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
.md-view pre { background: #090b10; border: 1px solid var(--border); border-radius: 8px; padding: 14px; overflow-x: auto; margin: 14px 0; }
.md-view code { font-family: var(--font-mono); color: var(--primary); font-size: 0.82rem; }

/* =========================================================================
   DEAD-CENTER TO BOTTOM-CENTER PROMPT TRANSITION STYLES
   ========================================================================= */
.prompt-stage-wrapper {
  position: absolute;
  z-index: 50;
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* STATE 1: DEAD CENTER (Initial Zero State) */
.prompt-stage-wrapper.stage-center {
  top: 45%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 680px;
  max-width: 90%;
}

/* STATE 2: DOCKED LOWER CENTER (After 1st prompt) */
.prompt-stage-wrapper.stage-docked {
  top: auto;
  bottom: 20px;
  left: 50%;
  transform: translateX(-50%);
  width: 640px;
  max-width: 90%;
}

.hero-greeting {
  text-align: center;
  margin-bottom: 20px;
  transition: opacity 0.25s ease;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.stage-docked .hero-greeting { display: none; }

.hero-logo-img {
  width: 72px; height: 72px;
  border-radius: 16px; object-fit: cover;
  border: 1px solid rgba(255, 255, 255, 0.22);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.8), 0 0 30px rgba(56, 189, 248, 0.15);
  margin-bottom: 12px;
  transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.3s ease;
}
.hero-logo-img:hover {
  transform: scale(1.05);
}

.prompt-box {
  width: 100%;
  background: rgba(22, 27, 38, 0.95);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: var(--border-rim), 0 16px 48px rgba(0, 0, 0, 0.7);
  border-radius: 16px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: all 0.3s ease;
}
.prompt-box:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 24px rgba(56, 189, 248, 0.25), var(--border-rim);
}
.prompt-textarea {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-main);
  font-family: var(--font-sans);
  font-size: 0.9rem;
  resize: none;
  min-height: 48px;
  line-height: 1.5;
}
.prompt-textarea::placeholder { color: var(--text-dim); }

.prompt-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.prompt-chips {
  display: flex;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
  justify-content: center;
  transition: opacity 0.25s ease;
}
.stage-docked .prompt-chips { display: none; }

.chip {
  padding: 6px 12px;
  background: #161922;
  border: 1px solid var(--border);
  border-radius: 20px;
  font-size: 0.72rem;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
}
.chip:hover {
  background: #202636;
  border-color: rgba(255,255,255,0.2);
  color: var(--text-main);
}

/* RIGHT PANE: COWORKER AGENT & TRAJECTORY */
.sidecar-pane {
  background: var(--bg-sidebar);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidecar-header {
  padding: 10px 14px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase;
  color: var(--text-dim); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;
}

/* Chat & Stream History */
.chat-stream { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }

/* Tool Execution Accordion Card */
.tool-card {
  background: #141722; border: 1px solid var(--border); border-radius: 8px;
  overflow: hidden; font-size: 0.75rem;
}
.tool-card-header {
  padding: 8px 10px; background: #181c2a; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; font-weight: 600;
  user-select: none;
}
.tool-card-header:hover { background: #202638; }
.tool-badge { font-size: 0.62rem; font-family: var(--font-mono); padding: 2px 6px; border-radius: 4px; }
.tool-card-body { padding: 10px; font-family: var(--font-mono); font-size: 0.7rem; background: #0e1118; color: var(--text-muted); display: none; line-height: 1.6; }

/* Executive Decision HUD Card */
.decision-card {
  background: rgba(30, 25, 15, 0.9); border: 1px solid rgba(245, 158, 11, 0.5);
  box-shadow: var(--border-rim), 0 8px 24px rgba(0,0,0,0.5); border-radius: 10px; padding: 12px;
}
.btn-approve {
  background: var(--success); color: #022c22; font-weight: 700; font-size: 0.75rem;
  padding: 7px 12px; border-radius: 6px; border: none; cursor: pointer; flex: 1;
}
.btn-approve:hover { background: #34d399; }
.btn-deny {
  background: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 700; font-size: 0.75rem;
  padding: 7px 12px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.3); cursor: pointer; flex: 1;
}
.btn-deny:hover { background: rgba(239, 68, 68, 0.25); }

/* 3. BOTTOM STATUS STRIP (28px) */
.status-bar {
  height: 28px; background: #0c0e14; border-top: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 14px; font-size: 0.68rem; font-family: var(--font-mono); color: var(--text-dim);
}
.status-left { display: flex; align-items: center; gap: 14px; }
.status-right { display: flex; align-items: center; gap: 14px; }

.toast {
  position: fixed; bottom: 45px; right: 24px;
  background: #1c2130; border: 1px solid var(--border); box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  padding: 10px 16px; border-radius: 8px; font-size: 0.78rem; font-weight: 600; display: none; z-index: 500;
}
</style>
</head>
<body>

<!-- 1. TOP UTILITY BAR -->
<div class="top-bar">
  <div class="brand-group" onclick="resetToCenterPrompt()">
    <img src="/api/logo" id="top-brand-logo" alt="Anton Logo" class="brand-logo-img">
    <span class="brand-name" id="top-brand-name">ANTON</span>
    <span class="breadcrumb">workspace / devops / vault</span>
  </div>

  <div class="top-actions">
    <!-- Son of Anton Mode Button (No lightning bolt) -->
    <button class="son-toggle" id="son-toggle-btn" onclick="toggleSonOfAnton()">
      <span class="son-dot"></span>
      <span id="son-label">SON OF ANTON [OFF]</span>
    </button>
    <div style="font-size:0.75rem;color:var(--success);font-weight:700;display:flex;align-items:center;gap:6px">
      <span style="width:6px;height:6px;border-radius:50%;background:var(--success);box-shadow:0 0 6px var(--success)"></span>
      ONLINE
    </div>
  </div>
</div>

<!-- 2. MAIN 3-PANE WORKBENCH -->
<div class="workbench">
  <!-- LEFT PANE: NAVIGATOR -->
  <div class="nav-pane">
    <div class="nav-header">Knowledge & Code Tree</div>
    <div class="tree-container">
      <!-- Deterministic Python Gates -->
      <div class="tree-section">⚡ Python Verify Gates</div>
      <div class="tree-node" onclick="openFile('scripts/verify_balance.py')">
        <span>🐍 verify_balance.py</span><span class="tree-pill">0-LLM</span>
      </div>
      <div class="tree-node" onclick="openFile('anton/scheduler.py')">
        <span>🐍 scheduler.py</span><span class="tree-pill">ENGINE</span>
      </div>

      <!-- 100x Learned Skills -->
      <div class="tree-section">🧠 100x Learned Skills</div>
      <div class="tree-node" onclick="openFile('skills/100x-desktop-ide-designer')">
        <span>✦ 100x-desktop-ide</span><span class="tree-pill">0.98</span>
      </div>
      <div class="tree-node" onclick="openFile('skills/100x-gtm-strategist')">
        <span>✦ 100x-gtm-strategist</span><span class="tree-pill">0.98</span>
      </div>
      <div class="tree-node" onclick="openFile('skills/100x-pr-publicity-specialist')">
        <span>✦ 100x-pr-publicity</span><span class="tree-pill">0.96</span>
      </div>

      <!-- GTM Strategy Artifacts -->
      <div class="tree-section">📑 Strategy Artifacts</div>
      <div class="tree-node" onclick="openFile('strategy/award-marketing-plan')">
        <span>📄 award-marketing-plan</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-node" onclick="openFile('strategy/content-calendar')">
        <span>📅 content-calendar</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-node" onclick="openFile('strategy/pr-outreach-list')">
        <span>📰 pr-outreach-list</span><span class="tree-pill">MD</span>
      </div>

      <!-- Spatial Views -->
      <div class="tree-section">🌌 Spatial Views</div>
      <div class="tree-node" onclick="open3DGraph()">
        <span>🪐 3D Neural Second Brain</span><span class="tree-pill">GRAPH</span>
      </div>
    </div>
  </div>

  <!-- CENTER PANE: WORKSPACE & MONACO -->
  <div class="editor-pane">
    <!-- Multi-Tab Bar -->
    <div class="editor-tabs" id="editor-tab-bar">
      <!-- Populated dynamically -->
    </div>

    <!-- Content Buffers -->
    <div class="editor-body">
      <div id="monaco-container"></div>
      <div id="markdown-container" class="md-view"></div>
      <div id="graph-tab-container"></div>

      <!-- DYNAMIC PROMPT STAGE (Transitions from Center to Docked Bottom) -->
      <div class="prompt-stage-wrapper stage-center" id="prompt-stage">
        <div class="hero-greeting" id="hero-greeting-box">
          <img src="/api/logo" id="hero-brand-logo" alt="Anton Logo" class="hero-logo-img">
          <div style="font-size:1.25rem;font-weight:800;letter-spacing:-0.02em;margin-bottom:6px" id="hero-headline">What would you like Anton to do?</div>
          <div style="font-size:0.8rem;color:var(--text-muted)" id="hero-subheadline">Autonomous Coworker with Deterministic Gates & Second Brain Memory</div>
        </div>

        <div class="prompt-box">
          <textarea id="main-prompt-input" class="prompt-textarea" placeholder="Ask Anton anything, design a workflow, or search knowledge (↵ to run)..."></textarea>
          <div class="prompt-footer">
            <span style="font-size:0.68rem;font-family:var(--font-mono);color:var(--text-dim);background:#10131b;padding:2px 8px;border-radius:10px;border:1px solid var(--border)">
              Local [REDACTED-LOCAL-INFERENCE] ➔ Cloud Fallback
            </span>
            <button onclick="submitPrompt()" style="background:var(--primary);color:#082f49;font-weight:700;font-size:0.75rem;padding:5px 14px;border-radius:6px;border:none;cursor:pointer">
              Run ↵
            </button>
          </div>
        </div>

        <div class="prompt-chips" id="hero-chips">
          <div class="chip" onclick="applyChip('Reconcile Stripe payouts and QuickBooks ledger with $0.00 hard gate')">
            ⚡ Reconcile Stripe & QBO ($0.00 Gate)
          </div>
          <div class="chip" onclick="applyChip('Synthesize GTM launch plan and 2-week content calendar for SaaS award')">
            🏆 Launch 2026 SaaS Award GTM Campaign
          </div>
          <div class="chip" onclick="applyChip('Inspect 100x desktop IDE designer skill protocol')">
            🧠 Inspect 100x Desktop IDE Skill
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- RIGHT PANE: COWORKER AGENT & TRAJECTORY -->
  <div class="sidecar-pane">
    <div class="sidecar-header">
      <span>Agent Coworker & Gates</span>
      <span style="font-family:var(--font-mono);font-size:0.65rem">R1 FAILS-CLOSED</span>
    </div>

    <div class="chat-stream" id="agent-chat-stream">
      <!-- Executive Decision Card -->
      <div id="decision-hud-box">
        <div class="decision-card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <span style="font-size:0.65rem;font-weight:800;color:#fbbf24;text-transform:uppercase">Approval Gate #108</span>
            <span style="font-size:0.65rem;font-family:var(--font-mono);color:var(--text-dim)">7a3f89...</span>
          </div>
          <div style="font-size:0.85rem;font-weight:700;margin-bottom:4px">Action: Payout Reconcile ($14.50)</div>
          <div style="font-size:0.72rem;color:var(--text-muted);margin-bottom:10px">Discrepancy caught by verify_balance.py. Halting at human boundary.</div>
          <div style="display:flex;gap:8px">
            <button class="btn-approve" onclick="resolveApproval(108, 'approve')">✓ Approve (↵)</button>
            <button class="btn-deny" onclick="resolveApproval(108, 'deny')">✗ Deny (⎋)</button>
          </div>
        </div>
      </div>

      <!-- Execution Tool Cards -->
      <div class="tool-card">
        <div class="tool-card-header" onclick="toggleToolCard('tool-1')">
          <span>⚡ tool: python3 scripts/verify_balance.py</span>
          <span class="tool-badge" style="background:rgba(16,185,129,0.15);color:var(--success)">exit 0 · 0.005s ▾</span>
        </div>
        <div class="tool-card-body" id="tool-1">
          Input: {"stripe_total": 1450.00, "qbo_total": 1450.00}<br>
          Output: VERIFY PASSED. 0 tokens consumed. Zero hallucination.
        </div>
      </div>

      <div class="tool-card">
        <div class="tool-card-header" onclick="toggleToolCard('tool-2')">
          <span>🧠 ambition: 2026 SaaS Award GTM</span>
          <span class="tool-badge" style="background:rgba(192,132,252,0.15);color:var(--purple)">EV=0.95 · 100x-GTM ▾</span>
        </div>
        <div class="tool-card-body" id="tool-2">
          Self-learned 100x-gtm-strategist in isolated sandbox container.<br>
          Synthesized: award-marketing-plan.md, content-calendar.md, pr-outreach-list.md.
        </div>
      </div>
    </div>
  </div>
</div>

<!-- 3. BOTTOM STATUS STRIP -->
<div class="status-bar">
  <div class="status-left">
    <span>🌿 main (commit f29d8ab)</span>
    <span>⚡ Gates: Fail-Closed Active</span>
    <span id="active-mode-status">Mode: Safe Standard</span>
  </div>
  <div class="status-right">
    <span>Token Budget: $0.042 / $5.00 Cap</span>
    <span id="clock-display">UTC --:--:--</span>
  </div>
</div>

<div class="toast" id="toast-msg"></div>

<!-- Monaco Loader -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/loader.min.js"></script>
<script>
const $ = id => document.getElementById(id);

let editorInstance = null;
let sonOfAntonActive = false;
let hasSubmittedPrompt = false;

// Multi-Tab State
let openTabs = [];
let activeTabId = null;

function showToast(msg, type='info') {
  const t = $('toast-msg');
  t.textContent = msg; t.style.display = 'block';
  t.style.borderColor = type === 'success' ? '#10b981' : (type === 'error' ? '#ef4444' : '#f59e0b');
  setTimeout(() => t.style.display = 'none', 3000);
}

function updateClock() {
  $('clock-display').textContent = 'UTC ' + new Date().toISOString().substring(11, 19);
}
setInterval(updateClock, 1000); updateClock();

// Monaco Init
require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs' }});

require(['vs/editor/editor.main'], function() {
  editorInstance = monaco.editor.create(document.getElementById('monaco-container'), {
    value: '',
    language: 'python',
    theme: 'vs-dark',
    automaticLayout: true,
    fontSize: 13,
    fontFamily: 'JetBrains Mono, Menlo, monospace',
    minimap: { enabled: false },
    lineNumbers: 'on',
    renderLineHighlight: 'all',
    scrollBeyondLastLine: false
  });
});

// Render Tab Bar
function renderTabBar() {
  const bar = $('editor-tab-bar');
  if (openTabs.length === 0) {
    bar.innerHTML = '';
    showBuffer('empty');
    return;
  }

  bar.innerHTML = openTabs.map(t => `
    <div class="tab ${t.id === activeTabId ? 'active' : ''}" onclick="switchTab('${t.id}')">
      <span>${t.title}</span>
      <span class="tab-close-btn" onclick="closeTab('${t.id}', event)">✕</span>
    </div>
  `).join('');

  const activeTab = openTabs.find(t => t.id === activeTabId);
  if (activeTab) {
    showBuffer(activeTab.type, activeTab.content);
  }
}

function showBuffer(type, content='') {
  const mCont = $('monaco-container');
  const mdCont = $('markdown-container');
  const gCont = $('graph-tab-container');

  mCont.style.display = 'none';
  mdCont.style.display = 'none';
  gCont.style.display = 'none';

  if (type === 'code') {
    mCont.style.display = 'block';
    if (editorInstance) {
      editorInstance.setValue(content);
      editorInstance.layout();
    }
  } else if (type === 'markdown') {
    mdCont.style.display = 'block';
    mdCont.innerHTML = marked.parse(content);
  } else if (type === 'graph') {
    gCont.style.display = 'block';
    init3DGraphInContainer();
  }
}

async function openFile(path) {
  dockPromptStage();

  const basename = path.split('/').pop();
  const existing = openTabs.find(t => t.id === path);

  if (existing) {
    activeTabId = path;
    renderTabBar();
    return;
  }

  try {
    const res = await fetch(`/api/vault/note?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    const isCode = data.is_code || path.endsWith('.py');

    openTabs.push({
      id: path,
      title: basename,
      type: isCode ? 'code' : 'markdown',
      content: data.content || ''
    });

    activeTabId = path;
    renderTabBar();
  } catch (e) {
    showToast('Failed to open file: ' + e.message, 'error');
  }
}

function open3DGraph() {
  dockPromptStage();
  const existing = openTabs.find(t => t.id === '3d-graph');
  if (existing) {
    activeTabId = '3d-graph';
    renderTabBar();
    return;
  }
  openTabs.push({
    id: '3d-graph',
    title: '🪐 3D Second Brain',
    type: 'graph',
    content: ''
  });
  activeTabId = '3d-graph';
  renderTabBar();
}

function switchTab(tabId) {
  activeTabId = tabId;
  renderTabBar();
}

function closeTab(tabId, event) {
  if (event) event.stopPropagation();
  const idx = openTabs.findIndex(t => t.id === tabId);
  if (idx === -1) return;

  openTabs.splice(idx, 1);

  if (activeTabId === tabId) {
    if (openTabs.length > 0) {
      activeTabId = openTabs[Math.max(0, idx - 1)].id;
    } else {
      activeTabId = null;
      if (!hasSubmittedPrompt) resetToCenterPrompt();
    }
  }
  renderTabBar();
}

function init3DGraphInContainer() {
  const gCont = $('graph-tab-container');
  if (!window.graphLoaded) {
    window.graphLoaded = true;
    fetch('/api/vault/graph').then(r => r.json()).then(gData => {
      ForceGraph3D()(gCont)
        .graphData(gData)
        .nodeLabel('title')
        .nodeColor(n => n.type === 'moc' ? '#c084fc' : (n.type === 'skill' ? '#10b981' : '#38bdf8'))
        .nodeVal('val')
        .linkWidth(1.2)
        .onNodeClick(n => openFile(n.id));
    });
  }
}

function dockPromptStage() {
  const stage = $('prompt-stage');
  stage.classList.remove('stage-center');
  stage.classList.add('stage-docked');
  hasSubmittedPrompt = true;
}

function resetToCenterPrompt() {
  const stage = $('prompt-stage');
  stage.classList.remove('stage-docked');
  stage.classList.add('stage-center');
  hasSubmittedPrompt = false;
  openTabs = [];
  activeTabId = null;
  renderTabBar();
  $('main-prompt-input').focus();
}

function applyChip(text) {
  $('main-prompt-input').value = text;
  submitPrompt();
}

async function submitPrompt() {
  const input = $('main-prompt-input');
  const q = input.value.trim();
  if (!q) return;

  dockPromptStage();
  input.value = '';

  const stream = $('agent-chat-stream');
  stream.innerHTML += `
    <div style="padding:8px 10px;background:#1e2436;border-radius:8px;font-size:0.78rem">
      <div style="font-weight:700;color:var(--primary);margin-bottom:2px">You</div>
      <div>${q}</div>
    </div>
  `;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: q })
    });
    const data = await res.json();
    stream.innerHTML += `
      <div style="padding:8px 10px;background:#141722;border:1px solid var(--border);border-radius:8px;font-size:0.78rem">
        <div style="font-weight:700;color:var(--purple);margin-bottom:2px">⚡ Anton</div>
        <div>${data.reply}</div>
      </div>
    `;
    if (data.note_path) openFile(data.note_path);
    stream.scrollTop = stream.scrollHeight;
  } catch (e) {
    showToast('Execution error: ' + e.message, 'error');
  }
}

$('main-prompt-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    submitPrompt();
  }
});

function toggleToolCard(id) {
  const el = $(id);
  el.style.display = (el.style.display === 'block') ? 'none' : 'block';
}

function updateSonUI() {
  const btn = $('son-toggle-btn');
  const lbl = $('son-label');
  const stat = $('active-mode-status');
  const topLogo = $('top-brand-logo');
  const heroLogo = $('hero-brand-logo');
  const brandName = $('top-brand-name');
  const heroHead = $('hero-headline');
  const heroSub = $('hero-subheadline');

  if (sonOfAntonActive) {
    btn.classList.add('active');
    lbl.textContent = 'SON OF ANTON [ACTIVE]';
    stat.textContent = 'Mode: Son of Anton (Overdrive)';
    stat.style.color = '#fbbf24';
    if (topLogo) topLogo.src = '/api/logo/son-of-anton';
    if (heroLogo) heroLogo.src = '/api/logo/son-of-anton';
    if (brandName) brandName.textContent = 'SON OF ANTON';
    if (heroHead) heroHead.textContent = 'What should Son of Anton execute?';
    if (heroSub) heroSub.textContent = 'Autonomous Overdrive · Zero Human Gate Delays';
  } else {
    btn.classList.remove('active');
    lbl.textContent = 'SON OF ANTON [OFF]';
    stat.textContent = 'Mode: Safe Standard';
    stat.style.color = 'var(--text-dim)';
    if (topLogo) topLogo.src = '/api/logo';
    if (heroLogo) heroLogo.src = '/api/logo';
    if (brandName) brandName.textContent = 'ANTON';
    if (heroHead) heroHead.textContent = 'What would you like Anton to do?';
    if (heroSub) heroSub.textContent = 'Autonomous Coworker with Deterministic Gates & Second Brain Memory';
  }
}

async function checkMode() {
  try {
    const res = await fetch('/api/mode');
    const data = await res.json();
    sonOfAntonActive = !!data.son_of_anton_mode;
    updateSonUI();
  } catch (e) {}
}

async function toggleSonOfAnton() {
  const nextState = !sonOfAntonActive;
  try {
    const res = await fetch('/api/mode/son-of-anton', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ son_of_anton_mode: nextState })
    });
    if (res.ok) {
      sonOfAntonActive = nextState;
      updateSonUI();
      showToast(sonOfAntonActive ? 'Son of Anton Mode ENGAGED' : 'Standard Safe Mode Restored', sonOfAntonActive ? 'warning' : 'success');
    }
  } catch (e) {
    showToast('Failed to toggle mode', 'error');
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
      showToast(`Approval #${aid} marked as ${decision.toUpperCase()}`, 'success');
      const box = $('decision-hud-box');
      if (box) {
        box.innerHTML = `<div style="padding:10px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.3);border-radius:8px;font-size:0.75rem;color:#34d399;text-align:center">✓ Gate Resolved (${decision.toUpperCase()})</div>`;
      }
    }
  } catch (e) {
    showToast(e.message, 'error');
  }
}

window.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    $('main-prompt-input').focus();
  } else if (e.key === 'Enter' && document.activeElement !== $('main-prompt-input')) {
    resolveApproval(108, 'approve');
  } else if (e.key === 'Escape' && document.activeElement !== $('main-prompt-input')) {
    resolveApproval(108, 'deny');
  }
});

checkMode();
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

class ChatReq(BaseModel):
    prompt: str

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

    @app.get("/api/logo")
    def get_logo():
        """Serves the approved classic Anton logo image."""
        install_dir = os.path.dirname(data_dir) if data_dir.endswith(".dev-data") else os.getcwd()
        logo_paths = [
            os.path.join(install_dir, "assets", "logos", "anton_logo.jpg"),
            "/Users/ai/rooms/devops/assets/logos/anton_dark_bw_icon_1787167963726.jpg",
            "/Users/ai/.gemini/antigravity/brain/b4a39c00-3096-4125-90bf-242cf7d5b2cc/anton_logo.jpg"
        ]
        for p in logo_paths:
            if os.path.exists(p):
                return FileResponse(p, media_type="image/jpeg")
        raise HTTPException(404, "logo image not found")

    @app.get("/api/logo/son-of-anton")
    def get_son_of_anton_logo():
        """Serves the young & reckless Son of Anton logo."""
        install_dir = os.path.dirname(data_dir) if data_dir.endswith(".dev-data") else os.getcwd()
        svg_paths = [
            os.path.join(install_dir, "assets", "logos", "son_of_anton_logo.svg"),
            "/Users/ai/.gemini/antigravity/brain/b4a39c00-3096-4125-90bf-242cf7d5b2cc/son_of_anton_logo.svg"
        ]
        for p in svg_paths:
            if os.path.exists(p):
                return FileResponse(p, media_type="image/svg+xml")
        raise HTTPException(404, "son of anton logo not found")

    @app.get("/api/mode")
    def get_mode():
        return {"son_of_anton_mode": engine.son_of_anton_mode}

    @app.post("/api/mode/son-of-anton")
    def set_mode(req: ModeReq, request: Request):
        _require_token(request, token)
        engine.son_of_anton_mode = req.son_of_anton_mode
        return {"status": "updated", "son_of_anton_mode": engine.son_of_anton_mode}

    @app.get("/api/vault/note")
    def get_vault_note(path: str):
        """Fetches and serves markdown or python code for the in-app document viewer."""
        install_dir = os.path.dirname(data_dir) if data_dir.endswith(".dev-data") else os.getcwd()
        candidates = [
            os.path.join(install_dir, path),
            os.path.join(data_dir, "vault", path + ".md"),
            os.path.join(data_dir, "vault", path),
            os.path.join(data_dir, path),
            os.path.join(data_dir, "skills", path.replace("skills/", ""), "SKILL.md"),
            os.path.join(install_dir, "scripts", os.path.basename(path))
        ]
        
        found = None
        for c in candidates:
            if os.path.exists(c) and os.path.isfile(c):
                found = c
                break
                
        if not found:
            raise HTTPException(404, f"file not found: {path}")
            
        with open(found, "r", encoding="utf-8") as f:
            content = f.read()
            
        is_code = found.endswith(".py") or found.endswith(".sh") or found.endswith(".yaml")
        return {"path": path, "content": content, "is_code": is_code}

    @app.post("/api/chat")
    def chat_prompt(req: ChatReq):
        """Handles regular conversational interactions and Second Brain queries."""
        p_lower = req.prompt.lower()
        if "reconcil" in p_lower or "math" in p_lower or "script" in p_lower or "gate" in p_lower:
            return {
                "reply": "Opened Python deterministic verify gate: scripts/verify_balance.py (0 tokens consumed).",
                "note_path": "scripts/verify_balance.py"
            }
        elif "award" in p_lower or "marketing" in p_lower or "gtm" in p_lower:
            return {
                "reply": "I've synthesized the 2026 SaaS Innovation Award campaign across 3 artifacts in the Second Brain.",
                "note_path": "strategy/award-marketing-plan"
            }
        elif "skill" in p_lower or "desktop" in p_lower or "designer" in p_lower:
            return {
                "reply": "Loaded staff-level protocol from Second Brain.",
                "note_path": "skills/100x-desktop-ide-designer"
            }
        else:
            return {
                "reply": f"Anton processed: '{req.prompt}'. Second Brain query completed.",
                "note_path": "strategy/award-marketing-plan"
            }

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
                    {"id": "skills/100x-desktop-ide-designer", "title": "100x Desktop IDE", "type": "skill", "val": 8}
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
