"""anton CLI — M1..M2 surface. Dev-safe: data stays under --data-dir."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

from .config import load_config
from .db import init_db
from .executor import FakeExecutor, OIExecutor, OpenCodeExecutor, PiExecutor
from .executor.ssh_executor import SSHExecutor
from .jobs import load_jobs
from .ledger import Ledger
from .models import RunRecord
from .routes import DEFAULT_CLOUD_MODEL, DEFAULT_LOCAL_MODEL, select_route
from .scheduler import JobEngine
from .vault_db import init_vault_db
from .webhook import WebhookServer
from .vault import emit_candidate, find_orphans, provision_vault, scan_vault
from .digest import build_digest, write_digest
from .governor import classify
from .learning import author_skill, index_skills
from .sandbox import promote, run_sandbox_gate
from .delta import scan_ledger_failures, scan_upskill_candidates
from .defaults import DEFAULT_JOBS_YAML
from .setup import run_setup
from .doctor import run_doctor
from .metering import connect as metering_connect, daily_totals, lifetime_totals
from .meta_learning import (
    process_pending_candidates, process_pending_opportunities,
    route as meta_learning_route, triage_skill_portfolio,
)
from .opportunity import scan_for_opportunities
from .upskill import consolidate_skill

EXECUTORS = {"fake": FakeExecutor, "pi": PiExecutor, "oi": OIExecutor, "ssh": SSHExecutor,
             "opencode": OpenCodeExecutor}

# Provider name (as saved by POST /api/wizard/providers, dashboard.py) ->
# the env var pi actually reads (pi --help's Environment Variables section).
_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
}


def _load_secrets_into_env(data_dir: str) -> None:
    """Provider keys saved via the setup wizard (POST /api/wizard/providers,
    dashboard.py's save_provider_key) land in secrets.yaml but were never
    read back anywhere -- PiExecutor's subprocess call (which inherits this
    process's environment) never actually saw a saved key. Load it in once
    at startup, before any executor is constructed."""
    secrets_path = os.path.join(os.path.dirname(data_dir), "secrets.yaml")
    if not os.path.exists(secrets_path):
        return
    import yaml
    with open(secrets_path, encoding="utf-8") as f:
        secrets = yaml.safe_load(f) or {}
    for provider, key in secrets.items():
        env_var = _PROVIDER_ENV_VARS.get(provider)
        if env_var and key and env_var not in os.environ:
            os.environ[env_var] = key


def _assert_isolation_trigger_integrity(data_dir: str) -> None:
    """The money/outbound gate lives in isolation.db; serve and any process
    that makes gate decisions must refuse to start on trigger drift — not
    only the dashboard process (R6-1)."""
    import sqlite3
    from .db import isolation_approvals_integrity
    path = os.path.join(data_dir, "isolation.db")
    if not os.path.exists(path):
        return
    conn = sqlite3.connect(path)
    try:
        drift = isolation_approvals_integrity(conn)
    finally:
        conn.close()
    if drift:
        raise RuntimeError(
            "isolation.db approvals trigger set drifted (" +
            ",".join(drift) + ") — refusing to start. Run `anton setup` "
            "/ re-run init_db to restore the canonical gate.")


def _build(config: dict, data_dir: str, executor_name: str):
    _load_secrets_into_env(data_dir)
    os.makedirs(data_dir, exist_ok=True)
    init_db(os.path.join(data_dir, "isolation.db"))
    _assert_isolation_trigger_integrity(data_dir)
    init_vault_db(os.path.join(data_dir, "vault", "vault.db"))
    jobs_path = os.path.join(data_dir, config.get("jobs_file", "jobs.yaml"))
    if not os.path.exists(jobs_path):
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_JOBS_YAML)
    jobs = load_jobs(jobs_path)
    if executor_name == "pi":
        executor = PiExecutor(tools=config["general"].get("pi_tools", PiExecutor().tools))
    else:
        executor = EXECUTORS.get(executor_name, FakeExecutor)()
    ledger = Ledger(os.path.join(data_dir, "runs.jsonl"))
    engine = JobEngine(jobs, ledger, executor, config, data_dir=data_dir)
    return jobs, ledger, engine


def _jobs_path(data_dir: str, config: dict) -> str:
    return os.path.join(data_dir, config.get("jobs_file", "jobs.yaml"))


def cmd_run(args, config: dict) -> int:
    jobs, ledger, engine = _build(config, args.data_dir, args.executor)
    route = select_route(prefer=args.route if args.route != "auto" else "local")
    model = args.model or route.model
    provider = args.provider or route.provider
    executor = EXECUTORS[args.executor]()
    result = executor.run(args.task, model=model, provider=provider)
    record = RunRecord.new(
        task=args.recipe, exit_code=result.exit_code,
        flags=f"executor:{args.executor};route:{args.route}",
        output=result.output, model=result.model, provider=result.provider,
        fallback_used=result.fallback_used, tokens_in=result.tokens_in,
        tokens_out=result.tokens_out, cost_usd=result.cost_usd,
        duration_ms=result.duration_ms,
    )
    ledger.append(record)
    print(json.dumps({"exit": record.exit, "model": record.model,
                      "provider": record.provider, "ledger": ledger.path}, indent=2))
    return 0 if record.exit == 0 else 1


def cmd_jobs(args, config: dict) -> int:
    jobs, _, _ = _build(config, args.data_dir, "fake")
    if args.run_id:
        engine = _build(config, args.data_dir, args.executor)[2]
        job = engine.by_id(args.run_id)
        if job is None:
            print(f"no job {args.run_id!r}", file=sys.stderr)
            return 1
        rec = engine.run_job(job)
        print(json.dumps({"job": job.id, "exit": rec.exit, "flags": rec.flags,
                          "ts": rec.ts}, indent=2))
        return 0 if rec.exit == 0 else 1
    for j in jobs:
        trig = j.trigger.get("type")
        extra = j.trigger.get("expr") if trig == "cron" else j.trigger.get("path", "")
        print(f"{j.id}\t{trig}\t{extra}\tcadence={j.expected_cadence_min}")
    return 0


def cmd_canary(args, config: dict) -> int:
    jobs, ledger, engine = _build(config, args.data_dir, "fake")
    trips = engine.run_canary()
    if not trips:
        print("PASS — no tripwires")
        return 0
    for t in trips:
        print(f"TRIPWIRE\t{t['job_id']}\tlast_seen={t.get('last_seen')}\t"
              f"expected_min={t['expected_min']}")
    return 1


def _opportunity_scan_due(data_dir: str, hours: float) -> bool:
    marker = os.path.join(data_dir, "last-opportunity-scan")
    if not os.path.exists(marker):
        return True
    with open(marker, encoding="utf-8") as f:
        last = f.read().strip()
    try:
        last_dt = dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return True
    return dt.datetime.now(dt.timezone.utc) - last_dt >= dt.timedelta(hours=hours)


def _touch_opportunity_scan(data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "last-opportunity-scan"), "w", encoding="utf-8") as f:
        f.write(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def cmd_serve(args, config: dict) -> int:
    jobs, ledger, engine = _build(config, args.data_dir, args.executor)
    host, port = config["general"]["host"], config["general"].get("port", 8799)
    if args.port:
        port = args.port
    srv = WebhookServer(engine, host, port)
    srv.start()
    print(f"anton serve: http://{host}:{srv.port}  (jobs={len(jobs)}, "
          f"executor={args.executor}, poll={config['general']['poll_seconds']}s)", flush=True)
    engine._touch_heartbeat()
    try:
        while True:
            engine._touch_heartbeat()
            # A provider key saved through the setup wizard after this process
            # already booted lands in secrets.yaml from a *different* process
            # (the dashboard) -- re-checking here each tick is what actually
            # gets it into this process's environment before the next dispatch,
            # instead of requiring a restart. Cheap: one file read per poll.
            _load_secrets_into_env(args.data_dir)
            # Pick up jobs.yaml edits (UI-added automations, hand edits)
            # without a restart — one stat() per poll.
            if engine.reload_jobs_if_changed():
                print(f"jobs reloaded: {len(engine.jobs)} defined", flush=True)
            for job in engine.due_jobs():
                rec = engine.run_job(job)
                print(f"[{rec.ts}] cron {job.id} exit={rec.exit} flags={rec.flags}", flush=True)
            trips = engine.run_canary()
            if trips:
                print(f"canary: {len(trips)} tripwire(s)", flush=True)
            # Failure -> initiative detection has to run here, not just in
            # `anton delta`, or process_pending_candidates below never sees
            # anything: repeated failures are the raw material of the
            # self-learning loop. Governor still gates dispatch (conservative
            # default leaves candidates pending); this only creates them.
            import sqlite3 as _sq3
            _db_conn = _sq3.connect(os.path.join(args.data_dir, "isolation.db"))
            try:
                _rem = scan_ledger_failures(ledger, _db_conn)
                _ups = scan_upskill_candidates(ledger, _db_conn)
                if _rem or _ups:
                    print(f"delta: {_rem} remediation(s), {_ups} upskill(s) "
                          f"candidate(s) detected", flush=True)
            finally:
                _db_conn.close()
            # Conservative by default (upskill.py's _DISPATCH_RISK_PROFILE
            # scores under the auto-execute threshold): a candidate detected
            # from repeated failures (delta.py's scan_upskill_candidates)
            # stays pending here unless the deployment explicitly opts in via
            # upskill.set_dispatch_risk_profile().
            upskilled = process_pending_candidates(engine)
            if upskilled:
                print(f"upskill: {len(upskilled)} candidate(s) processed", flush=True)
            # Proactive scan: not reacting to a failure, looking for things
            # worth upskilling toward before anything breaks. Real dispatch
            # cost, so this runs on its own hours-scale cadence, not every
            # poll tick.
            scan_hours = config["general"].get("opportunity_scan_hours", 24)
            if _opportunity_scan_due(args.data_dir, scan_hours):
                found = scan_for_opportunities(engine)
                _touch_opportunity_scan(args.data_dir)
                if found:
                    print(f"opportunity scan: {len(found)} candidate(s) found", flush=True)
                acted = process_pending_opportunities(engine)
                if acted:
                    print(f"opportunity: {len(acted)} candidate(s) processed", flush=True)
            time.sleep(config["general"].get("poll_seconds", 15))
    except KeyboardInterrupt:
        srv.stop()
        return 0


def cmd_vault(args, config: dict) -> int:
    vault_dir = os.path.join(args.data_dir, "vault")
    if args.provision:
        provision_vault(vault_dir)
        print(f"vault provisioned: {vault_dir}")
        return 0
    from .db import init_db
    init_db(os.path.join(args.data_dir, "isolation.db"))
    _assert_isolation_trigger_integrity(args.data_dir)
    new_mod, removed = scan_vault(vault_dir)
    db_conn = __import__("sqlite3").connect(os.path.join(args.data_dir, "isolation.db"))
    for n in new_mod:
        emit_candidate(db_conn, "review_vault_note", f"vault/{n['path']}")
    orphans = find_orphans(vault_dir)
    if orphans:
        emit_candidate(db_conn, "synthesize_vault_graph", "vault/Orphans")
    db_conn.close()
    print(f"new/modified: {len(new_mod)}, removed: {len(removed)}, orphans: {len(orphans)}")
    for n in new_mod:
        print(f"  new {n['path']}")
    for o in orphans:
        print(f"  orphan {o}")
    return 0 if not new_mod and not orphans else 1


def cmd_digest(args, config: dict) -> int:
    _jobs, _ledger, engine = _build(config, args.data_dir, "fake")
    vault_dir = os.path.join(args.data_dir, "vault")
    provision_vault(vault_dir)
    content = build_digest(engine, vault_dir, config,
                           heartbeat_path=os.path.join(args.data_dir, "last-heartbeat"))
    path = write_digest(os.path.join(vault_dir, "digests", "daily-digest.md"),
                        content, vault_dir)
    print(f"digest written: {path}")
    return 0


def cmd_governor(args, config: dict) -> int:
    r = classify(args.ev, args.feasibility, risk=args.risk, kind=args.kind)
    print(f"score={r.score}  route={r.route}  reasons={r.reasons}")
    return 0


def cmd_upskill(args, config: dict) -> int:
    _jobs, _ledger, engine = _build(config, args.data_dir, args.executor)
    if args.scan:
        # Explicit, human-triggered scan: same no-gate posture as --subject
        # (a deliberate action, not an inferred one) — the dispatch-into-
        # research step for anything it finds still goes through
        # process_pending_opportunities' governor gate below.
        found = scan_for_opportunities(engine)
        print(f"opportunity scan: {len(found)} candidate(s) found")
        for o in found:
            print(f"  {o.subject}  source={o.source}  worth={o.worth}")
        acted = process_pending_opportunities(engine)
        for a in acted:
            print(f"  {a['slug']}: {a['action']}" + (f" ({a.get('status')})" if a.get("status") else ""))
        return 0
    if args.triage:
        report = triage_skill_portfolio(engine)
        print(f"triage: {len(report.active)} active, {len(report.archived)} archived")
        for s_ in report.archived:
            print(f"  archived: {s_}")
        return 0
    if args.consolidate:
        did = consolidate_skill(engine, args.consolidate, threshold=args.consolidation_threshold)
        print(f"consolidated {args.consolidate}" if did else
              f"{args.consolidate}: not enough unconsumed lessons yet")
        return 0
    if not args.subject:
        print("--subject is required unless --consolidate/--triage", file=sys.stderr)
        return 2
    # meta-learning is the entry point (checks the existing pool first --
    # "reuse" short-circuits before any research/experience dispatch even
    # starts). is_repeated_failure=False here: a human named this subject
    # explicitly, so decide() only ever resolves to reuse/learn_from_research
    # -- min_sources/min_types/max_research_attempts are safe to forward.
    result = meta_learning_route(engine, args.subject, is_repeated_failure=False,
                                 min_sources=args.min_sources, min_types=args.min_types,
                                 max_research_attempts=args.max_research_attempts)
    print(f"upskill {result.slug}: {result.status}" + (f" ({result.detail})" if result.detail else ""))
    if result.research:
        print(f"  research: {len(result.research.sources)} source(s) across "
              f"{len(result.research.by_type)} type(s): {result.research.by_type}")
    return 0 if result.status in ("promoted", "reused") else 1


def cmd_skills(args, config: dict) -> int:
    data_dir = args.data_dir
    if args.index:
        return _index_skills(data_dir)
    if not args.title:
        print("--title is required unless --index", file=sys.stderr)
        return 2
    slug = author_skill(title=args.title, description=args.description,
                        condition=args.condition,
                        steps=(args.step1, args.step2, args.step3),
                        out_dir=os.path.join(data_dir, "staging", slug_of(args.title)))
    script = os.path.join(data_dir, "staging", slug_of(args.title), "scripts", f"{slug}_evaluator.py")
    ok = run_sandbox_gate(script, golden_payload=args.golden,
                          db_path=os.path.join(data_dir, "isolation.db"), slug=slug)
    if not ok:
        print(f"sandbox gate FAILED for {slug}")
        return 1
    dst = promote(script, os.path.join(data_dir, "skills"), slug=slug)
    import shutil
    staging_skill = os.path.join(data_dir, "staging", slug_of(args.title), "SKILL.md")
    if os.path.exists(staging_skill):
        shutil.copy2(staging_skill, os.path.join(data_dir, "skills", slug, "SKILL.md"))
    print(f"skill {slug} promoted -> {dst}")
    return 0


def _index_skills(data_dir: str) -> int:
    if not os.path.isdir(os.path.join(data_dir, "skills")):
        print("no skills dir yet", file=sys.stderr)
        return 1
    count = index_skills(data_dir)
    print(f"indexed {count} skill(s) into skill_dependencies")
    return 0


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slug_of(title: str) -> str:
    return title.lower().strip().replace(" ", "-").replace("_", "-")


def cmd_delta(args, config: dict) -> int:
    from .db import init_db
    _jobs, ledger, engine = _build(config, args.data_dir, "fake")
    db_conn = __import__("sqlite3").connect(os.path.join(args.data_dir, "isolation.db"))
    slugs = scan_ledger_failures(ledger, db_conn, since_hours=args.since)
    # A single failure is a repair candidate (scan_ledger_failures, above);
    # repeated failure of the SAME task is a competence gap and gets the
    # research-first pipeline instead (upskill.py), not a simple re-run.
    upskill_slugs = scan_upskill_candidates(ledger, db_conn, since_hours=args.since)
    trips = engine.run_canary()
    db_conn.close()
    print(f"ledger-failure candidates: {len(slugs)}")
    for s_ in slugs:
        print(f"  {s_}")
    print(f"upskill candidates: {len(upskill_slugs)}")
    for s_ in upskill_slugs:
        print(f"  {s_}")
    print(f"tripwires: {len(trips)}")
    for t in trips:
        print(f"  {t['job_id']}")
    return 0 if not slugs and not upskill_slugs and not trips else 1


def cmd_setup(args, config: dict) -> int:
    keys = {}
    for env in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        v = os.environ.get(env)
        if v:
            keys[env] = v
    info = run_setup(args.install_dir, executor=args.executor, org_id=args.org_id,
                     provider_keys=keys or None, force=args.force)
    print("anton installed:")
    for k, v in info.items():
        print(f"  {k}: {v}")
    return 0


def cmd_dashboard(args, config: dict) -> int:
    from .dashboard import create_app
    import uvicorn
    _jobs, _ledger, engine = _build(config, args.data_dir, args.executor)
    app = create_app(engine, args.data_dir, config)
    host, port = config["general"]["host"], args.port or config["general"].get("port", 8799)
    print(f"anton dashboard: http://{host}:{port}  (read-only pane + approvals)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def cmd_doctor(args, config: dict) -> int:
    lines, ok = run_doctor(args.data_dir, executor_name=args.executor)
    for ln in lines:
        print(ln)
    return 0 if ok else 1


def cmd_usage(args, config: dict) -> int:
    db = os.path.join(args.data_dir, "isolation.db")
    if not os.path.exists(db):
        print("no isolation.db yet — run setup first", file=sys.stderr)
        return 1
    conn = metering_connect(db)
    import json
    print(json.dumps({"daily": daily_totals(conn, args.org_id),
                      "lifetime": lifetime_totals(conn, args.org_id)}, indent=2))
    conn.close()
    return 0


def cmd_oauth(args, config: dict) -> int:
    from .oauth import CallbackServer
    srv = CallbackServer(port=args.port, timeout_s=args.timeout)
    srv.start()
    print(f"OAuth callback listening on http://127.0.0.1:{srv.port}/callback "
          f"(timeout {args.timeout}s)", flush=True)
    print("Send the provider here: /callback?code=<CODE>&state=<STATE>", flush=True)
    try:
        result = srv.wait()
        print(f"received: code={'<redacted>' if result.get('code') else '(none)'} "
              f"state={result.get('state') or '(none)'}")
        return 0
    except TimeoutError:
        print("timeout — no callback received", file=sys.stderr)
        return 1
    finally:
        srv.stop()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="anton", description="anton — an AI agent for your small business")
    sub = ap.add_subparsers(dest="command", required=True)
    ap.add_argument("--config", default=None, help=argparse.SUPPRESS)

    run = sub.add_parser("run", help="run a task through an executor and record to the ledger")
    run.add_argument("--task", required=True)
    run.add_argument("--recipe", default="adhoc")
    run.add_argument("--executor", choices=sorted(EXECUTORS), default="pi")
    run.add_argument("--route", choices=["local", "cloud", "auto"], default="auto")
    run.add_argument("--data-dir", default=".dev-data")
    run.add_argument("--model", default=None)
    run.add_argument("--provider", default=None)
    run.set_defaults(fn=cmd_run)

    jobs = sub.add_parser("jobs", help="list jobs (or run one with --run-id)")
    jobs.add_argument("--data-dir", default=".dev-data")
    jobs.add_argument("--executor", choices=sorted(EXECUTORS), default="pi")
    jobs.add_argument("--run-id", default=None)
    jobs.set_defaults(fn=cmd_jobs)

    canary = sub.add_parser("canary", help="expected-vs-actual tripwire check")
    canary.add_argument("--data-dir", default=".dev-data")
    canary.set_defaults(fn=cmd_canary)

    serve = sub.add_parser("serve", help="run scheduler loop + webhook receiver")
    serve.add_argument("--data-dir", default=".dev-data")
    serve.add_argument("--executor", choices=sorted(EXECUTORS), default="pi")
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(fn=cmd_serve)

    vault = sub.add_parser("vault", help="provision the second-brain vault or run the delta/graph scan")
    vault.add_argument("--data-dir", default=".dev-data")
    vault.add_argument("--provision", action="store_true")
    vault.set_defaults(fn=cmd_vault)

    digest = sub.add_parser("digest", help="generate the agent digest into the vault")
    digest.add_argument("--data-dir", default=".dev-data")
    digest.set_defaults(fn=cmd_digest)

    gov = sub.add_parser("governor", help="ambition governor: score + route a candidate")
    gov.add_argument("--ev", type=float, required=True)
    gov.add_argument("--feasibility", type=float, required=True)
    gov.add_argument("--risk", default="low")
    gov.add_argument("--kind", default="internal")
    gov.set_defaults(fn=cmd_governor)

    skills = sub.add_parser("skills", help="author + sandbox-gate + promote a skill")
    skills.add_argument("--title", default=None)
    skills.add_argument("--description", default="")
    skills.add_argument("--condition", default="task matches")
    skills.add_argument("--step1", default="Detect the condition")
    skills.add_argument("--step2", default="Compute the decision rule")
    skills.add_argument("--step3", default="Commit to action")
    skills.add_argument("--golden", default=None)
    skills.add_argument("--data-dir", default=".dev-data")
    skills.set_defaults(fn=cmd_skills)

    delta = sub.add_parser("delta", help="delta detection: failures + canary -> candidates")
    delta.add_argument("--data-dir", default=".dev-data")
    delta.add_argument("--since", type=int, default=24)
    delta.set_defaults(fn=cmd_delta)

    upskill = sub.add_parser("upskill", help="research-first skill authoring (learn-from-research)")
    upskill.add_argument("--subject", default=None)
    upskill.add_argument("--consolidate", default=None, metavar="SLUG",
                         help="merge+prune unconsumed lessons into an existing skill instead of upskilling a new subject")
    upskill.add_argument("--consolidation-threshold", type=int, default=3)
    upskill.add_argument("--triage", action="store_true",
                         help="archive dormant skills (unused in the staleness window) instead of upskilling a subject")
    upskill.add_argument("--scan", action="store_true",
                         help="proactively scan connected sources (vault + mcp_servers) for opportunities instead of upskilling a named subject")
    upskill.add_argument("--min-sources", type=int, default=5)
    upskill.add_argument("--min-types", type=int, default=2)
    upskill.add_argument("--max-research-attempts", type=int, default=3)
    upskill.add_argument("--data-dir", default=".dev-data")
    upskill.add_argument("--executor", choices=sorted(EXECUTORS), default="pi")
    upskill.set_defaults(fn=cmd_upskill)

    setup = sub.add_parser("setup", help="provision a fresh install directory")
    setup.add_argument("--install-dir", default=os.path.expanduser("~/.anton"))
    setup.add_argument("--executor", default="pi")
    setup.add_argument("--org-id", default="default")
    setup.add_argument("--force", action="store_true")
    setup.set_defaults(fn=cmd_setup)

    dash = sub.add_parser("dashboard", help="run the read-only web dashboard + approvals")
    dash.add_argument("--data-dir", default=".dev-data")
    dash.add_argument("--executor", choices=sorted(EXECUTORS), default="pi")
    dash.add_argument("--port", type=int, default=None)
    dash.set_defaults(fn=cmd_dashboard)
    skills.add_argument("--index", action="store_true",
                        help="index data/skills into skill_dependencies")

    doctor = sub.add_parser("doctor", help="read-only diagnostics")
    doctor.add_argument("--data-dir", default=".dev-data")
    doctor.add_argument("--executor", default="pi")
    doctor.set_defaults(fn=cmd_doctor)

    usage = sub.add_parser("usage", help="metering totals (cloud usage)")
    usage.add_argument("--data-dir", default=".dev-data")
    usage.add_argument("--org-id", default="default")
    usage.set_defaults(fn=cmd_usage)

    oauth = sub.add_parser("oauth", help="localhost OAuth callback server (onboarding)")
    oauth.add_argument("--port", type=int, default=0)
    oauth.add_argument("--timeout", type=int, default=120)
    oauth.set_defaults(fn=cmd_oauth)

    args = ap.parse_args(argv)
    config = load_config(args.config)
    return args.fn(args, config)


if __name__ == "__main__":
    sys.exit(main())
