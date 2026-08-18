"""harbor CLI — M1..M2 surface. Dev-safe: data stays under --data-dir."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

from .config import load_config
from .db import init_db
from .executor import FakeExecutor, OIExecutor, PiExecutor
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
from .learning import author_skill
from .sandbox import promote, run_sandbox_gate
from .delta import scan_ledger_failures
from .defaults import DEFAULT_JOBS_YAML
from .setup import run_setup

EXECUTORS = {"fake": FakeExecutor, "pi": PiExecutor, "oi": OIExecutor}



def _build(config: dict, data_dir: str, executor_name: str):
    os.makedirs(data_dir, exist_ok=True)
    init_db(os.path.join(data_dir, "isolation.db"))
    init_vault_db(os.path.join(data_dir, "vault", "vault.db"))
    jobs_path = os.path.join(data_dir, config.get("jobs_file", "jobs.yaml"))
    if not os.path.exists(jobs_path):
        with open(jobs_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_JOBS_YAML)
    jobs = load_jobs(jobs_path)
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


def cmd_serve(args, config: dict) -> int:
    jobs, ledger, engine = _build(config, args.data_dir, args.executor)
    host, port = config["general"]["host"], config["general"].get("port", 8799)
    if args.port:
        port = args.port
    srv = WebhookServer(engine, host, port)
    srv.start()
    print(f"harbor serve: http://{host}:{srv.port}  (jobs={len(jobs)}, "
          f"executor={args.executor}, poll={config['general']['poll_seconds']}s)", flush=True)
    try:
        while True:
            for job in engine.due_jobs():
                rec = engine.run_job(job)
                print(f"[{rec.ts}] cron {job.id} exit={rec.exit} flags={rec.flags}", flush=True)
            trips = engine.run_canary()
            if trips:
                print(f"canary: {len(trips)} tripwire(s)", flush=True)
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
    path = write_digest(os.path.join(vault_dir, "digests", "control-plane-digest.md"),
                        content, vault_dir)
    print(f"digest written: {path}")
    return 0


def cmd_governor(args, config: dict) -> int:
    r = classify(args.ev, args.feasibility, risk=args.risk, kind=args.kind)
    print(f"score={r.score}  route={r.route}  reasons={r.reasons}")
    return 0


def cmd_skills(args, config: dict) -> int:
    data_dir = args.data_dir
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
    print(f"skill {slug} promoted -> {dst}")
    return 0


def slug_of(title: str) -> str:
    return title.lower().strip().replace(" ", "-").replace("_", "-")


def cmd_delta(args, config: dict) -> int:
    from .db import init_db
    _jobs, ledger, engine = _build(config, args.data_dir, "fake")
    db_conn = __import__("sqlite3").connect(os.path.join(args.data_dir, "isolation.db"))
    slugs = scan_ledger_failures(ledger, db_conn, since_hours=args.since)
    trips = engine.run_canary()
    db_conn.close()
    print(f"ledger-failure candidates: {len(slugs)}")
    for s_ in slugs:
        print(f"  {s_}")
    print(f"tripwires: {len(trips)}")
    for t in trips:
        print(f"  {t['job_id']}")
    return 0 if not slugs and not trips else 1


def cmd_setup(args, config: dict) -> int:
    keys = {}
    for env in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        v = os.environ.get(env)
        if v:
            keys[env] = v
    info = run_setup(args.install_dir, executor=args.executor, org_id=args.org_id,
                     provider_keys=keys or None, force=args.force)
    print("harbor-sas installed:")
    for k, v in info.items():
        print(f"  {k}: {v}")
    return 0


def cmd_dashboard(args, config: dict) -> int:
    from .dashboard import create_app
    import uvicorn
    _jobs, _ledger, engine = _build(config, args.data_dir, args.executor)
    app = create_app(engine, args.data_dir, config)
    host, port = config["general"]["host"], args.port or config["general"].get("port", 8799)
    print(f"harbor dashboard: http://{host}:{port}  (read-only pane + approvals)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harbor", description="harbor-sas control plane")
    sub = ap.add_subparsers(dest="command", required=True)
    ap.add_argument("--config", default=None, help=argparse.SUPPRESS)

    run = sub.add_parser("run", help="run a task through an executor and record to the ledger")
    run.add_argument("--task", required=True)
    run.add_argument("--recipe", default="adhoc")
    run.add_argument("--executor", choices=sorted(EXECUTORS), default="fake")
    run.add_argument("--route", choices=["local", "cloud", "auto"], default="auto")
    run.add_argument("--data-dir", default=".dev-data")
    run.add_argument("--model", default=None)
    run.add_argument("--provider", default=None)
    run.set_defaults(fn=cmd_run)

    jobs = sub.add_parser("jobs", help="list jobs (or run one with --run-id)")
    jobs.add_argument("--data-dir", default=".dev-data")
    jobs.add_argument("--executor", choices=sorted(EXECUTORS), default="fake")
    jobs.add_argument("--run-id", default=None)
    jobs.set_defaults(fn=cmd_jobs)

    canary = sub.add_parser("canary", help="expected-vs-actual tripwire check")
    canary.add_argument("--data-dir", default=".dev-data")
    canary.set_defaults(fn=cmd_canary)

    serve = sub.add_parser("serve", help="run scheduler loop + webhook receiver")
    serve.add_argument("--data-dir", default=".dev-data")
    serve.add_argument("--executor", choices=sorted(EXECUTORS), default="fake")
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(fn=cmd_serve)

    vault = sub.add_parser("vault", help="provision the second-brain vault or run the delta/graph scan")
    vault.add_argument("--data-dir", default=".dev-data")
    vault.add_argument("--provision", action="store_true")
    vault.set_defaults(fn=cmd_vault)

    digest = sub.add_parser("digest", help="generate the control-plane digest into the vault")
    digest.add_argument("--data-dir", default=".dev-data")
    digest.set_defaults(fn=cmd_digest)

    gov = sub.add_parser("governor", help="ambition governor: score + route a candidate")
    gov.add_argument("--ev", type=float, required=True)
    gov.add_argument("--feasibility", type=float, required=True)
    gov.add_argument("--risk", default="low")
    gov.add_argument("--kind", default="internal")
    gov.set_defaults(fn=cmd_governor)

    skills = sub.add_parser("skills", help="author + sandbox-gate + promote a skill")
    skills.add_argument("--title", required=True)
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

    setup = sub.add_parser("setup", help="provision a fresh install directory")
    setup.add_argument("--install-dir", default=os.path.expanduser("~/.harbor"))
    setup.add_argument("--executor", default="fake")
    setup.add_argument("--org-id", default="default")
    setup.add_argument("--force", action="store_true")
    setup.set_defaults(fn=cmd_setup)

    dash = sub.add_parser("dashboard", help="run the read-only web dashboard + approvals")
    dash.add_argument("--data-dir", default=".dev-data")
    dash.add_argument("--executor", choices=sorted(EXECUTORS), default="fake")
    dash.add_argument("--port", type=int, default=None)
    dash.set_defaults(fn=cmd_dashboard)

    args = ap.parse_args(argv)
    config = load_config(args.config)
    return args.fn(args, config)


if __name__ == "__main__":
    sys.exit(main())
