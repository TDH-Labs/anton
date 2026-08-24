"""Shared defaults: config skeleton + default jobs (used by cli, setup, installer)."""

# Only webhook-triggered jobs are seeded on fresh installs. The old seeds
# (e2e-canary, hourly "daily-digest") were broken by construction: their
# recipes were passed verbatim as LLM prompts routed local-first, so on any
# install without a reachable Ollama they recorded exit-1 failures at cron
# cadence (~120/day) while doing nothing. Health monitoring already runs
# in-process every poll tick via JobEngine.run_canary(); digest generation
# belongs behind explicit provider configuration (`anton digest`).
DEFAULT_JOBS_YAML = """- id: smoke-hook
  trigger: { type: webhook }
  recipe: smoke-hook
  expected_cadence_min: 0
"""

DEFAULT_CONFIG_YAML = """general:
  data_dir: data
  host: 0.0.0.0
  port: 8799
  executor: pi            # fake | pi | oi | ssh
  pi_tools: "read,grep,find,ls"  # read-only by default; see executor/pi_executor.py
  dashboard_token: ""      # set before exposing the dashboard port (bearer on writes)
  poll_seconds: 15
  org_id: default
routes:
  local_model: ollama/llama3.1:8b
  cloud_model: openrouter/anthropic/claude-3.5-sonnet
  prefer: local
budgets:
  tokens_max_per_job: 120000
  cost_usd_max_per_job: 0.20
  daily_tokens_max: 1000000
  daily_cost_usd_max: 5.0
jobs_file: jobs.yaml
"""
