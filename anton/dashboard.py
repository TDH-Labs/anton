"""FastAPI agent dashboard + approvals API for Anton (M4)."""
from __future__ import annotations

import datetime as dt
import json
import os
import secrets
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, FileResponse

from .canary import compute_tripwires
from .connections import (LAST_REGISTRY_ERROR, bridges_configured, bundled_catalog,
                          composio_apps, nango_integrations, registry_servers)
from .digest import build_digest
from .models import RunRecord
from .providers import catalog_for_ui, list_models
from .ops_api import open_isolation_db, register_ops_routes
from .ops_schema import ensure_ops_schema, ensure_vault_ops_schema
from .routes import select_route
from .scheduler import JobEngine, get_son_of_anton_mode, set_son_of_anton_mode

# This port (8799) is never published in the real Docker deployment -- the
# Ops Center at :3080 (auth-gate -> dsh web) is the actual product surface a
# customer uses. This used to serve a full standalone chat-UI prototype
# seeded with fabricated demo content (a fake approval gate, fake tool-call
# output, a fake award-campaign artifact) and backed by a keyword-matching
# /api/chat stub, not a real model. Removed: a fake "AI chat" that returns
# canned text indistinguishable from a real response is a trust problem, not
# a placeholder, and this page was never real functionality to begin with.
# What's left below is a minimal, honest landing page for anyone who reaches
# this port directly (e.g. running natively without Docker) -- the real
# routes this file serves (/api/wizard/*, /api/logo, /api/approvals, etc.)
# are unaffected.
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Anton</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500&family=Barlow+Condensed:wght@600&display=swap" rel="stylesheet">
<style>
  body {
    font-family: 'Barlow', system-ui, sans-serif; background: #f2f2f3; color: #1d1f20;
    max-width: 460px; margin: 16vh auto 0; padding: 0 20px;
  }
  h1 { font-family: 'Barlow Condensed', system-ui, sans-serif; font-weight: 600; font-size: 30px; margin: 0 0 10px; }
  p { color: rgba(29,31,32,.65); font-size: 14px; line-height: 1.6; }
  code { font-family: ui-monospace, Menlo, monospace; background: #e9e9ea; padding: .1em .4em; }
</style></head>
<body>
  <h1>Anton</h1>
  <p>This is the internal API server (port 8799) -- not the Ops Center. If you're
  looking for the app itself, that's served on port 3080.</p>
  <p>Real routes on this server: <code>/api/wizard/*</code>, <code>/api/approvals</code>,
  <code>/api/ledger</code>, <code>/api/canary</code>, and the others the Ops Center
  UI calls directly.</p>
</body></html>"""


# Known OAuth authorize-URL templates, keyed by provider id. Extending to a
# new service means adding an entry here (and the operator registering a
# real OAuth app for it in config.yaml's oauth.<provider>.client_id) -- not
# hardcoding a new single-provider flow the way this used to work.
OAUTH_AUTHORIZE_URLS: dict = {
    "google": ("https://accounts.google.com/o/oauth2/v2/auth", "email"),
    "quickbooks": ("https://appcenter.intuit.com/connect/oauth2", "com.intuit.quickbooks.accounting"),
    "slack": ("https://slack.com/oauth/v2/authorize", "channels:read"),
    "github": ("https://github.com/login/oauth/authorize", "repo"),
}


def _save_secret(install_dir: str, key_name: str, value: str) -> None:
    """Shared by the provider-key wizard step and the Add-ons "API key"
    connection type -- same file, same merge-then-write-0600 discipline,
    distinguished by key_name (an AI provider name like "openai", or
    "mcp:<id>" for an arbitrary connected service's token)."""
    import yaml
    secrets_path = os.path.join(install_dir, "secrets.yaml")
    current_secrets = {}
    if os.path.exists(secrets_path):
        with open(secrets_path, "r", encoding="utf-8") as f:
            current_secrets = yaml.safe_load(f) or {}
    current_secrets[key_name] = value
    content = yaml.safe_dump(current_secrets)
    fd = os.open(secrets_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)


def _set_cloud_model(install_dir: str, model: str) -> None:
    """Persist the wizard's model pick into config.yaml routes.cloud_model
    (the executor's routing default), flipping prefer to cloud -- a key the
    user just entered is by definition a cloud key."""
    import yaml
    config_path = os.path.join(install_dir, "config.yaml")
    current = {}
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}
    routes = current.get("routes") or {}
    routes["cloud_model"] = model
    routes["prefer"] = "cloud"
    current["routes"] = routes
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(current, f)
    os.replace(tmp, config_path)


class OAuthCompleteReq(BaseModel):
    provider: str = "quickbooks"

class ApprovalReq(BaseModel):
    action: str
    amount: str = "0.00"
    recipient: str = ""

class ResolveReq(BaseModel):
    decision: str

class ApprovalDecisionReq(BaseModel):
    decision: str

class ProviderReq(BaseModel):
    provider: str
    key: str
    # Custom (OpenAI-compatible) providers: where to reach them. Also used by
    # known providers only if someone self-hosts a proxy; ignored otherwise.
    base_url: str = ""
    # Optional model selection from the wizard's model step. Persisted to
    # config.yaml routes.cloud_model so the executor picks it up on next poll.
    model: str = ""

class SetupWizardReq(BaseModel):
    step: str = "review"
    picks: List[str] = []

class MCPReq(BaseModel):
    name: str
    command: str
    room: str = ""
    what: str = ""
    permissions: List[str] = []
    # Present only for the "API key" connection type (Add-ons "connect
    # something new" -> a service with no OAuth/MCP, just a token). Stored
    # the same way provider keys are (secrets.yaml, 0600), under a
    # mcp:<id> namespace so it never collides with a real AI provider name.
    api_key: str = ""

class ModelsReq(BaseModel):
    provider: str
    key: str = ""
    base_url: str = ""

class ConnectReq(BaseModel):
    id: str
    name: str = ""
    what: str = ""
    url: str = ""
    auth: str = ""
    command: str = ""
    bridge: str = ""

class BrowserLoginReq(BaseModel):
    """The 4th Add-ons connection type: a service with no OAuth, MCP, or API
    key, so Anton signs in like a person would. No universal login form
    exists to detect safely, so the operator supplies the selectors --
    same "operator supplies the last-mile detail" pattern as OAuth's
    client_id."""
    name: str
    login_url: str
    username: str
    password: str
    what: str = ""
    username_selector: str = "input[type=email], input[type=text]"
    password_selector: str = "input[type=password]"
    submit_selector: str = "button[type=submit]"
    success_selector: str

class ModeReq(BaseModel):
    # Default True, not required: the Ops Center UI's two calling sites
    # (SidebarRoot.tsx, Brand.tsx) POST here with no body at all -- the
    # endpoint name alone implies the direction, matching /api/mode/standard's
    # fixed-false sibling below.
    son_of_anton_mode: bool = True

class ChatReq(BaseModel):
    prompt: str

def _require_token(request, token: str) -> None:
    # When the authZ spine is wired (config authz.enabled), identity comes
    # from per-user sessions resolved by AuthzMiddleware; the legacy shared
    # token is dead (REQ-AUTH-01, CI-T-AUTH-01). request.state.principal is
    # set by the middleware for authenticated requests.
    if getattr(request.app.state, "authz_middleware_active", False):
        if getattr(request.state, "principal", None) is None:
            raise HTTPException(401, "missing or invalid bearer token")
        return
    # An empty token means the operator explicitly opted out (create_app warns
    # loudly at startup); it must never silently disable auth on a deployment
    # that was expected to have one.
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
    app = FastAPI(title="anton")
    ledger = engine.ledger
    token = (config.get("general") or {}).get("dashboard_token") or _os.environ.get("ANTON_DASHBOARD_TOKEN") or _os.environ.get("HARBOR_DASHBOARD_TOKEN") or ""
    if token:
        app.state.dashboard_token = token
    else:
        import sys as _sys
        print(
            "WARNING: no dashboard_token configured — every write/approval endpoint "
            "is UNAUTHENTICATED. Set general.dashboard_token (or ANTON_DASHBOARD_TOKEN) "
            "and never expose this port beyond loopback without the auth-gate.",
            file=_sys.stderr,
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/health")
    def health():
        """Container/Umbrel healthcheck target for the dashboard's own port (distinct
        from `anton serve`'s webhook-server /health on its own port)."""
        return {"ok": True, "jobs": len(engine.jobs)}

    @app.get("/api/logo")
    def get_logo():
        """Serves the classic Anton logo image, if this install has one."""
        install_dir = os.path.dirname(data_dir) if data_dir.endswith(".dev-data") else os.getcwd()
        logo_path = os.path.join(install_dir, "assets", "logos", "anton_logo.jpg")
        if os.path.exists(logo_path):
            return FileResponse(logo_path, media_type="image/jpeg")
        raise HTTPException(404, "logo image not found")

    @app.get("/api/logo/son-of-anton")
    def get_son_of_anton_logo():
        """Serves the alternate Son of Anton logo, if this install has one."""
        install_dir = os.path.dirname(data_dir) if data_dir.endswith(".dev-data") else os.getcwd()
        svg_path = os.path.join(install_dir, "assets", "logos", "son_of_anton_logo.svg")
        if os.path.exists(svg_path):
            return FileResponse(svg_path, media_type="image/svg+xml")
        raise HTTPException(404, "son of anton logo not found")

    @app.get("/api/mode")
    def get_mode():
        # DB value wins: another process (the scheduler) may have observed a
        # toggle this process restarted past; in-memory is the fallback.
        mode = get_son_of_anton_mode(data_dir) if data_dir else engine.son_of_anton_mode
        return {"son_of_anton_mode": bool(mode) or engine.son_of_anton_mode}

    @app.post("/api/mode/son-of-anton")
    def set_mode(request: Request, req: ModeReq = ModeReq()):
        # req's own default (son_of_anton_mode=True) only relaxes field
        # validation *within* a body; FastAPI still requires a body to be
        # present unless the parameter itself defaults, which is what lets
        # the Ops Center UI's no-body POST through.
        _require_token(request, token)
        engine.son_of_anton_mode = req.son_of_anton_mode
        # Persist: serve/scheduler runs in a separate process and reads this
        # at gate-decision time — an in-memory-only flag never reaches it.
        set_son_of_anton_mode(data_dir, req.son_of_anton_mode)
        return {"status": "updated", "son_of_anton_mode": engine.son_of_anton_mode}

    @app.post("/api/mode/standard")
    def set_mode_standard(request: Request):
        """SidebarRoot.tsx posts here when the Son of Anton toggle flips off;
        no request body (mirrors /api/mode/son-of-anton's boolean, fixed false)."""
        _require_token(request, token)
        engine.son_of_anton_mode = False
        set_son_of_anton_mode(data_dir, False)
        return {"status": "updated", "son_of_anton_mode": False}

    @app.get("/api/vault/note")
    def get_vault_note(request: Request, path: str):
        """Fetches and serves markdown or python code for the in-app document viewer.

        Authenticated and path-contained: `path` is resolved against a fixed set of
        base directories and rejected if the realpath escapes any of them (no ../
        traversal into secrets.yaml, web-token, browser-vault.key, etc.)."""
        _require_token(request, token)
        install_dir = os.path.dirname(data_dir) if data_dir.endswith(".dev-data") else os.getcwd()
        # Each candidate is (base, relpath): the file must resolve, by realpath,
        # to something still inside its own base directory. No free-form
        # install_dir join — that allowed reading repo-root secrets.yaml and,
        # with ../, anything else on the host (web-token, browser-vault.key).
        candidates = [
            (os.path.join(data_dir, "vault"), path + ".md"),
            (os.path.join(data_dir, "vault"), path),
            (os.path.join(data_dir, "skills", path.replace("skills/", "")), "SKILL.md"),
            (os.path.join(install_dir, "scripts"), os.path.basename(path)),
        ]

        found = None
        for base, rel in candidates:
            c = os.path.join(base, rel)
            real = os.path.realpath(c)
            if (
                real.startswith(os.path.realpath(base) + os.sep)
                and os.path.isfile(c)
                and not os.path.islink(c)
            ):
                found = c
                break
                
        if not found:
            raise HTTPException(404, f"file not found: {path}")
            
        with open(found, "r", encoding="utf-8") as f:
            content = f.read()
            
        is_code = found.endswith(".py") or found.endswith(".sh") or found.endswith(".yaml")

        # Ops Center contract fields (README, Data Contracts: GET /api/vault/note
        # -> { title, kind, author, body, provenance, usedCount, linkCount }),
        # added alongside the original {path, content, is_code} the embedded
        # dashboard's own viewer already depends on.
        title, note_kind, author, provenance = os.path.basename(path), "note", "agent", None
        used_count = link_count = 0
        vault_db_path = os.path.join(data_dir, "vault", "vault.db")
        if os.path.exists(vault_db_path):
            import sqlite3 as _sqlite3
            with _sqlite3.connect(vault_db_path, timeout=10.0) as vconn:
                ensure_vault_ops_schema(vconn)
                row = vconn.execute(
                    "SELECT title, author, kind, provenance FROM notes WHERE path=? OR path=?",
                    (path, path + ".md")).fetchone()
                if row:
                    title = row[0] or title
                    author = row[1] or author
                    note_kind = row[2] or (
                        "moc" if path.startswith("mocs/") else "skill" if path.startswith("skills/") else "note")
                    provenance = row[3]
                slug = os.path.splitext(path)[0]
                used_count = vconn.execute(
                    "SELECT COUNT(*) FROM graph_edges WHERE to_note=?", (slug,)).fetchone()[0]
                link_count = vconn.execute(
                    "SELECT COUNT(*) FROM graph_edges WHERE from_note=?", (slug,)).fetchone()[0]

        return {
            "path": path, "content": content, "is_code": is_code,
            "title": title, "kind": note_kind, "author": author, "body": content,
            "provenance": provenance, "usedCount": used_count, "linkCount": link_count,
        }

    @app.post("/api/chat")
    def chat_prompt(request: Request, req: ChatReq):
        """Real dispatch through the configured executor. This backs both direct
        callers of this endpoint and the Ops Center's own "Anton" chat provider
        option (apiproxy's AntonFastApiAdapter registers an LLM provider that
        POSTs here) -- a customer selecting "Anton" as their chat provider used
        to get keyword-matched fabricated replies indistinguishable from a real
        response. prefer="cloud": a fresh install's setup wizard captures a
        cloud provider key (Anthropic/OpenAI/DeepSeek/OpenRouter), which is what
        this should actually route to by default, not a local model server this
        deployment doesn't run."""
        _require_token(request, token)
        route = select_route(prefer="cloud")
        result = engine.executor.run(req.prompt, model=route.model, provider=route.provider)
        record = RunRecord.new(
            task="chat", exit_code=result.exit_code, flags="source:api/chat",
            output=result.output, model=result.model, provider=result.provider,
            fallback_used=result.fallback_used, tokens_in=result.tokens_in,
            tokens_out=result.tokens_out, cost_usd=result.cost_usd,
            duration_ms=result.duration_ms,
        )
        ledger.append(record)
        engine._record_metering(record)
        if result.exit_code != 0:
            raise HTTPException(502, result.stderr or result.output or "chat dispatch failed")
        return {"reply": result.output}

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
        """Automation[] (README, Data Contracts). Backed by the new `automations`
        table (ops_schema.py) — NOT the `initiatives` table, which stays exactly
        as delta.py's candidate-remediation detection has always used it; this
        route only changed what path `/api/initiatives` itself serves."""
        conn = open_isolation_db(data_dir)
        try:
            rows = conn.execute(
                "SELECT id, name, plain, trigger_kind, trigger_display, trigger_expr, "
                "needs_signoff, author, last_run, state, risk, nodes_json, links_json "
                "FROM automations ORDER BY ts DESC LIMIT 50").fetchall()
        finally:
            conn.close()
        out = []
        for (aid, name, plain, tkind, tdisplay, texpr, needs_signoff, author, last_run,
             state, risk, nodes_json, links_json) in rows:
            out.append({
                "id": aid, "name": name, "plain": plain,
                "trigger": {"kind": tkind, "display": tdisplay, "expr": texpr},
                "needsSignoff": bool(needs_signoff), "author": author, "lastRun": last_run,
                "state": state, "risk": risk,
                "nodes": json.loads(nodes_json or "[]"), "links": json.loads(links_json or "[]"),
            })
        return out

    @app.get("/api/jobs")
    def jobs():
        """Job[] { id, automationId, trigger, nextRun, lastRun, cadenceMin }
        (README, Data Contracts). `automationId` best-effort matches by job
        id — jobs.yaml carries no explicit automation-linkage field."""
        now = dt.datetime.now(dt.timezone.utc)
        out = []
        for j in engine.jobs:
            trig = j.trigger or {}
            next_run = None
            if trig.get("type") == "cron" and j.cron is not None:
                nxt = j.cron.next_after(now)
                next_run = nxt.strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None
            last = ledger.last_run(j.id)
            out.append({
                "id": j.id, "automationId": j.id, "trigger": trig,
                "nextRun": next_run, "lastRun": (last or {}).get("ts"),
                "cadenceMin": j.expected_cadence_min,
            })
        return out

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
        """Approval[] { id, title, sub, reason, evidence, changes, age, kind }
        (README, Data Contracts). The `title`/`sub`/`reason`/`evidence`/
        `changes`/`kind` columns are additive (ops_schema.py) — a row created
        through the original money/outbound gate path (action/amount/
        recipient, no UI-card fields set) still renders with a reasonable
        fallback instead of nulls."""
        conn = open_isolation_db(data_dir)
        try:
            rows = conn.execute(
                "SELECT id, nonce, action, amount, recipient, status, ts, "
                "title, sub, reason, evidence, changes_json, kind "
                "FROM approvals WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        finally:
            conn.close()
        out = []
        for (aid, nonce, action, amount, recipient, row_status, ts, title, sub, reason,
             evidence, changes_json, kind) in rows:
            out.append({
                "id": aid,
                "title": title or f"Approve {action}",
                "sub": sub or (f"{amount} to {recipient}" if recipient else action),
                "reason": reason or "Requires human sign-off before Anton can proceed.",
                "evidence": evidence or "",
                "changes": json.loads(changes_json) if changes_json else [],
                "age": _age_str(ts),
                "kind": kind or "money",
            })
        return out

    @app.post("/api/approvals/{aid}")
    def decide_approval(aid: int, req: ApprovalDecisionReq, request: Request):
        """POST /api/approvals/:id -> { decision } (README, Data Contracts).
        Distinct from the pre-existing `/resolve` sub-route (approve|deny,
        used by the embedded dashboard) — this is the Ops Center's own
        three-way decision. `once` and `always` both approve; `always` is
        additionally flagged via `kind` so a future standing-allow policy has
        somewhere to read it from. `defer` ("Not now") leaves the row pending."""
        _require_token(request, token)
        if req.decision not in ("once", "always", "defer"):
            raise HTTPException(400, "decision must be once|always|defer")
        conn = open_isolation_db(data_dir)
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            appr_h, appr_p = principal.human_id, principal.principal_id
        else:
            appr_h, appr_p = "legacy:operators", "api:decide"
        try:
            if req.decision == "defer":
                row = conn.execute("SELECT id FROM approvals WHERE id=?", (aid,)).fetchone()
                if row is None:
                    raise HTTPException(404, "no approval with that id")
                return {"id": aid, "status": "pending", "decision": "defer"}
            new_status = "approved"
            new_kind = "standing" if req.decision == "always" else None
            hmac = _decision_hmac(_hmac_secret, aid)
            if new_kind:
                cur = conn.execute(
                    "UPDATE approvals SET status=?, kind=?, approver_human=?, "
                    "approver_principal=?, hmac=? WHERE id=? AND status='pending'",
                    (new_status, new_kind, appr_h, appr_p, hmac, aid))
            else:
                cur = conn.execute(
                    "UPDATE approvals SET status=?, approver_human=?, "
                    "approver_principal=?, hmac=? WHERE id=? AND status='pending'",
                    (new_status, appr_h, appr_p, hmac, aid))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(404, "no pending approval with that id")
        except sqlite3.IntegrityError:
            conn.rollback()
            raise HTTPException(409, "approver may not equal initiator")
        finally:
            conn.close()
        return {"id": aid, "status": new_status, "decision": req.decision}

    @app.post("/api/approvals")
    def create_approval(req: ApprovalReq, request: Request):
        _require_token(request, token)
        nonce = secrets.token_hex(16)
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            init_h, init_p = principal.human_id, principal.principal_id
        else:
            # Legacy (authz-off) mode still writes explicit identity markers
            # so the DB-level approver!=initiator gate stays meaningful and
            # NULL-attributed rows are never produced by the API (R5-1).
            init_h, init_p = "legacy:creators", "api:create"
        with sqlite3.connect(os.path.join(data_dir, "isolation.db"),
                             timeout=10.0) as conn:
            conn.execute(
                "INSERT INTO approvals(nonce, action, amount, recipient, status,"
                " ts, initiator_human, initiator_principal) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (nonce, req.action, req.amount, req.recipient, "pending",
                 _now_iso(), init_h, init_p))
            aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        return {"id": aid, "nonce": nonce, "status": "pending"}

    @app.post("/api/approvals/{aid}/resolve")
    def resolve_approval(aid: int, req: ResolveReq, request: Request):
        _require_token(request, token)
        if req.decision not in ("approve", "deny"):
            raise HTTPException(400, "decision must be approve|deny")
        principal = getattr(request.state, "principal", None)
        if principal is not None:
            appr_h, appr_p = principal.human_id, principal.principal_id
        else:
            appr_h, appr_p = "legacy:operators", "api:decide"
        new_status = "approved" if req.decision == "approve" else "denied"
        hmac = _decision_hmac(_hmac_secret, aid)
        try:
            with sqlite3.connect(os.path.join(data_dir, "isolation.db"),
                                 timeout=10.0) as conn:
                cur = conn.execute(
                    "UPDATE approvals SET status=?, approver_human=?, "
                    "approver_principal=?, hmac=? WHERE id=? AND status='pending'",
                    (new_status, appr_h, appr_p, hmac, aid))
                conn.commit()
                if cur.rowcount == 0:
                    raise HTTPException(404, "no pending approval with that id")
        except sqlite3.IntegrityError:
            # REQ-APPR-01: approver == initiator rejected at the DB layer
            raise HTTPException(409, "approver may not equal initiator")
        return {"id": aid, "status": new_status}

    @app.get("/api/digest", response_class=PlainTextResponse)
    def digest():
        content = build_digest(engine, os.path.join(data_dir, "vault"), config)
        return content

    @app.get("/api/vault/graph")
    def vault_graph():
        vault_db_path = os.path.join(data_dir, "vault", "vault.db")
        if not os.path.exists(vault_db_path):
            # Honest empty state, not fabricated content -- a fresh install
            # (vault.db not provisioned yet) previously returned fake nodes
            # ("Operations MOC", a made-up skill) that looked like real
            # customer data. Matches the same single-placeholder-node
            # fallback already used below for "vault.db exists but has
            # nothing in it yet".
            return {"nodes": [{"id": "index", "title": "Second Brain Root", "type": "moc", "val": 12}], "links": []}
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
        _save_secret(os.path.dirname(data_dir), req.provider, req.key)
        if req.base_url.strip():
            _save_secret(os.path.dirname(data_dir), f"{req.provider}:base_url", req.base_url.strip())
        # Make the key visible to the already-running executor without waiting
        # for a restart (cli.py's loader is idempotent per env var).
        try:
            from .cli import _load_secrets_into_env
            _load_secrets_into_env(data_dir)
        except Exception:
            pass
        if req.model.strip():
            _set_cloud_model(os.path.dirname(data_dir), f"{req.provider}/{req.model.strip()}")
        return {"status": "saved", "provider": req.provider, "model": req.model}

    @app.get("/api/wizard/catalog")
    def wizard_catalog(request: Request):
        """Single source of truth for provider lists -- the wizard and the
        settings API-keys section both render from this, so they can never
        drift apart again."""
        _require_token(request, token)
        return {"providers": catalog_for_ui()}

    @app.get("/api/wizard/keys")
    def wizard_keys(request: Request):
        """Which providers already have a saved key (booleans only -- secrets
        are never echoed back to any UI) and the model chosen in the wizard,
        so settings can show real state instead of empty boxes."""
        _require_token(request, token)
        install_dir = os.path.dirname(data_dir)
        have: dict[str, bool] = {}
        secrets_path = os.path.join(install_dir, "secrets.yaml")
        if os.path.exists(secrets_path):
            import yaml
            with open(secrets_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            for k, v in raw.items():
                if isinstance(v, str) and v and not k.startswith("mcp:") and not k.endswith(":base_url"):
                    have[k] = True
                elif isinstance(v, str) and k.endswith(":base_url") and v:
                    have[k] = True
        chosen_model = ""
        config_path = os.path.join(install_dir, "config.yaml")
        if os.path.exists(config_path):
            import yaml
            with open(config_path, encoding="utf-8") as f:
                routes = (yaml.safe_load(f) or {}).get("routes") or {}
            chosen_model = str(routes.get("cloud_model") or "")
        return {"have_key": have, "cloud_model": chosen_model}

    @app.post("/api/wizard/models")
    def wizard_models_post(req: ModelsReq, request: Request):
        """Preferred form: key rides in the JSON body, never in URLs/logs."""
        _require_token(request, token)
        return _wizard_models_impl(req.provider, req.key, req.base_url)

    @app.get("/api/wizard/models")
    def wizard_models(request: Request, provider: str, key: str = "", base_url: str = ""):
        """DEPRECATED: key in query string leaks into logs/history. Kept for
        the current wizard bundle; remove once clients use POST."""
        """Live-list models for a provider key. Errors are explicit strings,
        never silent empties: an empty list with no error means the provider
        genuinely returned zero models."""
        return _wizard_models_impl(provider, key, base_url)

    def _wizard_models_impl(provider: str, key: str = "", base_url: str = ""):
        if not key:
            # Fall back to whatever key was already saved for this provider.
            secrets_path = os.path.join(os.path.dirname(data_dir), "secrets.yaml")
            if os.path.exists(secrets_path):
                import yaml
                with open(secrets_path, encoding="utf-8") as f:
                    key = (yaml.safe_load(f) or {}).get(provider, "") or ""
        try:
            models = list_models(provider, key, base_url or None)
        except ValueError as e:
            return {"error": str(e), "models": []}
        except Exception as e:
            return {"error": f"Unexpected error listing models: {e}", "models": []}
        return {"models": models, "error": None}

    @app.get("/api/wizard/oauth/start")
    def start_oauth(request: Request, provider: str = "google"):
        """Per-service OAuth starter, not hardcoded to one provider. This used
        to always build a Google authorize URL with client_id=demo -- a fake
        that could never actually complete an OAuth handshake, regardless of
        which service the Add-ons UI claimed to be connecting. An operator
        registers a real OAuth app for a given service (client_id, in
        config.yaml's oauth.<provider> section) before this can do anything
        real for that service; until then, this says so plainly instead of
        producing a URL that silently fails."""
        _require_token(request, token)
        oauth_cfg = (config.get("oauth") or {}).get(provider) or {}
        client_id = oauth_cfg.get("client_id")
        authorize_url, default_scope = OAUTH_AUTHORIZE_URLS.get(provider, (None, ""))
        if not authorize_url:
            return {"status": "not_configured",
                    "detail": f"Anton doesn't know {provider}'s OAuth authorize URL yet."}
        if not client_id:
            return {"status": "not_configured",
                    "detail": f"No OAuth app registered for {provider} yet -- "
                              f"set oauth.{provider}.client_id in config.yaml."}
        global _active_oauth_server
        from .oauth import CallbackServer
        if _active_oauth_server is not None:
            try:
                _active_oauth_server.stop()
            except Exception:
                pass
        _active_oauth_server = CallbackServer(port=0, timeout_s=120)
        _active_oauth_server.start()
        scope = oauth_cfg.get("scope", default_scope)
        auth_url = (f"{authorize_url}?client_id={client_id}"
                   f"&redirect_uri=http://localhost:{_active_oauth_server.port}/callback"
                   f"&response_type=code&scope={scope}")
        return {"status": "listening", "port": _active_oauth_server.port, "auth_url": auth_url}

    @app.post("/api/wizard/oauth/complete")
    def complete_oauth(request: Request, req: OAuthCompleteReq):
        """Finishes the flow started by /oauth/start: waits for the local
        callback, exchanges the code at the provider's token endpoint, and
        stores tokens encrypted (credential broker when authZ is wired,
        secrets.yaml fallback otherwise) — refresh tokens are never echoed
        back (handoff #5 end-to-end)."""
        _require_token(request, token)
        global _active_oauth_server
        from .qbo_oauth import exchange_code, load_qbo_credentials, store_tokens
        provider = req.provider.strip() or "quickbooks"
        server = _active_oauth_server
        if server is None:
            raise HTTPException(409, "no OAuth flow in progress -- "
                                     "call /api/wizard/oauth/start first")
        redirect_uri = f"http://localhost:{server.port}/callback"
        try:
            result = server.wait()
        except TimeoutError as e:
            raise HTTPException(504, str(e))
        finally:
            try:
                server.stop()
            except Exception:
                pass
            _active_oauth_server = None
        client_id, client_secret = load_qbo_credentials()
        oauth_cfg = (config.get("oauth") or {}).get(provider) or {}
        client_id = oauth_cfg.get("client_id") or client_id
        client_secret = client_secret or os.environ.get(
            f"{provider.upper()}_CLIENT_SECRET", "")
        if not (client_id and client_secret):
            return {"status": "not_configured",
                    "detail": f"no OAuth client credentials for {provider} "
                              "(config.yaml oauth.<provider>.client_id or "
                              "env QBO_CLIENT_ID/QBO_CLIENT_SECRET)"}
        tokens = exchange_code(client_id, client_secret, result.get("code", ""),
                               redirect_uri)
        broker = getattr(app.state, "authz_broker", None)
        principal = getattr(request.state, "principal", None)
        if broker is not None and principal is not None:
            store_tokens(app.state.authz_broker, app.state.authz_store,
                         app.state.authz_audit, actor=principal,
                         provider=provider, tokens=tokens)
        else:
            _save_secret(os.path.dirname(data_dir),
                         f"{provider}:refresh_token",
                         str(tokens.get("refresh_token", "")))
        return {"status": "connected", "provider": provider,
                "scopes": str(tokens.get("scope", ""))}

    @app.get("/api/wizard/mcp")
    def list_mcp(request: Request):
        """Addon[] { id, name, what, permissions, status } (README, Data
        Contracts). Backed by `mcp_servers` — the two defaults below are
        seeded on first read so an empty install still shows the core/
        filesystem MCP servers the embedded dashboard always assumed."""
        _require_token(request, token)
        conn = open_isolation_db(data_dir)
        try:
            count = conn.execute("SELECT COUNT(*) FROM mcp_servers").fetchone()[0]
            if count == 0:
                now = _now_iso()
                conn.executemany(
                    "INSERT INTO mcp_servers(id, name, what, permissions_json, status, room, ts) "
                    "VALUES(?,?,?,?,?,?,?)",
                    [
                        ("anton-mcp-core", "anton-mcp-core", "Anton's own core tools", "[]", "active", "", now),
                        ("filesystem-mcp", "filesystem-mcp", "Read/write the local filesystem", "[]", "active", "", now),
                    ])
                conn.commit()
            rows = conn.execute(
                "SELECT id, name, what, permissions_json, status FROM mcp_servers ORDER BY ts ASC").fetchall()
        finally:
            conn.close()
        return [{
            "id": r[0], "name": r[1], "what": r[2],
            "permissions": json.loads(r[3] or "[]"), "status": r[4],
        } for r in rows]
    @app.post("/api/wizard/mcp")
    def add_mcp(req: MCPReq, request: Request):
        _require_token(request, token)
        conn = open_isolation_db(data_dir)
        try:
            mcp_id = req.name.strip().lower().replace(" ", "-")
            conn.execute(
                "INSERT INTO mcp_servers(id, name, what, permissions_json, status, room, ts) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET what=excluded.what, "
                "permissions_json=excluded.permissions_json, room=excluded.room, ts=excluded.ts",
                (mcp_id, req.name, req.what, json.dumps(req.permissions), "active", req.room, _now_iso()))
            conn.commit()
            if req.api_key.strip():
                _save_secret(os.path.dirname(data_dir), f"mcp:{mcp_id}", req.api_key.strip())
        finally:
            conn.close()
        return {"status": "registered", "id": mcp_id, "name": req.name, "room": req.room}

    @app.get("/api/connections/catalog")
    def connections_catalog(request: Request, registry: str = "1"):
        """The abundant connection list: bundled entries + (optionally) the
        live MCP registry sync + hosted-OAuth bridge apps (Composio/Nango).
        Each entry carries transport/auth metadata so the UI can render the
        right connect flow. Never raises -- a dead network degrades to the
        bundled list."""
        _require_token(request, token)
        out = bundled_catalog()
        if registry == "1":
            out.extend(registry_servers(data_dir))
        bridges = bridges_configured(config)
        if bridges["composio"]:
            try:
                out.extend(composio_apps(config["bridges"]["composio"]["api_key"]))
            except Exception:
                pass
        if bridges["nango"]:
            try:
                out.extend(nango_integrations(config["bridges"]["nango"]["secret_key"]))
            except Exception:
                pass
        return {"connections": out, "bridges": bridges,
                "registry_error": LAST_REGISTRY_ERROR}

    @app.post("/api/connections/connect")
    def connections_connect(req: ConnectReq, request: Request):
        """Connect a catalog entry: remote-http entries store their URL (and
        optional bearer token); stdio entries install like any MCP server;
        bridge entries record which bridge owns them. All state lives in the
        mcp_servers table so existing consumers see one shape."""
        _require_token(request, token)
        conn = open_isolation_db(data_dir)
        try:
            perms = json.dumps({k: v for k, v in {
                "url": req.url, "auth": req.auth,
                "command": req.command, "bridge": req.bridge}.items() if v})
            conn.execute(
                "INSERT INTO mcp_servers(id, name, what, permissions_json, status, room, ts) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET what=excluded.what, "
                "permissions_json=excluded.permissions_json, status=excluded.status, ts=excluded.ts",
                (req.id, req.name or req.id, req.what or "", perms, "active", "", _now_iso()))
            conn.commit()
        finally:
            conn.close()
        return {"status": "connected", "id": req.id}

    @app.post("/api/wizard/browser-login")
    def add_browser_login(req: BrowserLoginReq, request: Request):
        """Registers a stored-login connection and performs the first real
        login. The password is stored encrypted (browser_vault) and used
        directly here to fill the form -- it is never returned in this
        response and never reaches an LLM. A later dispatch that uses the
        resulting persisted session for real work is a separate,
        governor-gated concern (kind="outbound"), not built here."""
        _require_token(request, token)
        from . import browser_login, browser_vault
        install_dir = os.path.dirname(data_dir)
        mcp_id = req.name.strip().lower().replace(" ", "-")
        browser_vault.store_credential(install_dir, mcp_id, req.username, req.password)

        conn = open_isolation_db(data_dir)
        try:
            conn.execute(
                "INSERT INTO mcp_servers(id, name, what, permissions_json, status, room, ts) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET what=excluded.what, ts=excluded.ts",
                (mcp_id, req.name, req.what, "[]", "pending", "", _now_iso()))
            conn.commit()
        finally:
            conn.close()

        selectors = browser_login.LoginSelectors(
            username_selector=req.username_selector, password_selector=req.password_selector,
            submit_selector=req.submit_selector, success_selector=req.success_selector)
        result = browser_login.perform_login(install_dir, mcp_id, req.login_url, selectors)

        conn = open_isolation_db(data_dir)
        try:
            conn.execute("UPDATE mcp_servers SET status=? WHERE id=?",
                        ("active" if result.status == "success" else "pending", mcp_id))
            conn.commit()
        finally:
            conn.close()
        return {"status": result.status, "detail": result.detail, "id": mcp_id, "name": req.name}

    register_ops_routes(app, engine, data_dir, config, token)

    # Multi-user authorization spine (docs/AUTHZ-SPEC.md v1.1). Off by
    # default until migration flag flips; when enabled it replaces the
    # shared-token path entirely.
    authz_cfg = config.get("authz") or {}
    if authz_cfg.get("enabled"):
        from .authz import wire_authz
        wire_authz(app, data_dir, config)
    return app

def _day_ago_iso() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return (now - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_hmac_secret = ""


def _set_hmac_secret(secret: str) -> None:
    global _hmac_secret
    _hmac_secret = secret


def _decision_hmac(secret: str, aid: int) -> str:
    """KEYED authenticity marker for decided rows (R9: unkeyed sha256 let a
    reader offline-crack a low-entropy secret). The scheduler/upskill
    verifier recomputes it with the shared decision secret."""
    import hashlib
    import hmac as _hmac
    return _hmac.new(secret.encode(), str(aid).encode(),
                     hashlib.sha256).hexdigest()


def _age_str(ts: Optional[str]) -> str:
    """"2H AGO" / "3D AGO" style relative-age string (README §5 example copy)."""
    if not ts:
        return ""
    try:
        then = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return ""
    delta = dt.datetime.now(dt.timezone.utc) - then
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "JUST NOW"
    if minutes < 60:
        return f"{minutes}M AGO"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}H AGO"
    return f"{hours // 24}D AGO"
