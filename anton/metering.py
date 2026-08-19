"""Usage metering: canonical cloud-usage records for billing/budget (Q2, §15)."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from typing import Optional

from .models import RunRecord

TABLE = """
CREATE TABLE IF NOT EXISTS metering (
    id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT DEFAULT 'default',
    ts TEXT, provider TEXT, model TEXT, tokens_in INTEGER, tokens_out INTEGER,
    cost_usd REAL, job_id TEXT
)
"""


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(TABLE)
    conn.commit()
    return conn


def record(conn: sqlite3.Connection, record: RunRecord, job_id: Optional[str] = None) -> None:
    """Record cloud usage only; local runs are deliberately unmetered (Q1)."""
    if record.token_accounting != "cloud":
        return
    conn.execute(
        "INSERT INTO metering(org_id, ts, provider, model, tokens_in, tokens_out, cost_usd, job_id) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (record.org_id, record.ts, record.provider, record.model,
         record.tokens_in, record.tokens_out, record.cost_usd, job_id or record.task),
    )
    conn.commit()


def daily_totals(conn: sqlite3.Connection, org_id: str = "default") -> dict:
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0), "
        "COALESCE(SUM(cost_usd),0.0), COUNT(*) FROM metering "
        "WHERE org_id=? AND ts LIKE ?",
        (org_id, day + "%"),
    ).fetchone()
    return {"tokens_in": row[0], "tokens_out": row[1],
            "cost_usd": round(row[2], 6), "runs": row[3]}


def lifetime_totals(conn: sqlite3.Connection, org_id: str = "default") -> dict:
    row = conn.execute(
        "SELECT COALESCE(SUM(tokens_in),0), COALESCE(SUM(tokens_out),0), "
        "COALESCE(SUM(cost_usd),0.0), COUNT(*) FROM metering WHERE org_id=?",
        (org_id,),
    ).fetchone()
    return {"tokens_in": row[0], "tokens_out": row[1],
            "cost_usd": round(row[2], 6), "runs": row[3]}
