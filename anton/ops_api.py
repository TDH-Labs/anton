"""Anton Studio Ops Center API — the endpoints the design handoff's Data
Contracts section documents and dashboard.py did not previously serve:
`/api/systems`, `/api/agent/worklog`, `/api/incidents`,
`PUT /api/automations/:id`, `POST /api/setup` (wizard picks), and
`POST /api/automations/draft` (text-to-draft for "Describe it" / "Upload a
doc"). Registered
from `dashboard.create_app()` onto the same FastAPI app and isolation.db.

`/api/initiatives`, `/api/jobs`, `/api/approvals`, `/api/vault/note`, and
`/api/wizard/mcp` are reshaped in place in dashboard.py instead of duplicated
here, since that module already owns those paths.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .cron import Cron
from .models import RunRecord
from .ops_schema import ensure_ops_schema
from .routes import select_route
from .scheduler import JobEngine


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_isolation_db(data_dir: str) -> sqlite3.Connection:
    path = os.path.join(data_dir, "isolation.db")
    conn = sqlite3.connect(path, timeout=10.0)
    ensure_ops_schema(conn)
    return conn


class NodeIn(BaseModel):
    id: str
    kind: str
    x: float
    y: float
    text: str
    assignee: Optional[str] = None
    notify: Optional[List[str]] = None


class AutomationUpdate(BaseModel):
    """PUT body: the full node graph on approve (README, Data Contracts)."""
    name: Optional[str] = None
    plain: Optional[str] = None
    nodes: List[NodeIn]
    links: List[List[str]]
    state: Optional[str] = None


class WizardPicksReq(BaseModel):
    """POST /api/setup body: the first-run wizard's picks (README §11), distinct
    from the CLI's `anton setup` install-provisioning flow (setup.py)."""
    step: Optional[str] = None
    picks: List[str] = []


class AutomationDraftReq(BaseModel):
    """POST /api/automations/draft body. `description` is the plain-English
    ask ("Describe it") or a note about the uploaded procedure doc; when a
    .txt/.md doc is read client-side it arrives as `source_text` (with its
    filename as `source_name`)."""
    description: str
    source_text: Optional[str] = None
    source_name: Optional[str] = None


def build_draft_prompt(description: str, source_text: Optional[str] = None,
                       source_name: Optional[str] = None) -> str:
    """Strict text-to-draft prompt: JSON only, no prose around it, no tool
    use implied — the model drafts, it never acts."""
    source_block = ""
    if source_text:
        name = source_name or "uploaded document"
        source_block = (
            f"\nThe operator also uploaded a procedure document ({name}). Its full "
            f"text follows between the markers. Map what it describes into steps:\n"
            f"----- BEGIN {name} -----\n{source_text}\n----- END {name} -----\n")
    return f"""You are drafting an automation for Anton, an operations agent.
The operator described the automation they want in plain English:

{description.strip()}
{source_block}
Respond with JSON ONLY -- no markdown fences, no commentary before or after,
a single JSON object exactly matching this shape:

{{
  "name": "<short title case name, 2-6 words>",
  "plain": "<one sentence saying what it does>",
  "trigger": {{"kind": <one of "cron", "event", "interval", or null if unclear>,
              "display": "<human-readable when-it-runs, e.g. 'Every weekday at 7 AM', or null>",
              "expr": "<cron expression or interval string, or null if unknown>"}},
  "steps": [{{"text": "<one concrete action per step>", "assignee": <"agent" or "human" or null>}}]
}}

Rules:
- 2 to 8 steps. Each step is one concrete, checkable action.
- If a step needs a person's sign-off (money leaves, anything irreversible),
  set its assignee to "human".
- Do not invent connected systems you were not told about. If the description
  references a system, keep the reference generic (e.g. "the accounting file").
- READ-ONLY DRAFTING: produce JSON describing the workflow only. Do not claim
  to have run, scheduled, or contacted anything.
"""


def parse_automation_draft(output: str) -> dict:
    """Server-side shape validation of whatever the model returned -- same
    never-trust-the-dispatch discipline as opportunity.verify_opportunities.
    Raises ValueError with a user-presentable message unless `output` contains
    exactly one well-formed draft object. Returns the normalized draft dict."""
    text = output.strip()
    # Tolerate markdown fences even though the prompt forbids them.
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        end = text.rfind("```")
        if end != -1:
            text = text[:end]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"model output is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("draft must be a JSON object")

    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("draft.name must be a non-empty string")

    trigger = obj.get("trigger")
    if trigger is None:
        trigger = {}
    if not isinstance(trigger, dict):
        raise ValueError("draft.trigger must be an object or null")
    tkind = trigger.get("kind")
    if tkind is not None and tkind not in ("cron", "event", "interval"):
        raise ValueError("draft.trigger.kind must be cron|event|interval|null")
    tdisplay = trigger.get("display")
    texpr = trigger.get("expr")
    if tdisplay is not None and not isinstance(tdisplay, str):
        raise ValueError("draft.trigger.display must be a string or null")
    if texpr is not None and not isinstance(texpr, str):
        raise ValueError("draft.trigger.expr must be a string or null")

    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) == 0:
        raise ValueError("draft.steps must be a non-empty array")
    steps = []
    for s in raw_steps:
        if not isinstance(s, dict):
            raise ValueError("every draft.steps entry must be an object")
        text_ = s.get("text")
        if not isinstance(text_, str) or not text_.strip():
            raise ValueError("every step needs a non-empty text")
        assignee = s.get("assignee")
        if assignee is not None and assignee not in ("agent", "human"):
            assignee = None
        steps.append({"text": text_.strip(), "assignee": assignee})
    if len(steps) > 12:
        raise ValueError("draft.steps has too many entries (max 12)")

    plain = obj.get("plain")
    if not isinstance(plain, str):
        plain = ""
    return {
        "name": name.strip(), "plain": plain.strip(),
        "trigger": {"kind": tkind, "display": tdisplay, "expr": texpr},
        "steps": steps,
    }


def _require_token(request: Request, token: str) -> None:
    # Delegates to the dashboard's guard so the authZ spine (per-user
    # sessions, capability checks) governs ops routes too — a private copy
    # here would keep accepting the legacy shared token after the
    # migration flag flips and reject valid sessions.
    from .dashboard import _require_token as _dashboard_require_token
    _dashboard_require_token(request, token)


def register_ops_routes(app: FastAPI, engine: JobEngine, data_dir: str, config: dict, token: str) -> None:
    """Attach the Ops Center's genuinely-new routes to `app`.
    @param app - the FastAPI app dashboard.create_app() builds.
    @param engine - the running JobEngine (jobs, ledger, live state).
    @param data_dir - agent data directory (isolation.db lives here).
    @param config - loaded anton config.
    @param token - dashboard bearer token (empty string disables auth), matching
        dashboard.py's own `_require_token` convention.
    """

    @app.get("/api/systems")
    def list_systems():
        """System[] — external systems Anton watches (README, Data Contracts).
        Self-managed (this harness's own scheduler/webhook engine) is
        always reported first from live state; everything else comes from the
        `systems` table, seeded by whoever registers an integration."""
        conn = open_isolation_db(data_dir)
        try:
            rows = conn.execute(
                "SELECT id, name, sub, state, last_check, health, self_managed "
                "FROM systems ORDER BY ts DESC").fetchall()
        finally:
            conn.close()
        out = [{
            "id": "anton-scheduler", "name": "Anton scheduler", "sub": "cron + webhook engine",
            "state": f"{len(engine.jobs)} job(s) loaded", "lastCheck": _now_iso(),
            "health": "ok", "selfManaged": True,
        }]
        out += [{
            "id": r[0], "name": r[1], "sub": r[2], "state": r[3],
            "lastCheck": r[4], "health": r[5], "selfManaged": bool(r[6]),
        } for r in rows]
        return out

    @app.post("/api/automations/draft")
    def draft_automation(req: AutomationDraftReq, request: Request):
        """Plain-English (or uploaded-doc) -> draft automation, for the
        Automations screen's "Describe it" and "Upload a doc" cells. Dispatches
        through the same configured-model executor /api/chat uses (the setup
        wizard's cloud key), then strictly validates the JSON server-side.

        Governor philosophy: this endpoint DRAFTS ONLY. It never writes the
        automations table and never returns a running automation — the caller
        reviews the draft and confirms via the ordinary PUT /api/automations/:id
        approve path (state awaiting_approval, needs_signoff), exactly like a
        wizard pick or a hand-drawn graph. A malformed model answer is a 502,
        not a silently-shaped guess."""
        _require_token(request, token)
        if not req.description.strip():
            raise HTTPException(400, "description is required")
        route = select_route(prefer="cloud")
        prompt = build_draft_prompt(req.description, req.source_text, req.source_name)
        result = engine.executor.run(prompt, model=route.model, provider=route.provider)
        record = RunRecord.new(
            task="automation-draft", exit_code=result.exit_code, flags="source:api/automations/draft",
            output=result.output, model=result.model, provider=result.provider,
            fallback_used=result.fallback_used, tokens_in=result.tokens_in,
            tokens_out=result.tokens_out, cost_usd=result.cost_usd,
            duration_ms=result.duration_ms,
        )
        engine.ledger.append(record)
        engine._record_metering(record)
        if result.exit_code != 0:
            raise HTTPException(502, result.stderr or result.output or "draft dispatch failed")
        try:
            draft = parse_automation_draft(result.output)
        except ValueError as e:
            raise HTTPException(502, f"Model did not return a valid automation draft: {e}") from e
        # Draft stays pending review: needsSignoff is forced on and no state
        # field is ever returned as 'running' — activation only happens later
        # through PUT /api/automations/:id after explicit human confirmation.
        return {**draft, "needsSignoff": True, "state": "awaiting_approval", "author": "agent"}

    @app.put("/api/systems/{system_id}")
    def put_system(system_id: str, req: dict, request: Request):
        _require_token(request, token)
        conn = open_isolation_db(data_dir)
        try:
            conn.execute(
                "INSERT INTO systems(id, name, sub, state, last_check, health, self_managed, ts) "
                "VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, sub=excluded.sub, "
                "state=excluded.state, last_check=excluded.last_check, health=excluded.health, "
                "self_managed=excluded.self_managed, ts=excluded.ts",
                (system_id, req.get("name", system_id), req.get("sub"), req.get("state"),
                 req.get("lastCheck") or _now_iso(), req.get("health", "ok"),
                 int(bool(req.get("selfManaged", False))), _now_iso()))
            conn.commit()
        finally:
            conn.close()
        return {"id": system_id, "status": "saved"}

    @app.get("/api/agent/worklog")
    def agent_worklog():
        """{ ongoing, done } — derived from live engine state and today's
        ledger (README, Data Contracts). This is the one route the README
        singles out as making Anton's self-initiative visible."""
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        done = []
        for row in engine.ledger.read():
            if not row.get("ts", "").startswith(today):
                continue
            if row.get("task") == "fleet-canary":
                continue
            meta = row["ts"][11:16] if len(row.get("ts", "")) >= 16 else row.get("ts", "")
            status = "ok" if row.get("exit") == 0 else f"exit {row.get('exit')}"
            done.append({"text": f"{row.get('task')} ({status})", "meta": meta})
        due = engine.due_jobs()
        ongoing = [{"text": f"Waiting on the next window for {j.id}", "meta": "scheduled", "pct": None}
                   for j in due]
        return {"ongoing": ongoing, "done": list(reversed(done))[:20]}

    @app.get("/api/learning")
    def learning_entries():
        """Entry[] — backed by the existing `playbooks` table (learning.py's
        extract_playbook already writes slug/method/source_initiative; the
        Ops Center columns are additive, see ops_schema.py)."""
        conn = open_isolation_db(data_dir)
        try:
            rows = conn.execute(
                "SELECT slug, title, body, method, kind, triggered_by, source_initiative, "
                "usage_count, vault_path, ts FROM playbooks ORDER BY ts DESC LIMIT 50").fetchall()
        finally:
            conn.close()
        out = []
        for slug, title, body, method, kind, triggered_by, source_initiative, usage_count, vault_path, ts in rows:
            out.append({
                "kind": kind or "decision",
                "when": ts or _now_iso(),
                "title": title or slug.replace("-", " ").title(),
                "body": body or method or "",
                "triggeredBy": triggered_by or source_initiative or "",
                "usage": usage_count or 0,
                "vaultPath": vault_path,
            })
        return out

    @app.get("/api/incidents")
    def list_incidents():
        """Incident[] — the story: Anton caught it, worked out why, wrote it
        up, drafted a fix, and stopped at the gate (README §10). Backed by a
        real `incidents`/`incident_events` pair, not fabricated demo rows."""
        conn = open_isolation_db(data_dir)
        try:
            rows = conn.execute(
                "SELECT id, title, summary, status, window_start, window_end "
                "FROM incidents ORDER BY ts DESC LIMIT 50").fetchall()
            out = []
            for iid, title, summary, status, wstart, wend in rows:
                events = conn.execute(
                    "SELECT time, text, actor FROM incident_events WHERE incident_id=? ORDER BY id ASC",
                    (iid,)).fetchall()
                out.append({
                    "id": iid, "title": title, "summary": summary, "status": status,
                    "window": f"{wstart}–{wend}" if wend else (wstart or ""),
                    "events": [{"time": t, "text": tx, "actor": a} for t, tx, a in events],
                })
        finally:
            conn.close()
        return out

    @app.put("/api/automations/{automation_id}")
    def put_automation(automation_id: str, req: AutomationUpdate, request: Request):
        """Commit the full node graph on approve (README, Data Contracts).
        Anton drafted it, so Anton owns persistence — this is the only place
        automation.nodes/.links become durable, matching the State
        Management table's note that the draft "must survive navigating away
        and back before approval." Persisted server-side, not in browser
        storage."""
        _require_token(request, token)
        conn = open_isolation_db(data_dir)
        try:
            row = conn.execute("SELECT id FROM automations WHERE id=?", (automation_id,)).fetchone()
            nodes_json = json.dumps([n.model_dump() for n in req.nodes])
            links_json = json.dumps(req.links)
            now = _now_iso()
            if row is None:
                conn.execute(
                    "INSERT INTO automations(id, name, plain, nodes_json, links_json, state, ts) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (automation_id, req.name or automation_id, req.plain, nodes_json, links_json,
                     req.state or "awaiting_approval", now))
            else:
                sets = ["nodes_json=?", "links_json=?", "ts=?"]
                params: list = [nodes_json, links_json, now]
                if req.name is not None:
                    sets.append("name=?")
                    params.append(req.name)
                if req.plain is not None:
                    sets.append("plain=?")
                    params.append(req.plain)
                if req.state is not None:
                    sets.append("state=?")
                    params.append(req.state)
                params.append(automation_id)
                conn.execute(f"UPDATE automations SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
        finally:
            conn.close()
        return {"id": automation_id, "status": "saved"}

    @app.post("/api/setup")
    def submit_wizard(req: WizardPicksReq, request: Request):
        """Record the first-run wizard's picks (README §11: "Pick the work ->
        Connect it -> Set the leash -> Review the plan"). Distinct from the
        CLI's `anton setup` install provisioning (setup.py) — this is a
        product onboarding flow, not directory bootstrapping."""
        _require_token(request, token)
        conn = open_isolation_db(data_dir)
        try:
            conn.execute(
                "INSERT INTO wizard_submissions(picks_json, ts) VALUES(?,?)",
                (json.dumps({"step": req.step, "picks": req.picks}), _now_iso()))
            conn.commit()
        finally:
            conn.close()
        return {"status": "recorded", "picks": len(req.picks)}
