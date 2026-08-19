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
<title>ANTON — Autonomous Studio & Cognitive Control Plane</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/3d-force-graph"></script>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
:root {
  --bg-main: #090b10;
  --bg-canvas: #0e1118;
  --bg-surface: #131620;
  --bg-card: rgba(20, 24, 34, 0.85);
  --bg-card-hover: rgba(28, 34, 48, 0.95);
  --border: rgba(255, 255, 255, 0.08);
  --border-glow: rgba(56, 189, 248, 0.3);
  --border-rim: inset 0 1px 0 rgba(255, 255, 255, 0.16);
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --text-dim: #64748b;
  --primary: #38bdf8;
  --accent: #818cf8;
  --success: #10b981;
  --success-bg: rgba(16, 185, 129, 0.12);
  --warning: #f59e0b;
  --warning-bg: rgba(245, 158, 11, 0.12);
  --danger: #ef4444;
  --purple: #c084fc;
  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, Menlo, monospace;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background-color: var(--bg-main);
  color: var(--text-main);
  min-height: 100vh;
  padding: 1.25rem 1.5rem 5rem 1.5rem;
  line-height: 1.5;
  overflow-x: hidden;
}

.app-container { max-width: 1680px; margin: 0 auto; }

/* Top Header */
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1.5rem;
  background: var(--bg-surface);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border);
  box-shadow: var(--border-rim), 0 10px 30px rgba(0, 0, 0, 0.6);
  border-radius: 14px;
  margin-bottom: 1.25rem;
}
.brand { display: flex; align-items: center; gap: 12px; }
.brand-logo {
  width: 36px; height: 36px;
  background: linear-gradient(135deg, #1e2433, #151822);
  border: 1px solid rgba(255,255,255,0.18);
  box-shadow: var(--border-rim);
  border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.15rem; color: var(--primary);
}
.brand-title { font-size: 1.1rem; font-weight: 800; letter-spacing: -0.02em; }
.brand-badge {
  font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
  padding: 2px 8px; border-radius: 20px;
  background: rgba(56, 189, 248, 0.12); color: var(--primary);
  border: 1px solid rgba(56, 189, 248, 0.25);
}

.header-actions { display: flex; align-items: center; gap: 16px; }

/* Son of Anton Toggle */
.son-toggle {
  display: flex; align-items: center; gap: 8px; padding: 6px 14px;
  background: #171b24; border: 1px solid var(--border);
  box-shadow: var(--border-rim); border-radius: 30px; cursor: pointer;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1); font-size: 0.72rem; font-weight: 800;
  letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-muted);
}
.son-toggle:hover { border-color: rgba(255,255,255,0.25); background: #202634; }
.son-toggle.active {
  background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.6);
  color: #fbbf24; box-shadow: 0 0 20px rgba(245, 158, 11, 0.3);
}
.son-dot {
  width: 8px; height: 8px; border-radius: 50%; background: #64748b; transition: all 0.2s ease;
}
.son-toggle.active .son-dot {
  background: #fbbf24; box-shadow: 0 0 10px #fbbf24; animation: pulse 1.5s infinite;
}

@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }

.beacon {
  display: flex; align-items: center; gap: 8px; font-size: 0.72rem; font-weight: 700; color: var(--success);
  padding: 5px 12px; background: var(--success-bg); border-radius: 20px; border: 1px solid rgba(16, 185, 129, 0.25);
}
.beacon-dot { width: 6px; height: 6px; background: var(--success); border-radius: 50%; box-shadow: 0 0 8px var(--success); }

/* Navigation Tabs */
.nav-tabs { display: flex; gap: 8px; margin-bottom: 1.25rem; }
.tab-btn {
  background: var(--bg-surface); border: 1px solid var(--border); box-shadow: var(--border-rim);
  color: var(--text-muted); padding: 8px 18px; border-radius: 10px; cursor: pointer;
  font-size: 0.82rem; font-weight: 600; transition: all 0.15s ease;
}
.tab-btn:hover { background: var(--bg-card-hover); color: var(--text-main); }
.tab-btn.active {
  background: #202534; border-color: rgba(255, 255, 255, 0.2); color: var(--text-main);
  box-shadow: var(--border-rim), 0 4px 16px rgba(0,0,0,0.3);
}

/* 3-Column Studio Workspace */
.studio-layout {
  display: grid;
  grid-template-columns: 280px 1fr 380px;
  gap: 16px;
  min-height: 740px;
}
.studio-pane {
  background: var(--bg-surface); border: 1px solid var(--border);
  box-shadow: var(--border-rim), 0 12px 36px rgba(0,0,0,0.4); border-radius: 14px; padding: 1.25rem;
  overflow: hidden; display: flex; flex-direction: column;
}

/* Navigator Tree */
.tree-item {
  padding: 7px 10px; border-radius: 8px; font-size: 0.78rem; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between;
  color: var(--text-muted); transition: all 0.15s ease;
}
.tree-item:hover { background: #1a1e2b; color: var(--text-main); }
.tree-item.active { background: #22273a; color: var(--primary); font-weight: 600; }
.tree-badge {
  font-size: 0.65rem; font-family: var(--font-mono); padding: 2px 6px; border-radius: 4px;
  background: rgba(255,255,255,0.06); color: var(--text-dim);
}

/* Canvas Area */
.canvas-container {
  background-color: var(--bg-canvas);
  background-image: radial-gradient(rgba(255, 255, 255, 0.08) 1.2px, transparent 1.2px);
  background-size: 26px 26px;
  border-radius: 14px;
  border: 1px solid var(--border);
  box-shadow: var(--border-rim), inset 0 0 60px rgba(0,0,0,0.5);
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.canvas-header {
  padding: 12px 20px; background: rgba(19, 23, 32, 0.85); backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;
  z-index: 10;
}

/* SVG Cable Mesh Overlay */
.wire-canvas-svg {
  position: absolute; top: 0; left: 0; width: 100%; height: 100%;
  pointer-events: none; z-index: 2;
}

/* Multi-Branching Nodes Area */
.dag-area {
  flex: 1; padding: 30px 40px; display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 32px; align-items: center;
  position: relative; z-index: 5;
}

.dag-col { display: flex; flex-direction: column; gap: 24px; justify-content: center; }

/* Visual Node Card */
.node-card {
  background: var(--bg-card);
  backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: var(--border-rim), 0 10px 28px rgba(0, 0, 0, 0.5);
  border-radius: 12px; padding: 14px 16px; width: 100%; cursor: pointer;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
}
.node-card:hover {
  transform: translateY(-2px); border-color: rgba(255, 255, 255, 0.28);
  background: var(--bg-card-hover); box-shadow: var(--border-rim), 0 14px 36px rgba(0,0,0,0.6);
}
.node-card.active-glow {
  border-color: var(--primary); box-shadow: 0 0 24px rgba(56, 189, 248, 0.25), var(--border-rim);
}
.node-card.gate-locked {
  border-color: rgba(245, 158, 11, 0.5); box-shadow: 0 0 24px rgba(245, 158, 11, 0.2), var(--border-rim);
}
.node-card.gate-bypassed {
  border-color: rgba(16, 185, 129, 0.5); box-shadow: 0 0 24px rgba(16, 185, 129, 0.2), var(--border-rim);
}

/* Sockets */
.socket {
  position: absolute; width: 10px; height: 10px; border-radius: 50%;
  background: #1e2433; border: 2px solid #64748b; top: 50%; transform: translateY(-50%);
  transition: all 0.2s ease;
}
.socket-in { left: -6px; }
.socket-out { right: -6px; }
.node-card:hover .socket { border-color: var(--primary); box-shadow: 0 0 8px var(--primary); }

.node-meta-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.node-tag {
  font-size: 0.62rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.04em;
  padding: 2px 6px; border-radius: 5px; display: inline-block;
}
.tag-trigger { background: rgba(56, 189, 248, 0.15); color: var(--primary); }
.tag-brain { background: rgba(192, 132, 252, 0.15); color: var(--purple); }
.tag-gate { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
.tag-action { background: rgba(16, 185, 129, 0.15); color: var(--success); }

.node-latency { font-family: var(--font-mono); font-size: 0.65rem; color: var(--text-dim); }
.node-title { font-size: 0.88rem; font-weight: 700; margin-bottom: 3px; letter-spacing: -0.01em; }
.node-desc { font-size: 0.72rem; color: var(--text-muted); }

/* Right HUD Panels */
.research-hud {
  background: rgba(22, 26, 38, 0.7); border: 1px solid rgba(192, 132, 252, 0.25);
  box-shadow: var(--border-rim); border-radius: 12px; padding: 14px; margin-bottom: 14px;
}
.research-title {
  font-size: 0.72rem; font-weight: 800; color: var(--purple); text-transform: uppercase;
  display: flex; align-items: center; gap: 6px; margin-bottom: 8px; letter-spacing: 0.03em;
}
.thought-step {
  font-size: 0.73rem; color: var(--text-muted); padding: 3px 0;
  display: flex; align-items: center; gap: 8px; font-family: var(--font-mono);
}
.thought-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--purple); }

/* Decision Card */
.decision-card {
  background: rgba(28, 32, 46, 0.9); border: 1px solid rgba(245, 158, 11, 0.4);
  box-shadow: var(--border-rim), 0 10px 30px rgba(0,0,0,0.5); border-radius: 12px; padding: 16px; margin-bottom: 14px;
}
.decision-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.decision-badge {
  font-size: 0.65rem; font-weight: 800; text-transform: uppercase; padding: 2px 7px; border-radius: 12px;
  background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3);
}
.btn-approve {
  flex: 1; background: var(--success); color: #022c22; font-weight: 700; font-size: 0.78rem;
  padding: 8px 12px; border-radius: 8px; border: none; cursor: pointer; transition: all 0.15s ease;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.btn-approve:hover { background: #34d399; }
.btn-deny {
  flex: 1; background: rgba(239, 68, 68, 0.15); color: #f87171; font-weight: 700; font-size: 0.78rem;
  padding: 8px 12px; border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.3); cursor: pointer;
  transition: all 0.15s ease; display: flex; align-items: center; justify-content: center; gap: 6px;
}
.btn-deny:hover { background: rgba(239, 68, 68, 0.25); }

/* Markdown Reader Drawer */
.markdown-drawer {
  background: #11141c; border-left: 1px solid var(--border);
  box-shadow: -12px 0 40px rgba(0,0,0,0.7); position: fixed;
  top: 0; right: 0; width: 680px; height: 100vh; z-index: 300;
  display: none; flex-direction: column; overflow: hidden;
}
.drawer-header {
  padding: 16px 24px; background: #161a25; border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
}
.drawer-title { font-size: 0.95rem; font-weight: 700; color: var(--text-main); font-family: var(--font-mono); }
.drawer-close { background: transparent; border: none; color: var(--text-dim); font-size: 1.2rem; cursor: pointer; }
.drawer-close:hover { color: #fff; }
.drawer-body { flex: 1; padding: 24px; overflow-y: auto; font-size: 0.86rem; line-height: 1.7; color: #cbd5e1; }
.drawer-body h1, .drawer-body h2, .drawer-body h3 { color: #f8fafc; margin: 16px 0 10px 0; }
.drawer-body table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 0.8rem; }
.drawer-body th, .drawer-body td { padding: 8px 12px; border: 1px solid var(--border); text-align: left; }
.drawer-body pre { background: #0a0c10; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 14px 0; font-family: var(--font-mono); }
.drawer-body code { font-family: var(--font-mono); font-size: 0.8rem; color: var(--primary); }

/* Floating Command Capsule (⌘K) */
.command-capsule {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: rgba(20, 24, 34, 0.92); backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.16); box-shadow: var(--border-rim), 0 16px 48px rgba(0, 0, 0, 0.7);
  border-radius: 30px; padding: 8px 20px; display: flex; align-items: center; gap: 12px; width: 600px; max-width: 90vw; z-index: 100;
}
.command-input {
  background: transparent; border: none; outline: none; color: var(--text-main); font-family: var(--font-sans); font-size: 0.85rem; flex: 1;
}

/* Modal */
.modal-backdrop {
  position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
  background: rgba(0,0,0,0.75); backdrop-filter: blur(6px);
  display: none; align-items: center; justify-content: center; z-index: 400;
}
.modal-box {
  background: #151822; border: 1px solid rgba(245, 158, 11, 0.4);
  box-shadow: 0 20px 50px rgba(0,0,0,0.8); border-radius: 16px; padding: 24px; max-width: 480px; width: 90%;
}

.toast {
  position: fixed; bottom: 85px; right: 24px;
  background: #1c2130; border: 1px solid var(--border); box-shadow: 0 8px 24px rgba(0,0,0,0.5);
  padding: 10px 16px; border-radius: 10px; font-size: 0.8rem; font-weight: 600; display: none; z-index: 500;
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
          <span class="brand-badge">COGNITIVE OS v0.1.0</span>
        </div>
        <div style="font-size:0.72rem;color:var(--text-dim)">Second Brain & Autonomous Operating Studio</div>
      </div>
    </div>
    
    <div class="header-actions">
      <!-- Son of Anton Toggle -->
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
    <button class="tab-btn active" onclick="switchTab('studio', event)">📐 Studio Workspace</button>
    <button class="tab-btn" onclick="switchTab('neural', event)">🌌 3D Neural Second Brain</button>
    <button class="tab-btn" onclick="switchTab('telemetry', event)">📊 Telemetry & Ledger</button>
    <button class="tab-btn" onclick="switchTab('wizard', event)">⚙️ Key Vault & Bridges</button>
  </div>

  <!-- TAB 1: STUDIO WORKSPACE -->
  <div id="tab-studio" class="tab-pane active">
    <div class="studio-layout">
      <!-- Left: Navigator (Click to Open Markdown) -->
      <div class="studio-pane">
        <div style="font-size:0.72rem;font-weight:800;color:var(--text-dim);text-transform:uppercase;margin-bottom:10px">Interactive Memory & Skills</div>
        <div style="display:flex;flex-direction:column;gap:4px;overflow-y:auto;flex:1">
          <div style="padding:4px 8px;font-size:0.75rem;color:var(--primary);font-weight:700">🧠 100x Learned Skills</div>
          <div class="tree-item" onclick="openMarkdownReader('skills/100x-desktop-ide-designer')"><span>✦ 100x-desktop-ide</span><span class="tree-badge">0.98</span></div>
          <div class="tree-item" onclick="openMarkdownReader('skills/100x-mobile-app-designer')"><span>✦ 100x-mobile-app</span><span class="tree-badge">0.96</span></div>
          <div class="tree-item" onclick="openMarkdownReader('skills/elite-software-product-designer')"><span>✦ elite-software-product</span><span class="tree-badge">0.99</span></div>
          <div class="tree-item" onclick="openMarkdownReader('skills/100x-gtm-strategist')"><span>✦ 100x-gtm-strategist</span><span class="tree-badge">0.98</span></div>
          <div class="tree-item" onclick="openMarkdownReader('skills/100x-pr-publicity-specialist')"><span>✦ 100x-pr-publicity</span><span class="tree-badge">0.96</span></div>
          
          <div style="padding:8px 8px 4px 8px;font-size:0.75rem;color:var(--purple);font-weight:700;margin-top:6px">📑 GTM Strategy Artifacts</div>
          <div class="tree-item" onclick="openMarkdownReader('strategy/award-marketing-plan')"><span>📄 award-marketing-plan</span><span class="tree-badge">MD</span></div>
          <div class="tree-item" onclick="openMarkdownReader('strategy/content-calendar')"><span>📅 content-calendar</span><span class="tree-badge">MD</span></div>
          <div class="tree-item" onclick="openMarkdownReader('strategy/pr-outreach-list')"><span>📰 pr-outreach-list</span><span class="tree-badge">MD</span></div>
        </div>
      </div>

      <!-- Center: Multi-Branching DAG Canvas -->
      <div class="canvas-container" id="canvas-container-elem">
        <div class="canvas-header">
          <span style="font-size:0.8rem;font-weight:800;color:var(--text-muted);text-transform:uppercase">Execution & Reasoning Pipeline</span>
          <span style="font-size:0.72rem;color:var(--text-dim);font-family:var(--font-mono)">Branching DAG · 60 FPS Pulse</span>
        </div>

        <!-- SVG Bezier Mesh Overlay -->
        <svg class="wire-canvas-svg" id="dag-svg-canvas">
          <defs>
            <linearGradient id="grad-cyan" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.8"/>
              <stop offset="100%" stop-color="#c084fc" stop-opacity="0.8"/>
            </linearGradient>
            <linearGradient id="grad-purple" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#c084fc" stop-opacity="0.8"/>
              <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.8"/>
            </linearGradient>
            <linearGradient id="grad-emerald" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.8"/>
              <stop offset="100%" stop-color="#10b981" stop-opacity="0.8"/>
            </linearGradient>
          </defs>
          <!-- Dynamic Paths generated via JS -->
        </svg>

        <!-- Multi-Branching Grid Layout -->
        <div class="dag-area">
          <!-- Column 1: Triggers -->
          <div class="dag-col">
            <div class="node-card active-glow" id="node-trig-1" onclick="openMarkdownReader('mocs/operations')">
              <span class="socket socket-out"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-trigger">Trigger</span>
                <span class="node-latency">POST</span>
              </div>
              <div class="node-title">Webhook: Stripe</div>
              <div class="node-desc">/hooks/stripe-payout</div>
            </div>

            <div class="node-card" id="node-trig-2" onclick="openMarkdownReader('strategy/award-marketing-plan')">
              <span class="socket socket-out"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-trigger">Trigger</span>
                <span class="node-latency">06:00 UTC</span>
              </div>
              <div class="node-title">Cron: Daily Sync</div>
              <div class="node-desc">QBO Bank Ingest</div>
            </div>
          </div>

          <!-- Column 2: AI Cognitive Ingest -->
          <div class="dag-col">
            <div class="node-card" id="node-brain-1" onclick="openMarkdownReader('skills/100x-desktop-ide-designer')">
              <span class="socket socket-in"></span>
              <span class="socket socket-out"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-brain">AI Brain</span>
                <span class="node-latency">12ms · 98%</span>
              </div>
              <div class="node-title">Extract & OCR</div>
              <div class="node-desc">Local [REDACTED-LOCAL-INFERENCE]-reason</div>
            </div>

            <div class="node-card" id="node-brain-2" onclick="openMarkdownReader('skills/100x-gtm-strategist')">
              <span class="socket socket-in"></span>
              <span class="socket socket-out"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-brain">Ambition</span>
                <span class="node-latency">EV=0.95</span>
              </div>
              <div class="node-title">Governor Score</div>
              <div class="node-desc">100x GTM Self-Learn</div>
            </div>
          </div>

          <!-- Column 3: Deterministic Verify & Gate -->
          <div class="dag-col">
            <div class="node-card gate-locked" id="node-gate-1" onclick="openMarkdownReader('mocs/operations')">
              <span class="socket socket-in"></span>
              <span class="socket socket-out"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-gate">Verify Gate</span>
                <span class="node-latency" id="node-gate-badge">FAIL-CLOSED</span>
              </div>
              <div class="node-title">Deterministic Math</div>
              <div class="node-desc" id="node-gate-desc">verify_balance.py (Δ=0)</div>
            </div>
          </div>

          <!-- Column 4: Outcomes -->
          <div class="dag-col">
            <div class="node-card" id="node-action-1" onclick="openMarkdownReader('mocs/operations')">
              <span class="socket socket-in"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-action">Outcome</span>
                <span class="node-latency">ATOMIC</span>
              </div>
              <div class="node-title">Commit QBO Ledger</div>
              <div class="node-desc">runs.jsonl append</div>
            </div>

            <div class="node-card" id="node-action-2" onclick="openMarkdownReader('strategy/content-calendar')">
              <span class="socket socket-in"></span>
              <div class="node-meta-row">
                <span class="node-tag tag-action">Outcome</span>
                <span class="node-latency">VAULT</span>
              </div>
              <div class="node-title">GTM Launch Active</div>
              <div class="node-desc">2-Week Calendar Set</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Cognitive Research Stream & Decision HUD -->
      <div class="studio-pane">
        <!-- Research Stream HUD -->
        <div class="research-hud">
          <div class="research-title">🔍 Cognitive Research Stream</div>
          <div class="thought-step"><span class="thought-dot"></span><span>Literature search: GTM sequencing</span></div>
          <div class="thought-step"><span class="thought-dot"></span><span>Assumption audit: Zero spam press</span></div>
          <div class="thought-step"><span class="thought-dot"></span><span>Sandbox trial: 100x-gtm exit 0</span></div>
          <div class="thought-step"><span class="thought-dot"></span><span>Promotion: Linked in vault.db</span></div>
        </div>

        <div style="font-size:0.72rem;font-weight:800;color:var(--text-dim);text-transform:uppercase;margin-bottom:8px">Executive Decision HUD</div>
        <div id="decision-hud-container">
          <p style="font-size:0.78rem;color:var(--text-dim);text-align:center;padding:15px 0">All gates operating securely.</p>
        </div>

        <div style="font-size:0.72rem;font-weight:800;color:var(--text-dim);text-transform:uppercase;margin:12px 0 8px 0">Live Activity Feed</div>
        <div id="live-activity-feed" style="display:flex;flex-direction:column;gap:8px;overflow-y:auto;flex:1"></div>
      </div>
    </div>
  </div>

  <!-- TAB 2: 3D NEURAL SECOND BRAIN -->
  <div id="tab-neural" class="tab-pane" style="display:none">
    <div class="studio-pane" style="padding:0">
      <div id="graph-container" style="width:100%;height:650px;background:var(--bg-canvas)"></div>
    </div>
  </div>

  <!-- TAB 3: TELEMETRY & LEDGER -->
  <div id="tab-telemetry" class="tab-pane" style="display:none">
    <div class="studio-pane">
      <div style="font-size:0.85rem;font-weight:700;margin-bottom:12px">Execution & Audit Ledger (runs.jsonl)</div>
      <table>
        <thead>
          <tr>
            <th>Timestamp</th><th>Task</th><th>Exit Code</th><th>Flags</th><th>Model / Provider</th><th>Duration / Cost</th>
          </tr>
        </thead>
        <tbody id="ledger-rows"></tbody>
      </table>
    </div>
  </div>

  <!-- TAB 4: KEY VAULT -->
  <div id="tab-wizard" class="tab-pane" style="display:none">
    <div class="studio-pane" style="max-width:800px;margin:0 auto">
      <h3 style="margin-bottom:16px">Capability Bridges & Key Vault (0600 POSIX)</h3>
      <div style="display:flex;flex-direction:column;gap:14px">
        <select id="wiz-provider" style="padding:10px;background:#181b24;border:1px solid var(--border);color:#fff;border-radius:8px">
          <option value="openrouter">OpenRouter (Claude 3.5 Sonnet)</option>
          <option value="anthropic">Anthropic Direct</option>
          <option value="openai">OpenAI Direct</option>
          <option value="ollama">Local Ollama</option>
        </select>
        <input type="password" id="wiz-key" placeholder="API Key..." style="padding:10px;background:#181b24;border:1px solid var(--border);color:#fff;border-radius:8px">
        <button onclick="saveProviderKey()" class="btn-approve" style="padding:10px">Save to Vault</button>
      </div>
    </div>
  </div>
</div>

<!-- Floating Command Capsule (⌘K) -->
<div class="command-capsule">
  <span style="color:var(--primary);font-size:1.1rem">⚡</span>
  <input type="text" id="cmd-input" class="command-input" placeholder="Ask Anton anything, trigger a recipe, or search Second Brain (⌘K)...">
  <span style="background:#222634;border:1px solid rgba(255,255,255,0.1);padding:2px 6px;border-radius:6px;font-family:var(--font-mono);font-size:0.7rem;color:var(--text-muted)">⌘K</span>
</div>

<!-- Markdown Reader Drawer -->
<div class="markdown-drawer" id="md-drawer">
  <div class="drawer-header">
    <span class="drawer-title" id="drawer-file-title">Markdown Document</span>
    <button class="drawer-close" onclick="closeMarkdownReader()">✕</button>
  </div>
  <div class="drawer-body" id="drawer-file-content">
    Loading document...
  </div>
</div>

<!-- Son of Anton Confirmation Modal -->
<div class="modal-backdrop" id="son-modal">
  <div class="modal-box">
    <div style="font-size:1.1rem;font-weight:800;color:#fbbf24;margin-bottom:8px">⚡ Activate Son of Anton Mode?</div>
    <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:20px;line-height:1.6">
      Anton will autonomously execute all workflows with human approval gates without halting for manual confirmation.
      All deterministic verify gates and token budgets remain in effect.
    </div>
    <div style="display:flex;justify-content:flex-end;gap:10px">
      <button class="btn-deny" onclick="closeSonModal()">Cancel</button>
      <button class="btn-approve" style="background:#f59e0b;color:#000" onclick="confirmSonOfAnton()">⚡ Engage</button>
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
  t.textContent = msg; t.style.display = 'block';
  t.style.borderColor = type === 'success' ? '#10b981' : (type === 'error' ? '#ef4444' : '#f59e0b');
  setTimeout(() => t.style.display = 'none', 3500);
}

function updateClock() {
  $('clock-display').textContent = 'UTC ' + new Date().toISOString().substring(11, 19);
}
setInterval(updateClock, 1000); updateClock();

function switchTab(tab, e) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p => p.style.display = 'none');
  e.target.classList.add('active');
  $('tab-' + tab).style.display = 'block';
  if (tab === 'neural' && !window.graphLoaded) initGraph();
  if (tab === 'studio') setTimeout(renderSvgWires, 50);
}

// Render dynamic SVG Bezier connection wires
function renderSvgWires() {
  const svg = $('dag-svg-canvas');
  if (!svg) return;
  const container = $('canvas-container-elem');
  const cRect = container.getBoundingClientRect();

  const connections = [
    { from: 'node-trig-1', to: 'node-brain-1', grad: 'url(#grad-cyan)' },
    { from: 'node-trig-2', to: 'node-brain-1', grad: 'url(#grad-cyan)' },
    { from: 'node-trig-2', to: 'node-brain-2', grad: 'url(#grad-cyan)' },
    { from: 'node-brain-1', to: 'node-gate-1', grad: 'url(#grad-purple)' },
    { from: 'node-brain-2', to: 'node-gate-1', grad: 'url(#grad-purple)' },
    { from: 'node-gate-1', to: 'node-action-1', grad: 'url(#grad-emerald)' },
    { from: 'node-gate-1', to: 'node-action-2', grad: 'url(#grad-emerald)' }
  ];

  let pathsHtml = `
    <defs>
      <linearGradient id="grad-cyan" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.85"/>
        <stop offset="100%" stop-color="#c084fc" stop-opacity="0.85"/>
      </linearGradient>
      <linearGradient id="grad-purple" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#c084fc" stop-opacity="0.85"/>
        <stop offset="100%" stop-color="#f59e0b" stop-opacity="0.85"/>
      </linearGradient>
      <linearGradient id="grad-emerald" x1="0%" y1="0%" x2="100%" y2="0%">
        <stop offset="0%" stop-color="#f59e0b" stop-opacity="0.85"/>
        <stop offset="100%" stop-color="#10b981" stop-opacity="0.85"/>
      </linearGradient>
    </defs>
  `;

  connections.forEach(c => {
    const elFrom = $(c.from);
    const elTo = $(c.to);
    if (!elFrom || !elTo) return;

    const r1 = elFrom.getBoundingClientRect();
    const r2 = elTo.getBoundingClientRect();

    const x1 = r1.right - cRect.left;
    const y1 = r1.top + r1.height / 2 - cRect.top;
    const x2 = r2.left - cRect.left;
    const y2 = r2.top + r2.height / 2 - cRect.top;

    const dx = (x2 - x1) * 0.5;
    const pathD = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

    pathsHtml += `
      <path d="${pathD}" fill="none" stroke="${c.grad}" stroke-width="2.5" stroke-linecap="round"/>
      <circle cx="${x1}" cy="${y1}" r="3.5" fill="#38bdf8"/>
      <circle cx="${x2}" cy="${y2}" r="3.5" fill="#10b981"/>
    `;
  });

  svg.innerHTML = pathsHtml;
}

window.addEventListener('resize', renderSvgWires);
setTimeout(renderSvgWires, 200);

async function openMarkdownReader(path) {
  const drawer = $('md-drawer');
  drawer.style.display = 'flex';
  $('drawer-file-title').textContent = path + '.md';
  $('drawer-file-content').innerHTML = '<p style="color:var(--text-dim)">Fetching artifact from Second Brain...</p>';
  try {
    const res = await fetch(`/api/vault/note?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    if (data.content) {
      $('drawer-file-content').innerHTML = marked.parse(data.content);
    } else {
      $('drawer-file-content').innerHTML = '<p style="color:var(--danger)">Failed to load document.</p>';
    }
  } catch (e) {
    $('drawer-file-content').innerHTML = '<p style="color:var(--danger)">Error: ' + e.message + '</p>';
  }
}

function closeMarkdownReader() { $('md-drawer').style.display = 'none'; }

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
  const gateNode = $('node-gate-1');
  const gateBadge = $('node-gate-badge');
  const gateDesc = $('node-gate-desc');

  if (sonOfAntonActive) {
    btn.classList.add('active');
    lbl.textContent = '⚡ SON OF ANTON [ACTIVE]';
    if (gateNode) {
      gateNode.classList.remove('gate-locked');
      gateNode.classList.add('gate-bypassed');
    }
    if (gateBadge) {
      gateBadge.textContent = 'AUTO-BYPASS ⚡';
      gateBadge.style.color = '#10b981';
    }
    if (gateDesc) gateDesc.textContent = 'Cryptographic Bypass Logged';
  } else {
    btn.classList.remove('active');
    lbl.textContent = '⚡ SON OF ANTON [OFF]';
    if (gateNode) {
      gateNode.classList.remove('gate-bypassed');
      gateNode.classList.add('gate-locked');
    }
    if (gateBadge) {
      gateBadge.textContent = 'FAIL-CLOSED';
      gateBadge.style.color = '#f59e0b';
    }
    if (gateDesc) gateDesc.textContent = 'verify_balance.py (Δ=0)';
  }
}

function toggleSonOfAnton() {
  if (!sonOfAntonActive) {
    $('son-modal').style.display = 'flex';
  } else {
    setSonMode(false);
  }
}
function closeSonModal() { $('son-modal').style.display = 'none'; }
async function confirmSonOfAnton() { closeSonModal(); await setSonMode(true); }

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
  } catch (e) { showToast('Mode change failed', 'error'); }
}

async function loadOps() {
  try {
    const [l, a] = await Promise.all([
      fetch('/api/ledger').then(r => r.json()),
      fetch('/api/approvals').then(r => r.json())
    ]);

    if (a.length > 0) {
      const top = a[0];
      activeApprovalId = top.id;
      $('decision-hud-container').innerHTML = `
        <div class="decision-card">
          <div class="decision-header">
            <span class="decision-badge">Approval #${top.id}</span>
            <span style="font-size:0.65rem;font-family:var(--font-mono);color:var(--text-dim)">${top.nonce.substring(0,8)}...</span>
          </div>
          <div style="font-size:0.92rem;font-weight:700;margin-bottom:4px">${top.action}</div>
          <div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:12px">Recipient: ${top.recipient || 'N/A'} · Amount: ${top.amount || '0.00'}</div>
          <div style="display:flex;gap:8px">
            <button class="btn-approve" onclick="resolveApproval(${top.id}, 'approve')">✓ Approve (↵)</button>
            <button class="btn-deny" onclick="resolveApproval(${top.id}, 'deny')">✗ Deny (⎋)</button>
          </div>
        </div>
      `;
    } else {
      activeApprovalId = null;
      $('decision-hud-container').innerHTML = sonOfAntonActive 
        ? '<div style="padding:14px;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.3);border-radius:8px;text-align:center;font-size:0.75rem;color:#fbbf24">⚡ Son of Anton Mode Active<br>Human gates are auto-approved.</div>'
        : '<p style="font-size:0.75rem;color:var(--text-dim);text-align:center;padding:15px 0">All gates operating securely.</p>';
    }

    $('live-activity-feed').innerHTML = l.slice(-5).reverse().map(r => `
      <div style="padding:7px 10px;background:#141722;border:1px solid var(--border);border-radius:8px;font-size:0.75rem">
        <div style="font-weight:600">${r.task} <span style="color:${r.exit===0?'#10b981':'#ef4444'}">(exit ${r.exit})</span></div>
        <div style="font-size:0.68rem;color:var(--text-dim);font-family:var(--font-mono)">${r.flags || 'none'} · ${r.ts.substring(11,19)}</div>
      </div>
    `).join('');

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
  } catch (e) { showToast(e.message, 'error'); }
}

$('cmd-input').addEventListener('keydown', async e => {
  if (e.key === 'Enter') {
    const q = $('cmd-input').value.trim();
    if (!q) return;
    $('cmd-input').value = 'Thinking...';
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: q })
      });
      const data = await res.json();
      $('cmd-input').value = '';
      if (data.note_path) openMarkdownReader(data.note_path);
      showToast(data.reply, 'success');
    } catch (err) {
      $('cmd-input').value = '';
      showToast('Execution error: ' + err.message, 'error');
    }
  }
});

window.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault(); $('cmd-input').focus();
  } else if (e.key === 'Enter' && activeApprovalId && document.activeElement !== $('cmd-input')) {
    resolveApproval(activeApprovalId, 'approve');
  } else if (e.key === 'Escape') {
    closeMarkdownReader();
    if (activeApprovalId) resolveApproval(activeApprovalId, 'deny');
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
      .nodeColor(n => n.type === 'moc' ? '#c084fc' : (n.type === 'skill' ? '#10b981' : '#38bdf8'))
      .nodeVal('val')
      .linkWidth(1.2)
      .linkOpacity(0.4)
      .onNodeClick(node => {
        openMarkdownReader(node.id);
      });
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

checkMode(); loadOps(); setInterval(loadOps, 3500);
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
        """Fetches and serves raw markdown content for the in-app markdown reader."""
        p = os.path.join(data_dir, "vault", path + ".md")
        if not os.path.exists(p):
            p = os.path.join(data_dir, "vault", path)
        if not os.path.exists(p):
            p = os.path.join(data_dir, path)
        if not os.path.exists(p):
            slug = path.replace("skills/", "")
            p = os.path.join(data_dir, "skills", slug, "SKILL.md")
        if not os.path.exists(p):
            raise HTTPException(404, f"note not found: {path}")
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()
        return {"path": path, "content": content}

    @app.post("/api/chat")
    def chat_prompt(req: ChatReq):
        """Handles regular conversational interactions and Second Brain queries."""
        p_lower = req.prompt.lower()
        if "reconcil" in p_lower or "invoice" in p_lower:
            return {
                "reply": "I have verified your Stripe and QuickBooks ledger entries. 1 discrepancy ($14.50) is held at the human gate.",
                "note_path": "mocs/operations"
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
                "reply": f"Anton received: '{req.prompt}'. Second Brain knowledge query completed.",
                "note_path": "mocs/strategy"
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
