# anton — turnkey image. docker/auth-gate.mjs (Node, port 3080) is the
# container's only published port: a password-gated reverse proxy in front of
# `anton dashboard`, which serves both the /api surface and Anton's own Ops
# Center UI. The Python processes (dashboard 8799, scheduler 8798) stay bound
# to container loopback.

# ---- stage 1: build Anton's own web UI ------------------------------------
# A single Vite app (anton/web), not a plugin monorepo: ~39 packages and a
# sub-second bundle. Node is needed only here and for the runtime's auth-gate
# and agent CLIs below.
FROM node:22-slim AS web-build
WORKDIR /web
COPY anton/web/package.json anton/web/package-lock.json* /web/
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund
COPY anton/web/ /web/
RUN npm run build

# ---- stage 2: runtime -----------------------------------------------------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-client curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# The default executor (anton/config.py) — real, tool-restricted execution,
# not the fake mock. Publicly published on the npm registry, MIT licensed
# (NOTICE), no private credentials needed to install it. Pinned, not
# `npm install -g @earendil-works/pi-coding-agent` unversioned: that would
# silently pick up whatever's newest on every rebuild, including breaking
# CLI-flag changes this image was never tested against. Bump deliberately —
# test against the new version, then move this pin — not automatically.
RUN npm install -g @earendil-works/pi-coding-agent@0.84.2

# Stored-login Add-ons connections (the "sign in like a person would"
# fallback for a site with no OAuth/MCP/API): browser_login.py drives a real,
# persistent Chromium session directly (never through an LLM -- the password
# is typed by Anton's own scripted code, not an agent). Real cost, stated
# plainly: the browser binary below adds roughly 300-400MB and real build
# time. Pinned exactly, matching pi's own deliberate-bump discipline above --
# the Python `playwright` package (pyproject.toml) and this Chromium install
# must move together.
RUN npm install -g @playwright/mcp@0.0.79

# opencode is the executor a job uses when it needs browser tools on an
# already-authenticated stored-login session (Job.executor = {name: opencode,
# mcp_profile: <service_id>}, anton/scheduler.py's per-job executor
# resolution -- pi has no MCP support at all, so it can't drive
# @playwright/mcp the way opencode can). Standard AI provider keys the setup
# wizard already saves (ANTHROPIC_API_KEY etc., loaded into this process's
# environment by cli.py's _load_secrets_into_env) reach opencode for free --
# no separate credential step needed for it specifically.
RUN npm install -g opencode-ai@1.18.19

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
# Browsers must live somewhere the runtime user can read: pin the path so
# root's install step and anton's runtime lookup agree (default ~/.cache is
# per-user and would 404 after the USER switch below).
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN python3 -m playwright install --with-deps chromium
ENV PLAYWRIGHT_LAUNCH_OPTIONS='{"chromiumSandbox": false}'
RUN mkdir -p /data

# The built UI, served by dashboard.py's StaticFiles mount. `pip install .`
# above copied the anton package into site-packages, so the module that runs
# is NOT /app/anton -- point it explicitly at the artifact rather than
# relying on a module-relative guess.
COPY --from=web-build /web/dist /app/anton/web/dist
ENV ANTON_WEB_DIST=/app/anton/web/dist

# Run as a non-root user: the agent executes job recipes and (with oi/opencode
# executors) arbitrary code — root amplifies any escape. /data is chowned so
# the named volume stays writable; entrypoint.sh needs no privileged ops.
RUN useradd -m -u 10001 anton \
    && chown -R anton:anton /app /data
USER anton

# Hits the dashboard's real /health ({"ok": true, "jobs": N}) on its
# container-internal port, not the auth-gate's public :3080/ -- that only
# proves a login page renders, not that the job engine is actually up. curl
# is already installed above for the agent-CLI install steps.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8799/health || exit 1

# entrypoint.sh runs `anton serve` and `anton dashboard` in the background and
# the auth-gate as the primary process; there is no CMD to pass through.
ENTRYPOINT ["/app/entrypoint.sh"]

EXPOSE 3080
VOLUME ["/data"]
