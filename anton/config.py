"""config.yaml loading with defaults. YAML (not TOML) for uniformity with jobs.yaml."""
from __future__ import annotations

import dataclasses
import os
from typing import Optional

import yaml

DEFAULTS = {
    "general": {
        "data_dir": ".dev-data",
        "host": "0.0.0.0",
        "port": 8799,
        "executor": "pi",  # fake | pi | oi | ssh
        # Tool allowlist passed to PiExecutor's `pi --tools <value>` invocation
        # (see executor/pi_executor.py). Read-only by default: nothing upstream
        # of PiExecutor restricts what a dispatched task can do, so widening
        # this to include edit/write/bash is a deliberate, informed choice for
        # deployments that need it, not a default.
        "pi_tools": "read,grep,find,ls",
        "poll_seconds": 15,
        "org_id": "default",
        # How often the proactive opportunity scanner (opportunity.py)
        # surveys connected sources (vault + mcp_servers) for things worth
        # upskilling toward before anything breaks. Real dispatch cost, so
        # this is hours, not the poll_seconds cadence.
        "opportunity_scan_hours": 24,
    },
    "routes": {
        "local_model": "ollama/llama3.1:8b",
        "cloud_model": "openrouter/anthropic/claude-3.5-sonnet",
        "prefer": "local",
    },
    "budgets": {
        "tokens_max_per_job": 120000,
        "cost_usd_max_per_job": 0.20,
        "daily_tokens_max": 1000000,
        "daily_cost_usd_max": 5.0,
    },
    "jobs_file": "jobs.yaml",
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Optional[str] = None) -> dict:
    cfg = deep_merge(DEFAULTS, {})
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = deep_merge(cfg, yaml.safe_load(f) or {})
    return cfg
