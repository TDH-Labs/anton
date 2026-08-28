# anton — turnkey image: docker/auth-gate.mjs (Node, port 3080, the
# container's only published port) is a password-gated reverse proxy in
# front of the anton-studio web UI, which stays loopback-only by its own
# design (dsh web refuses --host 0.0.0.0 — no auth/TLS on that surface).
# The anton Python API (dashboard on 8799, scheduler on 8798)
# stays container-internal too — apiproxy's Node half talks to dashboard
# over localhost:8799 in-container, see packages/host/apiproxy/src/index.ts.

# ---- stage 1: build the anton-studio Node frontend/host -------------------
FROM node:22-slim AS node-build

# scripts/build.ts shells out to `git rev-parse HEAD` to stamp the build
# revision (DSH_CLIENT_COMMIT_HASH, shown in the sidebar footer). The
# vendored anton-studio/ copied in below has no .git of its own to rev-parse
# against -- installing git doesn't fix that, only bypassing the shell-out
# does, via the ARG/ENV pair below.
RUN corepack enable
ENV CI=true

WORKDIR /src
COPY anton-studio/ /src/
ARG DSH_CLIENT_COMMIT_HASH=d7d80f9
ENV DSH_CLIENT_COMMIT_HASH=${DSH_CLIENT_COMMIT_HASH}

# Anton is a white-labeled build of the vendored DeepSeek Harness frontend --
# without these, the browser tab title falls back to "DSH Local Build" (its
# hardcoded default; DocumentTitle.tsx) and the first-run onboarding modal
# pushes signing up for DeepSeek's own hosted API by name
# (DeepSeekOnboardingDialog.tsx). Both are DSH_CLIENT_* build-time values,
# inlined by the bundler the same way DSH_CLIENT_COMMIT_HASH is above --
# see scripts/client-build-environment.ts.
ENV DSH_CLIENT_TITLE=Anton
ENV DSH_CLIENT_OFFICIAL_ONBOARDING=false

RUN pnpm install --frozen-lockfile
RUN pnpm run build
# Not pruned to production-only or `pnpm deploy`-isolated: apps/cli's `web`
# profile boots its plugin roster at runtime by package name (cordis Loader
# reading packages/bundle/web-app/cordis.patch.yml), not through apps/cli's
# own static imports, so the actual runtime package closure isn't fully
# reachable from apps/cli's declared dependency graph. Both prune --prod and
# pnpm deploy resolve statically and silently dropped real runtime deps
# (dsh-jobs-local -> dsh-scope, and others past it) as a result. Shipping
# the full dev install is the correct closure; it costs image size, not
# correctness.

# ---- stage 2: runtime (python backend + node web UI) ----------------
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

# Run as a non-root user: the agent executes job recipes and (with oi/opencode
# executors) arbitrary code — root amplifies any escape. /data is chowned so
# the named volume stays writable; entrypoint.sh needs no privileged ops.
RUN useradd -m -u 10001 anton \
    && chown -R anton:anton /app /data
USER anton

# Built Node app (source, lib/, apps/web/dist, and node_modules) replaces
# the raw source .dockerignore let through.
RUN rm -rf /app/anton-studio
COPY --from=node-build /src /app/anton-studio

# Hits the dashboard's real /health ({"ok": true, "jobs": N}) on its
# container-internal port, not the auth-gate's public :3080/ -- that only
# proves a login page renders, not that the job engine is actually up. curl
# is already installed above for the pi/dsh install steps.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8799/health || exit 1

# entrypoint.sh runs `anton serve` (background), `anton dashboard`
# (background), and `dsh web` (foreground, the primary process) itself;
# there is no CMD to pass through.
ENTRYPOINT ["/app/entrypoint.sh"]

EXPOSE 3080
VOLUME ["/data"]
