"""Anton Studio Ops Center API — the endpoints the design handoff's Data
Contracts section documents and dashboard.py did not previously serve:
`/api/systems`, `/api/agent/worklog`, `/api/incidents`,
`PUT /api/automations/:id`, and `POST /api/setup` (wizard picks). Registered
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
from .ops_schema import ensure_ops_schema
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
