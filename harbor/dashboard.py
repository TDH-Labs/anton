"""FastAPI dashboard — read-only pane of glass + approvals API (M4).

The dashboard NEVER executes jobs. Approvals write only to the `approvals` table;
downstream gated tools (M5) consult it before any commit (R1).
"""
from __future__ import annotations

import datetime as dt
import os
import secrets

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .canary import compute_tripwires
from .digest import build_digest
from .scheduler import JobEngine

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>harbor-sas — control plane</title>
<style>
body{font-family:ui-monospace,Menlo,monospace;margin:2rem;background:#0f1115;color:#d7dae0}
h1{font-size:1.2rem}h2{font-size:1rem;margin-top:1.6rem;border-bottom:1px solid #262b33;padding-bottom:.3rem}
table{border-collapse:collapse;font-size:.8rem;width:100%}
td,th{border:1px solid #262b33;padding:.3rem .5rem;text-align:left}
.badge{padding:.1rem .5rem;border-radius:3px;font-size:.7rem}
.ok{background:#123} .warn{background:#331;color:#fc6} .err{background:#311;color:#f66}
pre{background:#11151b;padding:.8rem;overflow:auto;max-height:300px}
</style></head><body>
<h1>harbor-sas — control plane <span id="status"></span></h1>
<h2>Canary</h2><table id="canary"></table>
<h2>Completed (last 24h)</h2><table id="ledger"></table>
<h2>Pipeline ahead</h2><table id="init"></table>
<h2>LLM usage (24h, cloud)</h2><div id="usage"></div>
<h2>Jobs</h2><table id="jobs"></table>
<h2>Approvals pending</h2><table id="approvals"></table>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){
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
  $('usage').textContent=`cloud runs: ${u.cloud_runs} · tokens: ${u.tokens_in} in / ${u.tokens_out} out · cost: $${u.cost_usd.toFixed(4)}`;
  $('jobs').innerHTML=j.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.trigger.type)}</td><td>${esc(x.trigger.expr||x.trigger.path||'')}</td><td>${esc(x.model_route)}</td></tr>`).join('');
  $('approvals').innerHTML=a.length?a.map(x=>`<tr><td>#${x.id}</td><td>${esc(x.action)}</td><td>${esc(x.amount??'')}</td><td>${esc(x.recipient??'')}</td><td>${esc(x.status)}</td></tr>`).join(''):'<tr><td colspan=5>(none)</td></tr>';
}
load(); setInterval(load, 5000);
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


def create_app(engine: JobEngine, data_dir: str, config: dict) -> FastAPI:
    app = FastAPI(title="harbor-sas control plane")
    ledger = engine.ledger

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
    def create_approval(req: ApprovalReq):
        nonce = secrets.token_hex(16)
        import sqlite3
        conn = sqlite3.connect(os.path.join(data_dir, "isolation.db"))
        conn.execute("INSERT INTO approvals(nonce, action, amount, recipient, status, ts) "
                     "VALUES(?,?,?,?,?,?)",
                     (nonce, req.action, req.amount, req.recipient, "pending",
                      dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        conn.commit()
        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return {"id": aid, "nonce": nonce, "status": "pending"}

    @app.post("/api/approvals/{aid}/resolve")
    def resolve_approval(aid: int, req: ResolveReq):
        if req.decision not in ("approve", "deny"):
            raise HTTPException(400, "decision must be approve|deny")
        import sqlite3
        conn = sqlite3.connect(os.path.join(data_dir, "isolation.db"))
        cur = conn.execute("UPDATE approvals SET status=? WHERE id=? AND status='pending'",
                           ("approved" if req.decision == "approve" else "denied", aid))
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            raise HTTPException(404, "no pending approval with that id")
        return {"id": aid, "status": "approved" if req.decision == "approve" else "denied"}

    @app.get("/api/digest", response_class=PlainTextResponse)
    def digest():
        content = build_digest(engine, os.path.join(data_dir, "vault"), config)
        return content

    return app


def _db_rows(data_dir: str, sql: str, params: tuple = ()) -> list:
    import sqlite3
    path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(path):
        return []
    conn = sqlite3.connect(path)
    rows = [dict(zip([c[0] for c in cur.description], r))
            for cur in (conn.execute(sql, params),) for r in cur.fetchall()]
    conn.close()
    return rows
