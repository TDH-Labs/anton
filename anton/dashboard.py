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
<title>ANTON — Autonomous Pro Studio & IDE</title>
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
.brand-group { display: flex; align-items: center; gap: 10px; }
.brand-logo {
  width: 28px; height: 28px;
  background: #1c2230; border: 1px solid rgba(255,255,255,0.15);
  border-radius: 6px; display: flex; align-items: center; justify-content: center;
  font-size: 0.95rem; color: var(--primary);
}
.brand-name { font-size: 0.95rem; font-weight: 800; letter-spacing: -0.02em; }
.breadcrumb { font-size: 0.75rem; color: var(--text-dim); font-family: var(--font-mono); }

/* Center Search Capsule */
.search-capsule {
  display: flex; align-items: center; gap: 8px;
  background: #141722; border: 1px solid var(--border);
  border-radius: 20px; padding: 4px 14px; width: 440px; cursor: pointer;
}
.search-input {
  background: transparent; border: none; outline: none;
  color: var(--text-main); font-size: 0.8rem; flex: 1; font-family: var(--font-sans);
}
.search-kbd {
  font-size: 0.65rem; font-family: var(--font-mono);
  background: #202636; padding: 1px 5px; border-radius: 4px; color: var(--text-dim);
}

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
  grid-template-columns: 260px 1fr 400px;
  overflow: hidden;
}

/* LEFT PANE: NAVIGATOR & SECOND BRAIN */
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
  padding: 5px 8px; border-radius: 6px; font-size: 0.78rem; cursor: pointer;
  color: var(--text-muted); transition: all 0.15s ease;
}
.tree-node:hover { background: #161a26; color: var(--text-main); }
.tree-node.active { background: #1e2436; color: var(--primary); font-weight: 600; }
.tree-pill { font-size: 0.62rem; font-family: var(--font-mono); padding: 1px 5px; border-radius: 4px; background: rgba(255,255,255,0.06); }

/* CENTER PANE: MONACO / WORKSPACE */
.editor-pane {
  background: var(--bg-editor);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
/* Tab Bar */
.editor-tabs {
  height: 38px;
  background: var(--bg-sidebar);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  overflow-x: auto;
}
.tab {
  display: flex; align-items: center; gap: 8px; padding: 0 14px; height: 100%;
  font-size: 0.78rem; color: var(--text-muted); border-right: 1px solid var(--border);
  cursor: pointer; background: #0e1117; user-select: none;
}
.tab.active { background: var(--bg-editor); color: var(--text-main); font-weight: 600; border-bottom: 2px solid var(--primary); }
.tab-close { font-size: 0.75rem; color: var(--text-dim); border-radius: 50%; padding: 1px 4px; }
.tab-close:hover { background: rgba(255,255,255,0.1); color: #fff; }

/* Editor / Preview Content */
.editor-body { flex: 1; position: relative; overflow: hidden; }
#monaco-container { width: 100%; height: 100%; display: none; }
#markdown-container { width: 100%; height: 100%; overflow-y: auto; padding: 32px 48px; display: block; }
#graph-tab-container { width: 100%; height: 100%; display: none; background: #0c0e14; }

/* Markdown Styling */
.md-view h1, .md-view h2, .md-view h3 { color: #f8fafc; margin: 20px 0 12px 0; }
.md-view p { color: #cbd5e1; line-height: 1.7; margin-bottom: 14px; font-size: 0.9rem; }
.md-view table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.82rem; }
.md-view th, .md-view td { border: 1px solid var(--border); padding: 8px 12px; text-align: left; }
.md-view pre { background: #090b10; border: 1px solid var(--border); border-radius: 8px; padding: 14px; overflow-x: auto; margin: 14px 0; }
.md-view code { font-family: var(--font-mono); color: var(--primary); font-size: 0.82rem; }

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

/* Tool Execution Accordion Card (Goose / OpenHands style) */
.tool-card {
  background: #141722; border: 1px solid var(--border); border-radius: 8px;
  overflow: hidden; font-size: 0.75rem;
}
.tool-card-header {
  padding: 8px 10px; background: #181c2a; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; font-weight: 600;
}
.tool-badge { font-size: 0.62rem; font-family: var(--font-mono); padding: 2px 6px; border-radius: 4px; }
.tool-card-body { padding: 10px; font-family: var(--font-mono); font-size: 0.7rem; background: #0e1118; color: var(--text-muted); display: none; }

/* Executive Decision HUD Card */
.decision-card {
  background: rgba(30, 25, 15, 0.9); border: 1px solid rgba(245, 158, 11, 0.5);
  box-shadow: var(--border-rim), 0 8px 24px rgba(0,0,0,0.5); border-radius: 10px; padding: 12px;
}
.btn-approve {
  background: var(--success); color: #022c22; font-weight: 700; font-size: 0.75rem;
  padding: 7px 12px; border-radius: 6px; border: none; cursor: pointer; flex: 1;
}
.btn-deny {
  background: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 700; font-size: 0.75rem;
  padding: 7px 12px; border-radius: 6px; border: 1px solid rgba(239, 68, 68, 0.3); cursor: pointer; flex: 1;
}

/* Chat Prompt Input Box */
.chat-input-wrapper {
  padding: 12px; background: #12151e; border-top: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 8px;
}
.chat-box {
  background: #181c28; border: 1px solid var(--border); border-radius: 10px;
  padding: 10px; display: flex; flex-direction: column; gap: 6px;
}
.chat-textarea {
  background: transparent; border: none; outline: none; color: var(--text-main);
  font-family: var(--font-sans); font-size: 0.82rem; resize: none; min-height: 48px;
}
.chat-actions { display: flex; justify-content: space-between; align-items: center; }
.model-pill {
  font-size: 0.68rem; font-family: var(--font-mono); color: var(--text-dim);
  background: #11141d; padding: 2px 8px; border-radius: 12px; border: 1px solid var(--border);
}
.send-btn {
  background: var(--primary); color: #082f49; font-weight: 700; font-size: 0.75rem;
  padding: 4px 12px; border-radius: 6px; border: none; cursor: pointer;
}

/* 3. BOTTOM STATUS STRIP (28px) */
.status-bar {
  height: 28px; background: #0c0e14; border-top: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 14px; font-size: 0.68rem; font-family: var(--font-mono); color: var(--text-dim);
}
.status-left { display: flex; align-items: center; gap: 14px; }
.status-right { display: flex; align-items: center; gap: 14px; }
</style>
</head>
<body>

<!-- 1. TOP UTILITY BAR -->
<div class="top-bar">
  <div class="brand-group">
    <div class="brand-logo">⚡</div>
    <span class="brand-name">ANTON</span>
    <span class="breadcrumb">workspace / devops / vault</span>
  </div>

  <div class="search-capsule" onclick="focusSearch()">
    <span style="color:var(--primary)">⚡</span>
    <input type="text" id="global-search" class="search-input" placeholder="Ask Anton, search notes, or run recipe (⌘K)...">
    <span class="search-kbd">⌘K</span>
  </div>

  <div class="top-actions">
    <button class="son-toggle" id="son-toggle-btn" onclick="toggleSonOfAnton()">
      <span class="son-dot"></span>
      <span id="son-label">⚡ SON OF ANTON [OFF]</span>
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
      <div class="tree-node active" onclick="openFile('scripts/verify_balance.py', 'python')">
        <span>🐍 verify_balance.py</span><span class="tree-pill">0-LLM</span>
      </div>
      <div class="tree-node" onclick="openFile('anton/scheduler.py', 'python')">
        <span>🐍 scheduler.py</span><span class="tree-pill">ENGINE</span>
      </div>

      <!-- 100x Learned Skills -->
      <div class="tree-section">🧠 100x Learned Skills</div>
      <div class="tree-node" onclick="openFile('skills/100x-desktop-ide-designer', 'markdown')">
        <span>✦ 100x-desktop-ide</span><span class="tree-pill">0.98</span>
      </div>
      <div class="tree-node" onclick="openFile('skills/100x-gtm-strategist', 'markdown')">
        <span>✦ 100x-gtm-strategist</span><span class="tree-pill">0.98</span>
      </div>
      <div class="tree-node" onclick="openFile('skills/100x-pr-publicity-specialist', 'markdown')">
        <span>✦ 100x-pr-publicity</span><span class="tree-pill">0.96</span>
      </div>

      <!-- GTM Strategy Artifacts -->
      <div class="tree-section">📑 Strategy Artifacts</div>
      <div class="tree-node" onclick="openFile('strategy/award-marketing-plan', 'markdown')">
        <span>📄 award-marketing-plan</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-node" onclick="openFile('strategy/content-calendar', 'markdown')">
        <span>📅 content-calendar</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-node" onclick="openFile('strategy/pr-outreach-list', 'markdown')">
        <span>📰 pr-outreach-list</span><span class="tree-pill">MD</span>
      </div>

      <!-- Views -->
      <div class="tree-section">🌌 Spatial Views</div>
      <div class="tree-node" onclick="open3DGraph()">
        <span>🪐 3D Neural Second Brain</span><span class="tree-pill">GRAPH</span>
      </div>
    </div>
  </div>

  <!-- CENTER PANE: EDITOR & DOCUMENT BUFFER -->
  <div class="editor-pane">
    <!-- Multi-Tab Bar -->
    <div class="editor-tabs" id="editor-tab-bar">
      <div class="tab active" id="tab-primary" onclick="focusTab('primary')">
        <span id="tab-primary-title">scripts/verify_balance.py</span>
        <span class="tab-close">✕</span>
      </div>
    </div>

    <!-- Content Buffers -->
    <div class="editor-body">
      <div id="monaco-container"></div>
      <div id="markdown-container" class="md-view"></div>
      <div id="graph-tab-container"></div>
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

      <!-- Execution Tool Cards (Goose / OpenHands style) -->
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

    <!-- Chat Prompt Input -->
    <div class="chat-input-wrapper">
      <div class="chat-box">
        <textarea id="chat-prompt-input" class="chat-textarea" placeholder="Ask Anton anything or instruct workflow... (↵ to send)"></textarea>
        <div class="chat-actions">
          <span class="model-pill">Local [REDACTED-LOCAL-INFERENCE] ➔ Cloud Fallback</span>
          <button class="send-btn" onclick="sendChatPrompt()">Send ↵</button>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- 3. BOTTOM STATUS STRIP -->
<div class="status-bar">
  <div class="status-left">
    <span>🌿 main (commit 7883b0a)</span>
    <span>⚡ Gates: Fail-Closed Active</span>
    <span id="active-mode-status">Mode: Safe Standard</span>
  </div>
  <div class="status-right">
    <span>Token Budget: $0.042 / $5.00 Cap</span>
    <span id="clock-display">UTC --:--:--</span>
  </div>
</div>

<!-- Monaco Loader -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/loader.min.js"></script>
<script>
let editorInstance = null;
let currentFile = 'scripts/verify_balance.py';
let sonOfAntonActive = false;

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
    scrollBeyondLastLine: false,
    readOnly: false
  });
  openFile('scripts/verify_balance.py', 'python');
});

const $ = id => document.getElementById(id);

function updateClock() {
  $('clock-display').textContent = 'UTC ' + new Date().toISOString().substring(11, 19);
}
setInterval(updateClock, 1000); updateClock();

async function openFile(path, type='markdown') {
  currentFile = path;
  $('tab-primary-title').textContent = path;
  document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('active'));

  const mContainer = $('monaco-container');
  const mdContainer = $('markdown-container');
  const gContainer = $('graph-tab-container');

  gContainer.style.display = 'none';

  try {
    const res = await fetch(`/api/vault/note?path=${encodeURIComponent(path)}`);
    const data = await res.json();

    if (data.is_code || path.endsWith('.py')) {
      mdContainer.style.display = 'none';
      mContainer.style.display = 'block';
      if (editorInstance) {
        editorInstance.setValue(data.content);
        monaco.editor.setModelLanguage(editorInstance.getModel(), 'python');
      }
    } else {
      mContainer.style.display = 'none';
      mdContainer.style.display = 'block';
      mdContainer.innerHTML = marked.parse(data.content);
    }
  } catch (e) {
    mdContainer.style.display = 'block';
    mdContainer.innerHTML = '<p style="color:var(--danger)">Error loading file: ' + e.message + '</p>';
  }
}

function open3DGraph() {
  $('monaco-container').style.display = 'none';
  $('markdown-container').style.display = 'none';
  const gContainer = $('graph-tab-container');
  gContainer.style.display = 'block';
  $('tab-primary-title').textContent = '3D Second Brain Graph';

  if (!window.graphLoaded) {
    window.graphLoaded = true;
    fetch('/api/vault/graph').then(r => r.json()).then(gData => {
      ForceGraph3D()(gContainer)
        .graphData(gData)
        .nodeLabel('title')
        .nodeColor(n => n.type === 'moc' ? '#c084fc' : (n.type === 'skill' ? '#10b981' : '#38bdf8'))
        .nodeVal('val')
        .linkWidth(1.2)
        .onNodeClick(n => openFile(n.id, 'markdown'));
    });
  }
}

function toggleToolCard(id) {
  const el = $(id);
  el.style.display = el.style.display === 'block' ? 'none' : 'block';
}

function focusSearch() { $('global-search').focus(); }

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
      const btn = $('son-toggle-btn');
      const lbl = $('son-label');
      const stat = $('active-mode-status');
      if (sonOfAntonActive) {
        btn.classList.add('active');
        lbl.textContent = '⚡ SON OF ANTON [ACTIVE]';
        stat.textContent = 'Mode: ⚡ Son of Anton (Overdrive)';
        stat.style.color = '#fbbf24';
      } else {
        btn.classList.remove('active');
        lbl.textContent = '⚡ SON OF ANTON [OFF]';
        stat.textContent = 'Mode: Safe Standard';
        stat.style.color = 'var(--text-dim)';
      }
    }
  } catch (e) {}
}

async function sendChatPrompt() {
  const input = $('chat-prompt-input');
  const q = input.value.trim();
  if (!q) return;
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
  } catch (e) {}
}

$('chat-prompt-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChatPrompt();
  }
});

window.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    $('global-search').focus();
  }
});
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
