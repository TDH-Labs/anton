# Harbor SAS — VM / Deployment Runbook

Purpose: take the repo from "built" to "deployed" on a clean box — VM first, then a real
Umbrel server. **Run these on the VM / Umbrel, never on the reference Mac.** The Mac is
the case study; its fleet is untouched.

---

## Phase 0 — Get the code onto the VM

Option A (preferred): push the repo, clone on the VM.

```bash
# on the Mac (or wherever you keep it):
cd ~/harbor-sas
git remote add origin <your-repo-url>   # e.g. https://github.com/you/harbor-sas.git
git push -u origin main
```

```bash
# on the VM (Ubuntu 22/24 recommended):
sudo apt-get update && sudo apt-get install -y git python3 python3-venv curl
git clone <your-repo-url> harbor-sas && cd harbor-sas
```

Option B (no remote yet): `rsync -az ~/harbor-sas/ vm:/opt/harbor-sas/` (exclude `.venv`, `.dev-data`).

Prereqs on the VM: `python3 --version` (≥ 3.11), Docker (Phase 3+), bun (Phase 2).

---

## Phase 1 — Host install smoke test

```bash
cd harbor-sas
bash install.sh                      # installs into $HOME/.harbor
$HOME/.harbor/venv/bin/harbor doctor --data-dir $HOME/.harbor/data
$HOME/.harbor/venv/bin/harbor serve  --data-dir $HOME/.harbor/data --executor fake --port 8799 &
sleep 3
curl -s http://127.0.0.1:8799/health                  # {"ok": true, ...}
curl -s -X POST http://127.0.0.1:8799/hooks/smoke-hook # exit 0 (webhook-triggered default job)
$HOME/.harbor/venv/bin/harbor canary --data-dir $HOME/.harbor/data   # PASS after the run
$HOME/.harbor/venv/bin/harbor digest --data-dir $HOME/.harbor/data
kill %1
```

**Pass =** doctor all ✓, health ok, webhook run recorded, canary PASS, digest generated.

---

## Phase 2 — Executor integration (the "fake → real" swap, item #1–3)

### 2a. pi executor

```bash
curl -fsSL https://bun.com/install | bash            # installs ~/.bun
export PATH="$HOME/.bun/bin:$PATH"
bun install -g @earendil-works/pi-coding-agent@0.84.2   # pin the Mac's version
pi --version                                          # 0.84.2
```

Provider: export your key (e.g. `export OPENROUTER_API_KEY=sk-or-…`) so pi can route.

```bash
cd harbor-sas
.venv/bin/harbor run --task "reply with exactly: OK" --recipe pi-smoke \
  --executor pi --route cloud --data-dir /tmp/pi-smoke-data
cat /tmp/pi-smoke-data/runs.jsonl      # expect: provider=openrouter, exit 0
```

**Verify metering actually captures** (the current gap): after a cloud run, `harbor usage`
should show tokens/cost > 0. If `tokens_in` is null, the pi CLI isn't exposing usage —
that's the known capture gap (see README "placeholders"); decide: accept nulls, or wire
the provider-API usage wrapper.

### 2b. OI executor

Install the standalone OI CLI matching the Mac's (release layout
`<ver>-<arch>-<os>`; pick the linux artifact for the VM from the
openinterpreter/open-interpreter GitHub releases, v0.0.34):

```bash
# example (adapt arch/url to the release you download):
mkdir -p ~/.openinterpreter && tar -xzf interpreter-0.0.34-x86_64-unknown-linux-gnu.tar.gz -C ~/.openinterpreter
export PATH="$HOME/.openinterpreter/bin:$PATH"
interpreter --version                                   # 0.0.34
```

Auth: same as the Mac — `INTERPRETER_HOME=~/.openinterpreter` with a config.toml routing
to your provider + the key exported.

```bash
.venv/bin/harbor run --task "reply with exactly: OK" --recipe oi-smoke \
  --executor oi --route cloud --data-dir /tmp/oi-smoke-data
cat /tmp/oi-smoke-data/runs.jsonl      # expect: model/provider populated
```

### 2c. Smoke verdicts

| Check | Pass = |
| --- | --- |
| pi run | exit 0, provider=openrouter, ledger row complete |
| oi run | exit 0, `-o` output captured, usage parsed if available |
| metering | `harbor usage` shows nonzero tokens/cost for a cloud run (or document nulls) |
| canary | PASS after runs; ATTENTION if you stop a job |

---

## Phase 3 — Container build + run

```bash
cd harbor-sas
docker build -t harbor-sas:latest .
docker compose -f umbrel/harbor-sas/docker-compose.yml config   # validate first

docker run -d --name harbor-sas-test -p 8799:8799 \
  -e HARBOR_EXECUTOR=fake \
  -e HARBOR_DASHBOARD_TOKEN=change-me \
  -v harbor_test_data:/data harbor-sas:latest

sleep 5
curl -s http://127.0.0.1:8799/health          # {"ok": true}  (serve: health + webhooks only)

# NOTE (clean-box fix 2026-08-18): /api/ledger and /api/approvals live on the
# SEPARATE dashboard server, not serve. Launch it too — WITH the token set:
docker exec -d harbor-sas-test bash -lc 'HARBOR_DASHBOARD_TOKEN=change-me \
  /app/venv/bin/harbor dashboard --data-dir /data --port 8800'
sleep 4
curl -s http://127.0.0.1:8800/api/ledger
curl -s -X POST http://127.0.0.1:8800/api/approvals \
  -H "Authorization: Bearer change-me" \
  -H "Content-Type: application/json" -d '{"action":"test"}'    # 200 with token
# without the token (correct env) -> 401
docker rm -f harbor-sas-test
```

**SSH executor in the container** (the Umbrel→host pattern):

```bash
docker run -d --name harbor-sas-ssh -p 8799:8799 \
  -e HARBOR_EXECUTOR=ssh \
  -e HARBOR_SSH_HOST=<host-that-runs-recipes> \
  -e HARBOR_SSH_USER=<user> \
  -e HARBOR_SSH_KEY="$(cat ~/.ssh/id_ed25519)" \
  -e HARBOR_SSH_COMMAND="bash -lc 'export PATH=\$HOME/.local/bin:\$PATH; run-local-recipe.sh <recipe>'" \
  -v harbor_test_data:/data harbor-sas:latest
# then POST a webhook job and confirm the host executed it
```

---

## Phase 4 — Umbrel app install

1. **Push the image** to a registry (multi-arch for Pi/ARM boxes):

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/<you>/harbor-sas:0.1.0 --push .
```

2. Point the compose at it:

```yaml
# umbrel/harbor-sas/docker-compose.yml
image: ghcr.io/<you>/harbor-sas:0.1.0
```

3. Install on Umbrel — easiest supported path: put `umbrel/harbor-sas/` in its own GitHub
   repo, then in the Umbrel App Store use **"Install from repo"** with that URL
   (developer option). Alternative: copy the app directory to the umbrelOS apps path on
   the server.

4. Set env at install (or in the app's settings): `HARBOR_DASHBOARD_TOKEN`,
   `HARBOR_EXECUTOR=ssh`, `HARBOR_SSH_*`.

5. Verify on the Umbrel box:

```bash
curl -s http://127.0.0.1:8799/health
curl -s -X POST http://127.0.0.1:8799/hooks/<job-id> -d '{}'
# dashboard at http://<umbrel-ip>:8799  (writes require the bearer token)
```

---

## Phase 5 — Pre-deployment checklist (fake → real)

- [ ] Executor: `HARBOR_EXECUTOR` is `pi`, `oi`, or `ssh` — **not** `fake`
- [ ] pi/OI executors integration-tested (Phase 2) — exit codes + ledger fields
- [ ] Metering: cloud run produces nonzero `tokens_in`/`cost_usd` in `harbor usage`,
      or the null-capture decision is documented
- [ ] `HARBOR_DASHBOARD_TOKEN` set; port 8799 never exposed without it
- [ ] Default jobs replaced with real recipes (the `control-plane-digest` job actually
      runs `harbor digest`)
- [ ] Approval model decision made (table-status OK for single-user; HMAC signing before
      multi-user)
- [ ] Sandbox gate: golden tests exist for every promoted skill
- [ ] Auto-start: launchd (Mac host) / systemd (Linux host) templates filled in — or the
      Umbrel app's `restart: unless-stopped` covers it
- [ ] Backup: `/data` (or `$HARBOR_HOME`) contains the whole state — back it up before
      upgrades; rollback = restore the volume

---

## Security notes

- Dashboard binds `127.0.0.1` by default; on Umbrel the port map exposes it — token or
  firewall.
- SSH executor: use a dedicated key; the command template is the trust boundary.
- Secrets: provider keys live in `secrets.yaml` (600) inside the install dir / volume.

## Rollback

- Host: delete `$HARBOR_HOME` → clean reinstall.
- Container: `docker compose down -v` (drops the volume) → redeploy.
- Umbrel: uninstall the app (keeps the volume unless removed) → reinstall from repo.

---

## CLEAN-BOX PROOF RESULTS (2026-08-18, option B)

Executed Phase 0–3 on a disposable Ubuntu 22.04 container + Mac-host Docker build.

### Verified works
- Install → doctor (all ✓ under py3.11), serve, health, cron-triggered canary, digest
- Container build + run, dashboard server (/api/ledger, /api/usage, /api/approvals)
- Approvals auth (401/401/200) **when HARBOR_DASHBOARD_TOKEN is set**

### Findings (runbook/doc corrections — not code bugs)
1. **Python prereq is real:** repo requires ≥3.11; Ubuntu 22.04 defaults to 3.10.
   install.sh does not recover from a stale mismatched `$HOME/.harbor` venv (must `rm -rf`
   it first). Add a prereq/preflight + venv-rebuild note.
2. **BIND BUG:** `harbor serve` binds 127.0.0.1 → inside a container the `-p 8799:8799`
   map is unreachable from the host. Serve must bind 0.0.0.0 (or a flag) for container use.
3. **RUNBOOK BUG — wrong server in Phase 1/3:** `/api/ledger` and `/api/approvals` live on
   the *dashboard* server, not the *serve* server. Phase 1 `curl .../api/ledger` on 8799
   (serve) returns 404. Correct: start dashboard (separate port) for those.
4. **RUNBOOK BUG — webhook job:** `POST /hooks/<id>` only accepts `trigger.type=="webhook"`
   jobs, but defaults/jobs.yaml has only cron triggers → smoke POST 404s. Add a webhook-triggered
   default job or note it.
5. **RUNBOOK GAP — dashboard token:** Phase 3 says "without token → 401" but launches the
   dashboard without setting HARBOR_DASHBOARD_TOKEN, so nothing is enforced. Auth works when
   the env var is set (verified 401/401/200). Fix the runbook command to set it.

### Option-B harvest into the LIVE engine (2026-08-18)
The runbook proof surfaced that harbor-sas's metering is a stub (pi executor
admits tokens stay None). The live engine now captures REAL metering by reading
pi's session usage: `~/.buzz/skills/initiative-engine/meter.py` (cloud-only rows
in isolation.db `metering` table), wired into `run-local-recipe.sh` after cloud
fallback + surfaced as a "Cloud usage" card on the live dashboard.
Verified: captures pi session usage (e.g. 1877/237 tok, $0.0084) with real data.
