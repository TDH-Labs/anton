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

PAGE = r"""<!doctype html>
<html lang="en" data-theme="system">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ANTON — Autonomous Workbench</title>
<link rel="icon" type="image/jpeg" href="/api/logo">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" data-name="vs/editor/editor.main" href="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/editor/editor.main.min.css">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://unpkg.com/3d-force-graph"></script>
<style>
/* === THEME VARIABLES === */
:root {
  --primary:#38bdf8; --primary-hover:#0284c7; --accent:#818cf8;
  --success:#10b981; --warning:#f59e0b; --danger:#ef4444; --purple:#c084fc;
  --font-sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --font-mono:'JetBrains Mono',ui-monospace,Menlo,monospace;
}
/* Light (default for system) */
[data-theme="light"],[data-theme="system"]{
  --bg-app:#f8fafc; --bg-sidebar:#f1f5f9; --bg-surface:#fff; --bg-card:#fff;
  --bg-card-hover:#f1f5f9; --bg-input:#fff; --border:#e2e8f0;
  --border-focus:#38bdf8; --text-main:#0f172a; --text-muted:#475569;
  --text-dim:#94a3b8; --shadow-sm:0 1px 3px rgba(0,0,0,.06);
  --shadow-lg:0 12px 32px rgba(0,0,0,.08); --code-bg:#f1f5f9;
}
@media(prefers-color-scheme:dark){
  [data-theme="system"]{
    --bg-app:#090b10; --bg-sidebar:#0e1117; --bg-surface:#131620;
    --bg-card:#181c28; --bg-card-hover:#202636; --bg-input:#141722;
    --border:rgba(255,255,255,.08); --border-focus:rgba(56,189,248,.5);
    --text-main:#f8fafc; --text-muted:#94a3b8; --text-dim:#64748b;
    --shadow-sm:0 1px 3px rgba(0,0,0,.4); --shadow-lg:0 16px 48px rgba(0,0,0,.6);
    --code-bg:#0c0e14;
  }
}
[data-theme="dark"]{
  --bg-app:#090b10; --bg-sidebar:#0e1117; --bg-surface:#131620;
  --bg-card:#181c28; --bg-card-hover:#202636; --bg-input:#141722;
  --border:rgba(255,255,255,.08); --border-focus:rgba(56,189,248,.5);
  --text-main:#f8fafc; --text-muted:#94a3b8; --text-dim:#64748b;
  --shadow-sm:0 1px 3px rgba(0,0,0,.4); --shadow-lg:0 16px 48px rgba(0,0,0,.6);
  --code-bg:#0c0e14;
}

/* === RESET & BODY === */
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-sans);background:var(--bg-app);color:var(--text-main);
  height:100vh;overflow:hidden;display:flex;flex-direction:column;
  transition:background .2s,color .2s}

/* === TOP BAR (48px) === */
.top-bar{height:48px;background:var(--bg-sidebar);border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 14px;
  flex-shrink:0;z-index:100}
.brand-group{display:flex;align-items:center;gap:10px;cursor:pointer}
.brand-logo{width:28px;height:28px;border-radius:6px;object-fit:cover;
  border:1px solid var(--border);box-shadow:var(--shadow-sm)}
.brand-name{font-size:.92rem;font-weight:800;letter-spacing:-.02em}
.breadcrumb{font-size:.72rem;color:var(--text-dim);font-family:var(--font-mono)}
.top-actions{display:flex;align-items:center;gap:10px}
.son-toggle{display:flex;align-items:center;gap:6px;padding:4px 12px;
  background:var(--bg-card);border:1px solid var(--border);border-radius:20px;
  cursor:pointer;font-size:.68rem;font-weight:800;text-transform:uppercase;
  color:var(--text-muted);transition:all .2s}
.son-toggle:hover{border-color:var(--border-focus)}
.son-toggle.active{background:rgba(245,158,11,.15);border-color:rgba(245,158,11,.6);
  color:#fbbf24;box-shadow:0 0 14px rgba(245,158,11,.25)}
.son-dot{width:7px;height:7px;border-radius:50%;background:var(--text-dim)}
.son-toggle.active .son-dot{background:#fbbf24;box-shadow:0 0 8px #fbbf24}
.icon-btn{background:var(--bg-card);border:1px solid var(--border);color:var(--text-muted);
  padding:5px 10px;border-radius:8px;cursor:pointer;font-size:.8rem;font-weight:600;
  display:flex;align-items:center;gap:6px;transition:all .15s}
.icon-btn:hover{background:var(--bg-card-hover);color:var(--text-main)}
.status-dot{width:6px;height:6px;border-radius:50%;background:var(--success);
  box-shadow:0 0 6px var(--success)}

/* === WORKBENCH (flex:1, horizontal 3-panel) === */
.workbench{flex:1;display:flex;overflow:hidden}

/* === LEFT SIDEBAR (260px → 48px icon rail) === */
.left-sidebar{width:260px;background:var(--bg-sidebar);border-right:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden;flex-shrink:0;
  transition:width .25s cubic-bezier(.16,1,.3,1)}
.left-sidebar.collapsed{width:48px}
.sidebar-top{display:flex;align-items:center;justify-content:space-between;
  padding:10px 12px;border-bottom:1px solid var(--border);flex-shrink:0}
.sidebar-title{font-size:.7rem;font-weight:800;text-transform:uppercase;
  color:var(--text-dim);letter-spacing:.04em;white-space:nowrap;overflow:hidden}
.left-sidebar.collapsed .sidebar-title{display:none}
.sidebar-collapse-btn{background:none;border:none;color:var(--text-dim);cursor:pointer;
  font-size:.85rem;padding:4px;border-radius:4px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;width:24px;height:24px}
.sidebar-collapse-btn:hover{background:var(--bg-card-hover);color:var(--text-main)}
.sidebar-body{flex:1;overflow-y:auto;overflow-x:hidden;padding:6px}
.left-sidebar.collapsed .sidebar-body{display:none}
.tree-section{font-size:.68rem;font-weight:700;color:var(--text-dim);
  text-transform:uppercase;padding:10px 6px 4px 6px;white-space:nowrap}
.tree-node{display:flex;align-items:center;justify-content:space-between;
  padding:6px 8px;border-radius:6px;font-size:.78rem;cursor:pointer;
  color:var(--text-muted);transition:all .12s;user-select:none;white-space:nowrap}
.tree-node:hover{background:var(--bg-card-hover);color:var(--text-main)}
.tree-node.active{background:var(--bg-card);color:var(--primary);font-weight:600}
.tree-pill{font-size:.62rem;font-family:var(--font-mono);padding:1px 5px;
  border-radius:4px;background:rgba(0,0,0,.06)}

/* === CENTER WORKSPACE (flex:1, vertical column) === */
.center-ws{flex:1;min-width:0;display:flex;flex-direction:column;
  background:var(--bg-app);overflow:hidden}

/* Messages scroll area — takes all available vertical space */
.msg-scroll{flex:1;overflow-y:auto;overflow-x:hidden;display:flex;
  flex-direction:column;padding:0}
/* When empty, center the hero via inner wrapper */
.msg-inner{display:flex;flex-direction:column;min-height:100%;padding:20px 28px 20px 28px}

/* Zero-state hero — centered in available space */
.zero-state{flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;text-align:center;gap:8px;padding-bottom:40px}
.zero-state.hidden{display:none}
.hero-logo{width:72px;height:72px;border-radius:16px;object-fit:cover;
  border:1px solid var(--border);box-shadow:var(--shadow-lg);margin-bottom:8px}
.hero-title{font-size:1.3rem;font-weight:800;letter-spacing:-.02em}
.hero-sub{font-size:.82rem;color:var(--text-muted)}
.hero-chips{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:16px}
.chip{padding:6px 12px;background:var(--bg-surface);border:1px solid var(--border);
  border-radius:20px;font-size:.72rem;color:var(--text-muted);cursor:pointer;
  transition:all .15s}
.chip:hover{background:var(--bg-card-hover);border-color:var(--border-focus);
  color:var(--text-main)}

/* Conversation cards (messages, tool cards, approval cards) */
.msg-card{padding:12px 16px;border:1px solid var(--border);border-radius:10px;
  font-size:.85rem;margin-bottom:12px}
.msg-card.user{background:var(--bg-card)}
.msg-card.agent{background:var(--bg-surface)}
.msg-sender{font-weight:700;margin-bottom:3px}
.msg-sender.user-name{color:var(--primary)}
.msg-sender.agent-name{color:var(--purple)}
.tool-card{background:var(--bg-surface);border:1px solid var(--border);
  border-radius:8px;overflow:hidden;font-size:.75rem;box-shadow:var(--shadow-sm);
  margin-bottom:12px}
.tool-card-hdr{padding:8px 12px;background:var(--bg-card);cursor:pointer;
  display:flex;align-items:center;justify-content:space-between;font-weight:600;
  user-select:none}
.tool-card-hdr:hover{background:var(--bg-card-hover)}
.tool-badge{font-size:.62rem;font-family:var(--font-mono);padding:2px 6px;
  border-radius:4px}
.tool-card-body{padding:12px;font-family:var(--font-mono);font-size:.72rem;
  background:var(--code-bg);color:var(--text-muted);display:none;line-height:1.6;
  border-top:1px solid var(--border)}
.decision-card{background:var(--bg-surface);border:1px solid rgba(245,158,11,.5);
  box-shadow:var(--shadow-sm);border-radius:10px;padding:14px;margin-bottom:12px}
.btn-approve{background:var(--success);color:#fff;font-weight:700;font-size:.75rem;
  padding:8px 14px;border-radius:6px;border:none;cursor:pointer;flex:1}
.btn-approve:hover{background:#059669}
.btn-deny{background:rgba(239,68,68,.12);color:#ef4444;font-weight:700;font-size:.75rem;
  padding:8px 14px;border-radius:6px;border:1px solid rgba(239,68,68,.25);
  cursor:pointer;flex:1}
.btn-deny:hover{background:rgba(239,68,68,.2)}
.inspect-link{color:var(--primary);text-decoration:underline;cursor:pointer;
  font-size:.75rem;margin-top:6px;display:inline-block}

/* Prompt input bar — PINNED TO BOTTOM via flex-shrink:0, NOT position:absolute */
.prompt-bar{flex-shrink:0;padding:12px 28px 16px 28px;background:var(--bg-app);
  border-top:1px solid var(--border)}
.prompt-box{background:var(--bg-surface);border:1px solid var(--border);
  border-radius:14px;padding:12px 16px;display:flex;flex-direction:column;gap:8px;
  box-shadow:var(--shadow-sm);transition:border-color .2s,box-shadow .2s}
.prompt-box:focus-within{border-color:var(--border-focus);
  box-shadow:0 0 16px rgba(56,189,248,.15)}
.prompt-textarea{background:transparent;border:none;outline:none;color:var(--text-main);
  font-family:var(--font-sans);font-size:.9rem;resize:none;min-height:44px;
  max-height:140px;line-height:1.5}
.prompt-textarea::placeholder{color:var(--text-dim)}
.prompt-footer{display:flex;justify-content:space-between;align-items:center}
.model-badge{font-size:.68rem;font-family:var(--font-mono);color:var(--text-dim);
  background:var(--bg-card);padding:2px 8px;border-radius:10px;
  border:1px solid var(--border)}
.run-btn{background:var(--primary);color:#082f49;font-weight:700;font-size:.75rem;
  padding:5px 14px;border-radius:6px;border:none;cursor:pointer}
.run-btn:hover{background:var(--primary-hover)}

/* === RIGHT VIEWER (width:0 → 50%, animated) === */
.right-viewer{width:0;background:var(--bg-surface);border-left:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden;flex-shrink:0;
  transition:width .3s cubic-bezier(.16,1,.3,1)}
.right-viewer.open{width:50%}
.viewer-header{display:flex;align-items:center;height:38px;background:var(--bg-sidebar);
  border-bottom:1px solid var(--border);flex-shrink:0;overflow-x:auto}
.viewer-tabs{display:flex;align-items:center;flex:1;overflow-x:auto;height:100%}
.tab{display:flex;align-items:center;gap:8px;padding:0 12px;height:100%;
  font-size:.78rem;color:var(--text-muted);border-right:1px solid var(--border);
  cursor:pointer;background:var(--bg-sidebar);user-select:none;white-space:nowrap}
.tab:hover{background:var(--bg-card-hover);color:var(--text-main)}
.tab.active{background:var(--bg-surface);color:var(--text-main);font-weight:600;
  border-bottom:2px solid var(--primary)}
.tab-x{font-size:.72rem;color:var(--text-dim);border-radius:4px;padding:2px 4px;
  cursor:pointer}
.tab-x:hover{background:rgba(239,68,68,.15);color:#ef4444}
.viewer-close{background:none;border:none;font-size:.9rem;color:var(--text-dim);
  cursor:pointer;padding:4px 10px;flex-shrink:0}
.viewer-close:hover{color:var(--text-main)}
.viewer-body{flex:1;position:relative;overflow:hidden}
#monaco-box{width:100%;height:100%;display:none}
#md-box{width:100%;height:100%;overflow-y:auto;padding:24px 32px;display:none}
#graph-box{width:100%;height:100%;display:none;background:#0c0e14}
.md-view h1,.md-view h2,.md-view h3{color:var(--text-main);margin:18px 0 10px 0}
.md-view p{color:var(--text-muted);line-height:1.7;margin-bottom:12px;font-size:.88rem}
.md-view table{width:100%;border-collapse:collapse;margin:14px 0;font-size:.8rem}
.md-view th,.md-view td{border:1px solid var(--border);padding:8px 12px;text-align:left}
.md-view pre{background:var(--code-bg);border:1px solid var(--border);border-radius:8px;
  padding:12px;overflow-x:auto;margin:12px 0}
.md-view code{font-family:var(--font-mono);color:var(--primary);font-size:.8rem}

/* === STATUS BAR (28px) === */
.status-bar{height:28px;background:var(--bg-sidebar);border-top:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 14px;
  font-size:.68rem;font-family:var(--font-mono);color:var(--text-dim);flex-shrink:0}
.status-left,.status-right{display:flex;align-items:center;gap:14px}

/* === SETTINGS MODAL === */
.modal-bg{position:fixed;top:0;left:0;width:100vw;height:100vh;
  background:rgba(0,0,0,.6);backdrop-filter:blur(4px);
  display:none;align-items:center;justify-content:center;z-index:500}
.modal-box{background:var(--bg-surface);border:1px solid var(--border);
  box-shadow:var(--shadow-lg);border-radius:14px;padding:24px;max-width:520px;width:90%}
.modal-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}
.modal-title{font-size:1.1rem;font-weight:700;color:var(--text-main)}
.modal-close{background:transparent;border:none;font-size:1.2rem;color:var(--text-dim);
  cursor:pointer}
.settings-group{margin-bottom:16px}
.settings-label{font-size:.8rem;font-weight:600;margin-bottom:6px;color:var(--text-main)}
.s-select,.s-input{width:100%;padding:8px 12px;background:var(--bg-input);
  border:1px solid var(--border);border-radius:8px;color:var(--text-main);
  font-size:.85rem;outline:none}
.toast{position:fixed;bottom:45px;right:24px;background:var(--bg-surface);
  border:1px solid var(--border);box-shadow:var(--shadow-lg);padding:10px 16px;
  border-radius:8px;font-size:.78rem;font-weight:600;display:none;z-index:600}
</style>
</head>
<body>

<!-- ===== TOP BAR ===== -->
<div class="top-bar">
  <div class="brand-group" onclick="goHome()">
    <img src="/api/logo" id="top-logo" class="brand-logo" alt="Logo">
    <span class="brand-name" id="top-name">ANTON</span>
    <span class="breadcrumb">workspace / devops / vault</span>
  </div>
  <div class="top-actions">
    <button class="son-toggle" id="son-btn" onclick="toggleSonMode()">
      <span class="son-dot"></span>
      <span id="son-label">SON OF ANTON [OFF]</span>
    </button>
    <button class="icon-btn" onclick="openSettings()">⚙ Settings</button>
    <div style="display:flex;align-items:center;gap:6px;font-size:.75rem;font-weight:700;color:var(--success);margin-left:4px">
      <span class="status-dot"></span>ONLINE
    </div>
  </div>
</div>

<!-- ===== WORKBENCH (3-panel flex row) ===== -->
<div class="workbench">

  <!-- LEFT SIDEBAR (260px → 48px) -->
  <div class="left-sidebar" id="left-sb">
    <div class="sidebar-top">
      <span class="sidebar-title">Knowledge & Code</span>
      <button class="sidebar-collapse-btn" id="sb-toggle" onclick="toggleSidebar()" title="⌘B">◀</button>
    </div>
    <div class="sidebar-body">
      <div class="tree-section">⚡ Python Verify Gates</div>
      <div class="tree-node" onclick="openInViewer('scripts/verify_balance.py')">
        <span>🐍 verify_balance.py</span><span class="tree-pill">0-LLM</span>
      </div>
      <div class="tree-node" onclick="openInViewer('anton/scheduler.py')">
        <span>🐍 scheduler.py</span><span class="tree-pill">ENGINE</span>
      </div>
      <div class="tree-section">🧠 100x Learned Skills</div>
      <div class="tree-node" onclick="openInViewer('skills/100x-desktop-ide-designer')">
        <span>✦ 100x-desktop-ide</span><span class="tree-pill">0.98</span>
      </div>
      <div class="tree-node" onclick="openInViewer('skills/100x-gtm-strategist')">
        <span>✦ 100x-gtm-strategist</span><span class="tree-pill">0.98</span>
      </div>
      <div class="tree-node" onclick="openInViewer('skills/100x-pr-publicity-specialist')">
        <span>✦ 100x-pr-publicity</span><span class="tree-pill">0.96</span>
      </div>
      <div class="tree-section">📑 Strategy Artifacts</div>
      <div class="tree-node" onclick="openInViewer('strategy/award-marketing-plan')">
        <span>📄 award-marketing-plan</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-node" onclick="openInViewer('strategy/content-calendar')">
        <span>📅 content-calendar</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-node" onclick="openInViewer('strategy/pr-outreach-list')">
        <span>📰 pr-outreach-list</span><span class="tree-pill">MD</span>
      </div>
      <div class="tree-section">🌌 Spatial Views</div>
      <div class="tree-node" onclick="openGraphViewer()">
        <span>🪐 3D Neural Second Brain</span><span class="tree-pill">GRAPH</span>
      </div>
    </div>
  </div>

  <!-- CENTER WORKSPACE -->
  <div class="center-ws">
    <!-- Scrollable message area -->
    <div class="msg-scroll" id="msg-scroll">
      <div class="msg-inner" id="msg-inner">

        <!-- Zero-state hero (visible when no messages) -->
        <div class="zero-state" id="zero-state">
          <img src="/api/logo" id="hero-logo" class="hero-logo" alt="Logo">
          <div class="hero-title" id="hero-title">What would you like Anton to do?</div>
          <div class="hero-sub" id="hero-sub">Autonomous Coworker with Deterministic Gates &amp; Second Brain Memory</div>
          <div class="hero-chips">
            <div class="chip" onclick="useChip('Reconcile Stripe payouts and QuickBooks ledger with $0.00 hard gate')">⚡ Reconcile Stripe & QBO</div>
            <div class="chip" onclick="useChip('Synthesize GTM launch plan and 2-week content calendar for SaaS award')">🏆 SaaS Award GTM Campaign</div>
            <div class="chip" onclick="useChip('Inspect 100x desktop IDE designer skill protocol')">🧠 100x Desktop IDE Skill</div>
          </div>
        </div>

        <!-- Messages stream (appended dynamically) -->
        <div id="msg-stream"></div>
      </div>
    </div>

    <!-- Prompt bar — PINNED TO BOTTOM (flex-shrink:0, NOT absolute) -->
    <div class="prompt-bar">
      <div class="prompt-box">
        <textarea id="prompt-input" class="prompt-textarea" rows="1"
          placeholder="Ask Anton anything, run a workflow, or search the Second Brain..."></textarea>
        <div class="prompt-footer">
          <span class="model-badge">Local [REDACTED-LOCAL-INFERENCE] → Cloud Fallback</span>
          <button class="run-btn" onclick="submitPrompt()">Run ↵</button>
        </div>
      </div>
    </div>
  </div>

  <!-- RIGHT VIEWER (width:0 → 50%) -->
  <div class="right-viewer" id="right-viewer">
    <div class="viewer-header">
      <div class="viewer-tabs" id="vtab-bar"></div>
      <button class="viewer-close" onclick="closeViewer()" title="Esc">✕</button>
    </div>
    <div class="viewer-body">
      <div id="monaco-box"></div>
      <div id="md-box" class="md-view"></div>
      <div id="graph-box"></div>
    </div>
  </div>
</div>

<!-- ===== STATUS BAR ===== -->
<div class="status-bar">
  <div class="status-left">
    <span>🌿 main</span>
    <span>⚡ Gates: Fail-Closed</span>
    <span id="mode-status">Mode: Safe Standard</span>
  </div>
  <div class="status-right">
    <span>Theme: <span id="theme-label">System</span></span>
    <span>Budget: $0.042 / $5.00</span>
    <span id="clock">UTC --:--:--</span>
  </div>
</div>

<!-- ===== SETTINGS MODAL ===== -->
<div class="modal-bg" id="settings-modal">
  <div class="modal-box">
    <div class="modal-hdr">
      <div class="modal-title">⚙ Anton Settings</div>
      <button class="modal-close" onclick="closeSettings()">✕</button>
    </div>
    <div class="settings-group">
      <div class="settings-label">Theme Appearance</div>
      <select id="theme-sel" class="s-select" onchange="setTheme(this.value)">
        <option value="system">🖥 System Default</option>
        <option value="light">☀ Light Mode</option>
        <option value="dark">🌙 Dark Mode</option>
      </select>
    </div>
    <div class="settings-group">
      <div class="settings-label">LLM Provider Keys</div>
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <select id="prov-sel" class="s-select" style="flex:1">
          <option value="openrouter">OpenRouter</option>
          <option value="anthropic">Anthropic</option>
          <option value="openai">OpenAI</option>
          <option value="ollama">Local Ollama</option>
        </select>
        <input type="password" id="prov-key" class="s-input" placeholder="API Key…" style="flex:1.5">
      </div>
      <button onclick="saveKey()" class="btn-approve" style="padding:7px;width:100%">Save Key</button>
    </div>
    <div style="display:flex;justify-content:flex-end;margin-top:20px">
      <button class="btn-approve" onclick="closeSettings()" style="flex:none;padding:8px 18px">Done</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- ===== SCRIPTS ===== -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/loader.min.js"></script>
<script>
const $=id=>document.getElementById(id);
let editor=null, sonMode=false, hasMessages=false;
let tabs=[], activeTab=null;

/* --- Utility --- */
function toast(msg,type){const t=$('toast');t.textContent=msg;t.style.display='block';
  t.style.borderColor=type==='success'?'#10b981':type==='error'?'#ef4444':'#f59e0b';
  setTimeout(()=>t.style.display='none',3000)}
function tick(){$('clock').textContent='UTC '+new Date().toISOString().slice(11,19)}
setInterval(tick,1000);tick();

/* --- Theme --- */
function initTheme(){setTheme(localStorage.getItem('anton_theme')||'system',false)}
function setTheme(t,save){
  document.documentElement.setAttribute('data-theme',t);
  $('theme-label').textContent=t[0].toUpperCase()+t.slice(1);
  if($('theme-sel'))$('theme-sel').value=t;
  if(save!==false)localStorage.setItem('anton_theme',t);
  if(editor){const dk=t==='dark'||(t==='system'&&matchMedia('(prefers-color-scheme:dark)').matches);
    monaco.editor.setTheme(dk?'vs-dark':'vs')}
}

/* --- Sidebar --- */
let sbOpen=true;
function toggleSidebar(){
  const sb=$('left-sb'),btn=$('sb-toggle');
  sbOpen=!sbOpen;
  sb.classList.toggle('collapsed',!sbOpen);
  btn.textContent=sbOpen?'◀':'▶';
}

/* --- Monaco --- */
require.config({paths:{'vs':'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs'}});
require(['vs/editor/editor.main'],function(){
  const dk=document.documentElement.getAttribute('data-theme')==='dark'||
    (document.documentElement.getAttribute('data-theme')==='system'&&matchMedia('(prefers-color-scheme:dark)').matches);
  editor=monaco.editor.create($('monaco-box'),{
    value:'',language:'python',theme:dk?'vs-dark':'vs',automaticLayout:true,
    fontSize:13,fontFamily:'JetBrains Mono,Menlo,monospace',
    minimap:{enabled:false},lineNumbers:'on',renderLineHighlight:'all',
    scrollBeyondLastLine:false
  });
});

/* --- Zero State --- */
function hideZeroState(){
  const z=$('zero-state');
  if(z)z.classList.add('hidden');
  hasMessages=true;
}

/* --- Right Viewer --- */
function showViewer(){$('right-viewer').classList.add('open')}
function closeViewer(){$('right-viewer').classList.remove('open')}

function renderTabs(){
  const bar=$('vtab-bar');
  if(!tabs.length){bar.innerHTML='';closeViewer();return}
  bar.innerHTML=tabs.map(t=>`<div class="tab ${t.id===activeTab?'active':''}"
    onclick="switchTab('${t.id}')"><span>${t.title}</span>
    <span class="tab-x" onclick="closeTab('${t.id}',event)">✕</span></div>`).join('');
  const at=tabs.find(t=>t.id===activeTab);
  if(at)showBuffer(at.type,at.content);
}

function showBuffer(type,content){
  $('monaco-box').style.display='none';
  $('md-box').style.display='none';
  $('graph-box').style.display='none';
  if(type==='code'){$('monaco-box').style.display='block';
    if(editor){editor.setValue(content||'');editor.layout()}}
  else if(type==='markdown'){$('md-box').style.display='block';
    $('md-box').innerHTML=marked.parse(content||'')}
  else if(type==='graph'){$('graph-box').style.display='block';loadGraph()}
}

async function openInViewer(path){
  showViewer();
  const bn=path.split('/').pop();
  if(tabs.find(t=>t.id===path)){activeTab=path;renderTabs();return}
  try{
    const r=await fetch('/api/vault/note?path='+encodeURIComponent(path));
    const d=await r.json();
    const isCode=d.is_code||path.endsWith('.py');
    tabs.push({id:path,title:bn,type:isCode?'code':'markdown',content:d.content||''});
    activeTab=path;renderTabs();
  }catch(e){toast('Failed to open: '+e.message,'error')}
}

function openGraphViewer(){
  showViewer();
  if(tabs.find(t=>t.id==='3d-graph')){activeTab='3d-graph';renderTabs();return}
  tabs.push({id:'3d-graph',title:'🪐 3D Brain',type:'graph',content:''});
  activeTab='3d-graph';renderTabs();
}

function switchTab(id){activeTab=id;renderTabs()}
function closeTab(id,ev){
  if(ev)ev.stopPropagation();
  const i=tabs.findIndex(t=>t.id===id);if(i<0)return;
  tabs.splice(i,1);
  if(activeTab===id){
    if(tabs.length)activeTab=tabs[Math.max(0,i-1)].id;
    else{activeTab=null;closeViewer()}
  }
  renderTabs();
}

let graphDone=false;
function loadGraph(){if(graphDone)return;graphDone=true;
  fetch('/api/vault/graph').then(r=>r.json()).then(d=>{
    ForceGraph3D()($('graph-box')).graphData(d).nodeLabel('title')
      .nodeColor(n=>n.type==='moc'?'#c084fc':n.type==='skill'?'#10b981':'#38bdf8')
      .nodeVal('val').linkWidth(1.2).onNodeClick(n=>openInViewer(n.id));
  });
}

/* --- Prompt & Chat --- */
function useChip(t){$('prompt-input').value=t;submitPrompt()}

async function submitPrompt(){
  const inp=$('prompt-input'),q=inp.value.trim();if(!q)return;
  hideZeroState();inp.value='';
  const stream=$('msg-stream');
  stream.innerHTML+=`<div class="msg-card user"><div class="msg-sender user-name">You</div><div>${q}</div></div>`;
  try{
    const r=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:q})});
    const d=await r.json();
    stream.innerHTML+=`<div class="msg-card agent"><div class="msg-sender agent-name">⚡ Anton</div>
      <div>${d.reply}</div>${d.note_path?`<a class="inspect-link" onclick="openInViewer('${d.note_path}')">Inspect ${d.note_path} →</a>`:''}</div>`;
    if(d.note_path)openInViewer(d.note_path);
    $('msg-scroll').scrollTop=$('msg-scroll').scrollHeight;
  }catch(e){toast('Error: '+e.message,'error')}
}

$('prompt-input').addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submitPrompt()}});

/* Auto-resize textarea */
$('prompt-input').addEventListener('input',function(){
  this.style.height='auto';this.style.height=Math.min(this.scrollHeight,140)+'px'});

function toggleToolCard(id){const el=$(id);el.style.display=el.style.display==='block'?'none':'block'}

/* --- Son of Anton Mode --- */
function updateSonUI(){
  const btn=$('son-btn'),lbl=$('son-label'),st=$('mode-status');
  const tl=$('top-logo'),hl=$('hero-logo'),tn=$('top-name');
  const ht=$('hero-title'),hs=$('hero-sub');
  if(sonMode){
    btn.classList.add('active');lbl.textContent='SON OF ANTON [ACTIVE]';
    st.textContent='Mode: Son of Anton (Overdrive)';st.style.color='#fbbf24';
    if(tl)tl.src='/api/logo/son-of-anton';if(hl)hl.src='/api/logo/son-of-anton';
    if(tn)tn.textContent='SON OF ANTON';
    if(ht)ht.textContent='What should Son of Anton execute?';
    if(hs)hs.textContent='Autonomous Overdrive · Zero Human Gate Delays';
  }else{
    btn.classList.remove('active');lbl.textContent='SON OF ANTON [OFF]';
    st.textContent='Mode: Safe Standard';st.style.color='var(--text-dim)';
    if(tl)tl.src='/api/logo';if(hl)hl.src='/api/logo';
    if(tn)tn.textContent='ANTON';
    if(ht)ht.textContent='What would you like Anton to do?';
    if(hs)hs.textContent='Autonomous Coworker with Deterministic Gates & Second Brain Memory';
  }
}
async function checkMode(){try{const r=await fetch('/api/mode');const d=await r.json();
  sonMode=!!d.son_of_anton_mode;updateSonUI()}catch(e){}}
async function toggleSonMode(){
  const next=!sonMode;
  try{const r=await fetch('/api/mode/son-of-anton',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({son_of_anton_mode:next})});
    if(r.ok){sonMode=next;updateSonUI();toast(sonMode?'Son of Anton ENGAGED':'Safe Mode Restored',sonMode?'warning':'success')}
  }catch(e){toast('Toggle failed','error')}
}

/* --- Approvals --- */
async function resolveApproval(aid,dec){
  try{const r=await fetch('/api/approvals/'+aid+'/resolve',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:dec})});
    if(r.ok){toast('Gate #'+aid+' '+dec.toUpperCase(),'success');
      const b=$('decision-box');if(b)b.innerHTML='<div style="padding:10px;background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.3);border-radius:8px;font-size:.75rem;color:#34d399;text-align:center">✓ Resolved ('+dec.toUpperCase()+')</div>'}
  }catch(e){toast(e.message,'error')}
}

/* --- Home Reset --- */
function goHome(){
  $('zero-state').classList.remove('hidden');
  $('msg-stream').innerHTML='';hasMessages=false;closeViewer();
  $('prompt-input').focus();
}

/* --- Settings --- */
function openSettings(){$('settings-modal').style.display='flex'}
function closeSettings(){$('settings-modal').style.display='none'}
async function saveKey(){
  const p=$('prov-sel').value,k=$('prov-key').value;
  if(!k)return toast('Enter a key','error');
  const r=await fetch('/api/wizard/providers',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({provider:p,key:k})});
  if(r.ok){toast('Saved '+p+' key','success');$('prov-key').value=''}
}

/* --- Keyboard Shortcuts --- */
addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='b'){e.preventDefault();toggleSidebar()}
  else if((e.metaKey||e.ctrlKey)&&e.key==='k'){e.preventDefault();$('prompt-input').focus()}
  else if(e.key==='Escape'){closeViewer();closeSettings()}
});

/* --- Seed initial demo content (approval gate + tool cards) --- */
function seedDemo(){
  const s=$('msg-stream');
  s.innerHTML=`
  <div class="decision-card" id="decision-box">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <span style="font-size:.65rem;font-weight:800;color:#fbbf24;text-transform:uppercase">Approval Gate #108</span>
      <span style="font-size:.65rem;font-family:var(--font-mono);color:var(--text-dim)">7a3f89…</span>
    </div>
    <div style="font-size:.85rem;font-weight:700;margin-bottom:4px">Action: Payout Reconcile ($14.50)</div>
    <div style="font-size:.75rem;color:var(--text-muted);margin-bottom:10px">Discrepancy caught by verify_balance.py. Halting at human boundary.</div>
    <div style="display:flex;gap:8px">
      <button class="btn-approve" onclick="resolveApproval(108,'approve')">✓ Approve (↵)</button>
      <button class="btn-deny" onclick="resolveApproval(108,'deny')">✗ Deny (⎋)</button>
    </div>
  </div>
  <div class="tool-card">
    <div class="tool-card-hdr" onclick="toggleToolCard('tc1')">
      <span>⚡ tool: python3 scripts/verify_balance.py</span>
      <span class="tool-badge" style="background:rgba(16,185,129,.15);color:var(--success)">exit 0 · 0.005s ▾</span>
    </div>
    <div class="tool-card-body" id="tc1">Input: {"stripe_total":1450.00,"qbo_total":1450.00}<br>
      Output: VERIFY PASSED. 0 tokens consumed.<br>
      <a class="inspect-link" onclick="openInViewer('scripts/verify_balance.py')">Inspect script →</a></div>
  </div>
  <div class="tool-card">
    <div class="tool-card-hdr" onclick="toggleToolCard('tc2')">
      <span>🧠 ambition: 2026 SaaS Award GTM</span>
      <span class="tool-badge" style="background:rgba(192,132,252,.15);color:var(--purple)">EV=0.95 · 100x-GTM ▾</span>
    </div>
    <div class="tool-card-body" id="tc2">Self-learned 100x-gtm-strategist in sandbox.<br>
      Synthesized: award-marketing-plan.md, content-calendar.md, pr-outreach-list.md.<br>
      <a class="inspect-link" onclick="openInViewer('strategy/award-marketing-plan')">Open GTM artifacts →</a></div>
  </div>`;
}

/* --- Init --- */
initTheme();checkMode();seedDemo();
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
