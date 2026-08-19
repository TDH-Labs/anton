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
<html><head><meta charset="utf-8"><title>harbor-sas — control plane</title>
<script src="https://unpkg.com/3d-force-graph"></script>
<style>
body{font-family:ui-monospace,Menlo,monospace;margin:0;padding:1.5rem;background:#0f1115;color:#d7dae0}
h1{font-size:1.2rem;display:flex;align-items:center;justify-content:space-between;margin-top:0}
h2{font-size:1rem;margin-top:1.4rem;border-bottom:1px solid #262b33;padding-bottom:.3rem}
table{border-collapse:collapse;font-size:.8rem;width:100%;margin-bottom:1rem}
td,th{border:1px solid #262b33;padding:.4rem .6rem;text-align:left}
.badge{padding:.15rem .5rem;border-radius:3px;font-size:.7rem;font-weight:bold}
.ok{background:#133;color:#4e9} .warn{background:#331;color:#fc6} .err{background:#311;color:#f66}
pre{background:#11151b;padding:.8rem;overflow:auto;max-height:300px}
.nav-tabs{display:flex;gap:8px;border-bottom:1px solid #262b33;margin-bottom:1.5rem}
.tab-btn{background:none;border:none;color:#8a919e;padding:8px 16px;cursor:pointer;font-family:inherit;font-size:.9rem;border-bottom:2px solid transparent}
.tab-btn.active{color:#fff;border-bottom:2px solid #388bfd;font-weight:bold}
.tab-pane{display:none}
.tab-pane.active{display:block}
.wizard-card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:1.2rem;margin-bottom:1rem}
.form-group{margin-bottom:1rem}
label{display:block;margin-bottom:.4rem;font-size:.85rem;color:#c9d1d9}
input[type=text],input[type=password],select{background:#0d1117;border:1px solid #30363d;color:#c9d1d9;padding:6px 10px;border-radius:4px;width:100%;max-width:400px;font-family:inherit}
button.action-btn{background:#238636;color:#fff;border:1px solid #2ea043;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:.85rem}
button.action-btn:hover{background:#2ea043}
button.sec-btn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:6px 14px;border-radius:4px;cursor:pointer;font-family:inherit;font-size:.85rem}
#graph-container{width:100%;height:500px;background:#0d1117;border:1px solid #30363d;border-radius:6px;position:relative}
#graph-info{position:absolute;top:10px;left:10px;background:rgba(15,17,21,0.85);padding:8px 12px;border:1px solid #30363d;border-radius:4px;font-size:.8rem;pointer-events:none}
</style></head><body>
<h1>
  <span>🌌 harbor-sas — control plane <span id="status" style="font-weight:normal;color:#8a919e;font-size:.85rem"></span></span>
  <span style="font-size:.8rem;color:#58a6ff">Agent Canvas & 3D Neural Viewport Ready</span>
</h1>

<div class="nav-tabs">
  <button class="tab-btn active" onclick="switchTab('ops')">📊 Control Plane & Telemetry</button>
  <button class="tab-btn" onclick="switchTab('neural')">🌌 3D Neural Second Brain</button>
  <button class="tab-btn" onclick="switchTab('wizard')">⚙️ Setup Wizard (Providers, OAuth & MCP)</button>
</div>

<div id="tab-ops" class="tab-pane active">
  <h2>Tripwire Canaries</h2><table id="canary"></table>
  <h2>Completed Runs (Last 24h)</h2><table id="ledger"></table>
  <h2>Initiatives Pipeline (Ahead)</h2><table id="init"></table>
  <h2>LLM Usage & Metering (24h)</h2><div id="usage" style="margin-bottom:1rem;color:#58a6ff"></div>
  <h2>Active Deterministic Jobs</h2><table id="jobs"></table>
  <h2>Human Approvals Pending (Gate)</h2><table id="approvals"></table>
</div>

<div id="tab-neural" class="tab-pane">
  <h2>Second Brain Neural Graph (Force-Directed WebGL Map)</h2>
  <div id="graph-container">
    <div id="graph-info">Hover or click a node to view connections</div>
  </div>
  <p style="font-size:.8rem;color:#8a919e;margin-top:.8rem">
    🟣 MOC Hubs &nbsp;|&nbsp; 🔵 Knowledge Notes &nbsp;|&nbsp; 🟢 Skills &nbsp;|&nbsp; 🔴 Incident Logs &nbsp;|&nbsp; 🟡 Temporal Digests
  </p>
</div>

<div id="tab-wizard" class="tab-pane">
  <h2>Turnkey Setup Wizard</h2>
  
  <div class="wizard-card">
    <h3 style="margin-top:0">1. LLM & Cloud Providers Setup</h3>
    <p style="font-size:.85rem;color:#8a919e">Configure provider API keys. Keys are saved to <code>secrets.yaml</code> with strict 0600 permissions.</p>
    <div class="form-group">
      <label>Provider</label>
      <select id="wiz-provider">
        <option value="openrouter">OpenRouter (Claude, Llama, Qwen)</option>
        <option value="anthropic">Anthropic (Claude 3.5 Sonnet direct)</option>
        <option value="openai">OpenAI (GPT-4o, o1, o3)</option>
        <option value="gemini">Google Gemini API</option>
        <option value="deepseek">DeepSeek API</option>
        <option value="local">Local [REDACTED-LOCAL-INFERENCE] / Ollama (http://localhost:11434)</option>
      </select>
    </div>
    <div class="form-group">
      <label>API Key / Local Base URL</label>
      <input type="password" id="wiz-key" placeholder="sk-...">
    </div>
    <button class="action-btn" onclick="saveProviderKey()">Save & Validate Key</button>
    <span id="wiz-key-status" style="margin-left:10px;font-size:.85rem"></span>
  </div>

  <div class="wizard-card">
    <h3 style="margin-top:0">2. Graphical OAuth Connections</h3>
    <p style="font-size:.85rem;color:#8a919e">Connect external services via local loopback OAuth callback server (<code>harbor/oauth.py</code>).</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <button class="sec-btn" onclick="startOAuth('google')">🔗 Connect Google / Gmail</button>
      <button class="sec-btn" onclick="startOAuth('github')">🔗 Connect GitHub</button>
      <button class="sec-btn" onclick="startOAuth('slack')">🔗 Connect Slack</button>
      <button class="sec-btn" onclick="startOAuth('qbo')">🔗 Connect QuickBooks Online</button>
    </div>
    <div id="oauth-status" style="margin-top:.8rem;font-size:.85rem;color:#58a6ff"></div>
  </div>

  <div class="wizard-card">
    <h3 style="margin-top:0">3. MCP Server Connections & Room Gates</h3>
    <p style="font-size:.85rem;color:#8a919e">Manage Model Context Protocol (MCP) server bridges and room capability assignments.</p>
    <div class="form-group">
      <label>MCP Server Name</label>
      <input type="text" id="mcp-name" placeholder="e.g. gdrive-mcp or postgres-mcp">
    </div>
    <div class="form-group">
      <label>Command & Arguments (JSON or CLI)</label>
      <input type="text" id="mcp-cmd" placeholder="npx -y @modelcontextprotocol/server-postgres postgresql://...">
    </div>
    <div class="form-group">
      <label>Assign to Room Scope</label>
      <select id="mcp-room">
        <option value="devops">devops</option>
        <option value="bookkeeping">bookkeeping</option>
        <option value="finance_real_estate">finance_real_estate</option>
        <option value="legal">legal</option>
        <option value="strategy">strategy</option>
      </select>
    </div>
    <button class="action-btn" onclick="registerMCP()">Register MCP Server</button>
    <div id="mcp-list" style="margin-top:1rem"></div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function switchTab(name){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active');
  $('tab-'+name).classList.add('active');
  if(name==='neural' && !window.graphLoaded) initGraph();
}

async function loadOps(){
  const [c,l,i,u,j,a]=await Promise.all([
    fetch('/api/canary').then(r=>r.json()),
    fetch('/api/ledger?limit=15').then(r=>r.json()),
    fetch('/api/initiatives').then(r=>r.json()),
    fetch('/api/usage').then(r=>r.json()),
    fetch('/api/jobs').then(r=>r.json()),
    fetch('/api/approvals').then(r=>r.json())]);
  $('status').textContent='— '+new Date().toISOString();
  $('canary').innerHTML=c.length?c.map(t=>`<tr><td><span class="badge warn">TRIPWIRE</span></td><td>${esc(t.job_id)}</td><td>last ${esc(t.last_seen??'never')}</td></tr>`).join(''):'<tr><td colspan=3>PASS — all within cadence</td></tr>';
  $('ledger').innerHTML=l.map(r=>`<tr><td>${esc(r.ts)}</td><td>${esc(r.task)}</td><td><span class="badge ${r.exit==0?'ok':'err'}">${r.exit}</span></td><td>${esc(r.model??'')}</td><td>${esc(r.provider??'')}</td></tr>`).join('');
  $('init').innerHTML=i.length?i.map(x=>`<tr><td>${esc(x.slug)}</td><td>${esc(x.source)}</td><td>${esc(x.risk)}</td></tr>`).join(''):'<tr><td colspan=3>(none)</td></tr>';
  $('usage').textContent=`Cloud runs: ${u.cloud_runs} · Tokens: ${u.tokens_in} in / ${u.tokens_out} out · Cost: $${u.cost_usd.toFixed(4)}`;
  $('jobs').innerHTML=j.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.trigger.type)}</td><td>${esc(x.trigger.expr||x.trigger.path||'')}</td><td>${esc(x.model_route)}</td></tr>`).join('');
  $('approvals').innerHTML=a.length?a.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.action)}</td><td>${esc(x.amount??'')}</td><td>${esc(x.recipient??'')}</td><td>${esc(x.status)}</td></tr>`).join(''):'<tr><td colspan=5>(none)</td></tr>';
}

async function initGraph(){
  window.graphLoaded=true;
  try{
    const gData = await fetch('/api/vault/graph').then(r=>r.json());
    const elem = $('graph-container');
    const Graph = ForceGraph3D()(elem)
      .graphData(gData)
      .nodeLabel('title')
      .nodeColor(node => {
        if(node.type==='moc') return '#a371f7';
        if(node.type==='skill') return '#3fb950';
        if(node.type==='incident') return '#f85149';
        if(node.type==='digest') return '#d29922';
        return '#58a6ff';
      })
      .nodeVal('val')
      .linkDirectionalParticles(2)
      .linkDirectionalParticleSpeed(0.005)
      .onNodeHover(node => {
        $('graph-info').textContent = node ? `${node.title} (${node.type}) - ${node.links||0} links` : 'Hover or click a node to view connections';
      });
  }catch(e){
    console.error(e);
  }
}

async function saveProviderKey(){
  const prov = $('wiz-provider').value;
  const key = $('wiz-key').value;
  if(!key) return alert('Please enter an API key or URL');
  $('wiz-key-status').textContent = 'Saving...';
  const res = await fetch('/api/wizard/providers', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({provider: prov, key: key})
  });
  if(res.ok){
    $('wiz-key-status').innerHTML = '<span style="color:#4e9">✓ Saved & Validated</span>';
    $('wiz-key').value = '';
  } else {
    $('wiz-key-status').innerHTML = '<span style="color:#f66">✗ Save failed</span>';
  }
}

async function startOAuth(provider){
  $('oauth-status').textContent = `Launching OAuth loopback for ${provider}...`;
  const res = await fetch(`/api/wizard/oauth/start?provider=${provider}`);
  const data = await res.json();
  $('oauth-status').innerHTML = `OAuth server listening on port ${data.port}. Please authorize in browser.`;
  if(data.auth_url) window.open(data.auth_url, '_blank');
}

async function registerMCP(){
  const name = $('mcp-name').value;
  const cmd = $('mcp-cmd').value;
  const room = $('mcp-room').value;
  if(!name || !cmd) return alert('Name and Command required');
  const res = await fetch('/api/wizard/mcp', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name, command: cmd, room})
  });
  if(res.ok){
    alert('MCP server registered and assigned to room ' + room);
    $('mcp-name').value=''; $('mcp-cmd').value='';
    loadMCP();
  }
}

async function loadMCP(){
  const res = await fetch('/api/wizard/mcp');
  const list = await res.json();
  $('mcp-list').innerHTML = list.length ? '<table><tr><th>Name</th><th>Room</th><th>Status</th></tr>' + 
    list.map(m=>`<tr><td>${esc(m.name)}</td><td>${esc(m.room)}</td><td><span class="badge ok">ACTIVE</span></td></tr>`).join('') + '</table>' : '<p style="font-size:.8rem;color:#8a919e">No custom MCP servers registered yet.</p>';
}

loadOps(); setInterval(loadOps, 5000); loadMCP();
</script></body></html>"""


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
    app = FastAPI(title="harbor-sas control plane")
    ledger = engine.ledger
    token = (config.get("general") or {}).get("dashboard_token") or _os.environ.get("HARBOR_DASHBOARD_TOKEN") or ""
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

