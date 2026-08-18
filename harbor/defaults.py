"""Shared defaults: config skeleton + default jobs (used by cli, setup, installer)."""

DEFAULT_JOBS_YAML = """- id: e2e-canary
  trigger: { type: cron, expr: "*/15 * * * *" }
  recipe: e2e-canary
  expected_cadence_min: 15
- id: control-plane-digest
  trigger: { type: cron, expr: "0 * * * *" }
  recipe: control-plane-digest
  expected_cadence_min: 60
- id: smoke-hook
  trigger: { type: webhook }
  recipe: smoke-hook
  expected_cadence_min: 0
"""

DEFAULT_CONFIG_YAML = """general:
  data_dir: data
  host: 0.0.0.0
  port: 8799
  executor: fake          # fake | pi | oi | ssh
  dashboard_token: ""      # set before exposing the dashboard port (bearer on writes)
  poll_seconds: 15
  org_id: default
routes:
  local_model: [REDACTED-LOCAL-MODEL]
  cloud_model: openrouter/anthropic/claude-3.5-sonnet
  prefer: local
budgets:
  tokens_max_per_job: 120000
  cost_usd_max_per_job: 0.20
  daily_tokens_max: 1000000
  daily_cost_usd_max: 5.0
jobs_file: jobs.yaml
"""
