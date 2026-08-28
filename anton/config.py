"""config.yaml loading with defaults. YAML (not TOML) for uniformity with jobs.yaml."""
from __future__ import annotations

import copy
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
    "n8n": {
        # The operator's own n8n instance -- editing an n8n-backed
        # automation's actual workflow happens there, not in a competing
        # in-app canvas (see dashboard.py's /api/n8n/config and
        # AutomationsScreen.tsx's "Draw it" tile). Empty by default: n8n is
        # optional infrastructure, not something every install needs.
        "base_url": "",
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    """Merge `override` onto `base`, returning a result that shares no nested
    container with `base`.

    The deep copy is load-bearing, not defensive: `load_config()` merges onto
    the module-level DEFAULTS, and a shallow `dict(base)` left every nested
    section (`general`, `routes`, `budgets`, `n8n`) aliased to the DEFAULTS
    object itself. Any caller mutating a section in place -- the n8n config
    write, `apply_bridge_credential_overrides`, a test setting a dashboard
    token -- silently rewrote the defaults for every later `load_config()` in
    the same process.
    """
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# Deployment-level bridge credentials for the hosted-OAuth connections
# catalog (Composio / Nango). Precedence, most specific wins:
#   1. config.yaml bridges: section  -- operator set it deliberately
#   2. pasted secrets (data-dir secrets.yaml composio_api_key /
#      nango_secret_key, written by POST /api/integrations/bridges/configure)
#   3. environment (ANTON_COMPOSIO_API_KEY / ANTON_NANGO_SECRET_KEY) --
#      headless VPS deploys
# Keys NEVER go into git or any committed file; secrets.yaml is 0600 inside
# the data volume, env vars live only in the process.
BRIDGE_ENV_VARS = {
    "composio": {"key": "api_key", "env": "ANTON_COMPOSIO_API_KEY",
                 "secret_name": "composio_api_key",
                 "url_env": "ANTON_COMPOSIO_BASE_URL", "url_field": "base_url"},
    "nango": {"key": "secret_key", "env": "ANTON_NANGO_SECRET_KEY",
              "secret_name": "nango_secret_key",
              "url_env": "ANTON_NANGO_HOST", "url_field": "host"},
}


def apply_bridge_credential_overrides(config: dict, data_dir: str | None) -> dict:
    """Fill config['bridges'] from pasted secrets + env without ever logging
    or echoing a key. Called once per process after load_config; mutates and
    returns `config`. Missing sources are simply skipped (a bridge stays
    unconfigured rather than half-configured with an empty string)."""
    import yaml
    bridges = config.setdefault("bridges", {})
    pasted: dict = {}
    if data_dir:
        for path in (os.path.join(data_dir, "secrets.yaml"),
                     os.path.join(os.path.dirname(data_dir), "secrets.yaml")):
            try:
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        raw = yaml.safe_load(f) or {}
                    pasted.update(raw)  # later (preferred location) wins
            except OSError:
                continue
    for bridge, spec in BRIDGE_ENV_VARS.items():
        entry = dict(bridges.get(bridge) or {})
        if not entry.get(spec["key"]):
            value = pasted.get(spec["secret_name"])
            if not value:
                value = os.environ.get(spec["env"])
            if value:
                entry[spec["key"]] = value
        if not entry.get(spec["url_field"]):
            url = os.environ.get(spec["url_env"])
            if url:
                entry[spec["url_field"]] = url
        if entry:
            bridges[bridge] = entry
    return config


def load_config(path: Optional[str] = None) -> dict:
    cfg = deep_merge(DEFAULTS, {})
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = deep_merge(cfg, yaml.safe_load(f) or {})
    return cfg
