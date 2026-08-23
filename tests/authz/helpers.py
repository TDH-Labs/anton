"""Shared fixtures for the adversarial authZ CI suite.

Written FIRST per HANDOFF #10 — the suite encodes the frozen spec
(docs/AUTHZ-SPEC.md v1.1) before any implementation exists. Each test
module maps 1:1 to CI-T-* ids named in the spec.
"""
from __future__ import annotations

import json
import os
import tempfile

from fastapi.testclient import TestClient

from anton.config import load_config
from anton.dashboard import create_app
from anton.db import init_db
from anton.executor import FakeExecutor
from anton.jobs import load_jobs
from anton.ledger import Ledger
from anton.scheduler import JobEngine

JOBS = """
- id: e2e-canary
  trigger: { type: cron, expr: "*/5 * * * *" }
  recipe: canary
"""


class Env:
    def __init__(self, tmpdir: str, client: TestClient):
        self.dir = tmpdir
        self.client = client

    # -- file paths ------------------------------------------------------
    @property
    def data_dir(self) -> str:
        return os.path.join(self.dir, "data")

    @property
    def authz_db(self) -> str:
        return os.path.join(self.data_dir, "authz.db")

    @property
    def isolation_db(self) -> str:
        return os.path.join(self.data_dir, "isolation.db")

    # -- identity helpers -------------------------------------------------
    def owner_claim(self) -> str:
        path = os.path.join(self.data_dir, "authz", "owner-claim")
        with open(path, encoding="utf-8") as f:
            return f.read().strip()

    def bootstrap_owner(self, username="owner", password="Owner-Pass-1!"):
        r = self.client.post("/api/auth/bootstrap", json={
            "username": username, "password": password,
            "claim": self.owner_claim()})
        assert r.status_code == 200, r.text
        return r.json()

    def login(self, username, password) -> dict:
        r = self.client.post("/api/auth/login",
                             json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def headers_for(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}


def build_env(authz_enabled=True, mode="multi_user", extra_authz=None) -> Env:
    tmpdir = tempfile.mkdtemp(prefix="authz-suite-")
    data_dir = os.path.join(tmpdir, "data")
    os.makedirs(data_dir, exist_ok=True)
    jobs_path = os.path.join(tmpdir, "jobs.yaml")
    with open(jobs_path, "w", encoding="utf-8") as f:
        f.write(JOBS)

    init_db(os.path.join(data_dir, "isolation.db"))
    ledger = Ledger(os.path.join(tmpdir, "runs.jsonl"))
    engine = JobEngine(load_jobs(jobs_path), ledger, FakeExecutor(), load_config())

    cfg = load_config()
    # NB: deep_merge is a shallow copy — cfg["general"] IS config.DEFAULTS
    # ["general"]. Never mutate nested dicts in place or the token leaks
    # into every other app built in the same process.
    cfg["general"] = dict(cfg.get("general") or {})
    cfg["general"]["dashboard_token"] = "s3cret-legacy"
    az = {"enabled": authz_enabled, "mode": mode}
    if extra_authz:
        az.update(extra_authz)
    cfg["authz"] = az

    app = create_app(engine, data_dir, cfg)
    env = Env(tmpdir, TestClient(app))
    env.engine = engine
    env.cfg = cfg
    env.app = app
    return env


def raw_sqlite(db_path: str, sql: str, params=()):
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()
