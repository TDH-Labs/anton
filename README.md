# Anton

Anton is an AI agent for your small business. Point it at the busywork — following up
on bills, watching the accounts you connect it to, keeping the schedule — and it does
the work itself.

Most agent products stop there: a loop that runs when you tell it to and starts fresh
every time. Want it to actually remember things? That's a vector DB or a notes app
you stand up yourself. Want it to stop before it spends money or emails a client
without asking first? That's a guardrail you wire up with a third-party framework,
bolted on after the fact. Anton ships with both already built in:

- **A second brain, live from first boot.** Notes, playbooks, and a graph of what
  it's picked up live in a real vault — markdown plus a queryable index — the moment
  Anton starts, browsable in the Ops Center's Memory tab. Nothing to connect
  separately.
- **A governor, not a suggestion.** Anything touching money or sending something on
  your behalf is hard-gated, full stop — it waits for your OK no matter what. Every
  other call Anton makes for itself, like repairing a stalled job or promoting a
  skill it taught itself, gets scored first; confidence has to clear a real bar
  before it acts without asking.

It doesn't just execute what you scheduled, either. A proactive scanner watches
whatever you've actually connected — the vault, your accounts, whatever's wired up —
for things worth doing before anything's even gone wrong, and queues them through
that same governor gate, so nothing runs on its own say-so alone. A stalled job gets
noticed the same way: if the fix is low-risk, Anton re-runs it itself instead of
waiting for you to catch it. And it teaches itself as it goes — research-backed when
the subject is new to it, drawn from its own past runs when something didn't go the
way it expected — picking up real skills instead of quietly rerunning the same
mistake.

The Ops Center is where you keep an eye on all of it: what it's doing right now, what
it noticed on its own, what's waiting on your OK, what went wrong, what it's learned.

## Getting started

You'll need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed
(it's free — download it, open it, that's the setup). Once it's running, open a terminal
and paste:

```bash
docker run -d --name anton -p 3080:3080 -v anton_data:/data ghcr.io/tdh-labs/anton:latest
```

That downloads and starts Anton. It runs quietly in the background from here — you don't
need to keep the terminal open.

This command is for your own computer or a trusted network — it has no HTTPS, so your
password would travel in plain text if port 3080 were opened to the public internet.
Putting Anton on a VPS with a public IP instead? Use [Installing on a VPS](#installing-on-a-vps) below, which adds real HTTPS.

Open [http://localhost:3080](http://localhost:3080) in your browser. The first thing
you'll see is a login screen with a password shown right on the page — write it down,
it's only shown once. Log in with it.

Anton will then walk you through a short setup wizard:

1. **Connect an AI provider.** This is the one step that costs money — Anton itself is
   free, but it needs an AI model to actually do the thinking, and that's billed by
   whichever provider you pick (Anthropic, OpenAI, DeepSeek, or OpenRouter), based on
   how much you use it. For one small business this is typically a few dollars a
   month, not a subscription — you only pay for what Anton actually does. The wizard
   links directly to each provider's page for getting a key. You can skip this step —
   Anton still boots and everything else still works, it just can't do real work until
   a key is saved (you can always come back to this later from Add-ons).
2. **Pick what to automate.** A handful of suggested starting points — pick any that
   sound useful, or none, you can always add more later.
3. **Connect it to your other systems.** QuickBooks, Slack, whatever you actually use —
   also entirely optional, and skippable for now.
4. **Set how much rope Anton has.** How much it's allowed to just do on its own versus
   how much it should check with you first. You can always loosen or tighten this
   later, per automation.

That's it — you're in. From there the Ops Center is the actual day-to-day app: what
Anton is working on right now, what's waiting on your approval, what went wrong (if
anything), and what it's learned.

## Installing on a VPS

The command above works fine on a VPS too, but it has no HTTPS — anyone on the network
path could see your password the moment port 3080 is open to the public internet. This
uses [Caddy](https://caddyserver.com/) as a reverse proxy in front of Anton instead,
which gets you a real, auto-renewing HTTPS certificate with no manual setup.

You'll need one thing plain `docker run` doesn't: a domain name (even a cheap or free
one) with its DNS **A record** pointed at your VPS's IP address — real HTTPS certificates
are issued for domain names, not bare IP addresses. Make sure ports 80 and 443 are open
in your cloud provider's firewall (Caddy needs both — 80 for the initial certificate
request, 443 for HTTPS itself).

```bash
git clone https://github.com/TDH-Labs/anton.git && cd anton
DOMAIN=yourdomain.com docker compose -f vps/docker-compose.yml up -d
```

Give it a minute for Caddy to request the certificate, then open `https://yourdomain.com`
— same login screen, same setup wizard, just with real HTTPS in front of it this time.
Updating and your data work exactly the same way as below, just with
`-f vps/docker-compose.yml` on your `docker compose` commands.

## Updating

```bash
docker pull ghcr.io/tdh-labs/anton:latest
docker stop anton && docker rm anton
docker run -d --name anton -p 3080:3080 -v anton_data:/data ghcr.io/tdh-labs/anton:latest
```

Your data lives in the `anton_data` volume, not the container — this swaps in the new
version without losing anything.

## Your data

Everything Anton knows — its second brain, its job history, your automations, your
connected accounts — lives in the `anton_data` Docker volume, not the container itself.
Removing and recreating the container (as in Updating, above) is safe. Removing the
*volume* is not — that's the one thing that actually deletes your data. Back it up like
you would any other important folder; see
[`docs/VM-RUNBOOK.md`](docs/VM-RUNBOOK.md#backup-and-restore) for the exact commands.

## What's actually running

One container, four processes:

- **`anton serve`** — the cron/webhook scheduler loop, plus tripwire detection: a job
  that's gone quiet gets auto-repaired (re-run) if the governor scores it low-risk, or
  surfaced for your review otherwise. Internal only.
- **`anton dashboard`** — the FastAPI `/api/*` surface the Ops Center UI talks to.
  Internal only.
- **`dsh web`** — the Ops Center UI itself. Binds loopback-only by its own design — no
  auth or TLS on that surface, and it has real file and shell access, so it never
  touches the network directly.
- **`docker/auth-gate.mjs`** — the one process actually published. A small password-
  gated reverse proxy in front of `dsh web`, so the whole thing is safe to expose
  directly without an SSH tunnel.

For a docker-compose file, Umbrel app manifest, and the full set of environment
variables Anton reads, see [`umbrel/anton/docker-compose.yml`](umbrel/anton/docker-compose.yml)
— every variable Anton supports is listed there with what it does. For a VPS with a
public IP, see [`vps/docker-compose.yml`](vps/docker-compose.yml) instead — the same
image, fronted by Caddy for real HTTPS (see [Installing on a VPS](#installing-on-a-vps)).

## License

See [LICENSE](LICENSE) — free to self-host and modify; not free to resell as a hosted
service without a separate agreement.

Anton is built on top of real, credited open-source work — full license text for
each is in [NOTICE](NOTICE):

- **[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)** — the Ops
  Center UI (`anton-studio/`) is a fork of it.
- **[pi](https://github.com/earendil-works/pi)** — the default executor, bundled in
  the image.
- **[opencode](https://github.com/anomalyco/opencode)** — a second executor, used
  for jobs that need browser tools, also bundled in the image.
- **[Playwright](https://github.com/microsoft/playwright-python)** and
  **[Playwright MCP](https://github.com/microsoft/playwright-mcp)** — drive the
  stored-login browser feature; Chromium itself ships in the image via Playwright.
- **[Caddy](https://caddyserver.com/)** — used, not bundled: the VPS install path
  runs it as its own separate container for HTTPS.

---

## Advanced / developer reference

Everything below is for extending or running Anton outside Docker — not needed to use
the product day to day.

### Executors

`ANTON_EXECUTOR` selects what actually runs a task: `pi` (default — a general-purpose
coding agent, tool-restricted to read-only by default via `pi_tools` in config.yaml),
`opencode` (a multi-provider agent with MCP support — the executor a job uses when it
needs browser tools on an already-authenticated stored-login session, see the
`executor:` job field below), `oi` (Open Interpreter, scoped as an office/PDF/media
specialist), `ssh` (run on a remote host you control), or `fake` (a mock, for testing).

### Commands (native / non-Docker install)

```
anton setup     --install-dir ~/.anton                # provision a fresh install
anton serve     --data-dir … [--port 8799]             # scheduler + webhook + canary
anton dashboard --data-dir … [--port 8799]             # /api/* surface + approvals
anton jobs      --data-dir … [--run-id <id>]           # list / run one job
anton canary    --data-dir …                           # expected-vs-actual tripwires
anton digest    --data-dir …                           # daily status digest
anton vault     --provision | scan                     # second-brain provision / scan
anton governor  --ev 0.8 --feasibility 0.9 --kind money  # score one decision
anton doctor    --data-dir …                           # read-only install diagnostics
anton run       --task "…" --executor pi               # one-off run into the ledger
```

`bash install.sh` installs natively into `$ANTON_HOME` (default `~/.anton`) instead of
via Docker — useful for a host that should run Anton directly rather than containerized.

### Jobs

`jobs.yaml` is the manifest:

```yaml
- id: bill-email
  trigger: { type: webhook, path: /hooks/bill-email }
  recipe: bill-capture
  expected_cadence_min: 1440
- id: notify-client
  trigger: { type: webhook, path: /hooks/notify-client }
  recipe: notify-client
  gate: { outbound: true }        # requires an approved nonce before it can run
- id: check-quickbooks-balance
  trigger: { type: webhook }
  recipe: "Using the browser tools available, check the current account balance and report it back."
  executor: { name: opencode, mcp_profile: quickbooks }  # a stored-login connection's persistent session
  gate: { outbound: true }        # real access to a real account -- always approved by hand
```

- Triggers: cron (5-field), webhook (`POST /hooks/<id>`), delta.
- Verify: shell command with a `<output>` token; non-zero exit fails the run.
- Budgets: per-job and daily token/cost caps, enforced.
- Gates: `money`/`outbound` jobs block until an approval exists (Ops Center's Waiting
  on you, or the dashboard API).
- Executor override: `executor: {name, ...}` runs just that one job through a different
  executor than the install's default — today, `{name: opencode, mcp_profile: <id>}`
  for a job that needs an Add-ons stored-login connection's already-authenticated
  browser session (the password itself never reaches the job; only the logged-in
  session does).
- Canary: a job that misses 2× its expected cadence trips a tripwire — if it has a
  mapped repair recipe and scores low-risk, Anton re-runs it itself; otherwise it's
  surfaced for you.

### Tests

```bash
pip install -e . pytest
python -m pytest tests/ -v
```
