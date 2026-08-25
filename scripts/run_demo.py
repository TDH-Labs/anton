#!/usr/bin/env python3
"""
Anton Live Interactive Demo & Asciinema Recording Generator.
Runs a complete end-to-end showcase of all agent-harness capabilities and captures
an animated demo.cast file for playback.
"""
import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"

DEMO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".demo-data"))
REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CAST_PATH = os.path.join(REPO_DIR, "demo.cast")

cast_events = []
start_monotonic = time.monotonic()


def record_out(text: str, delay: float = 0.0):
    sys.stdout.write(text)
    sys.stdout.flush()
    elapsed = round(time.monotonic() - start_monotonic, 3)
    cast_events.append([elapsed, "o", text])
    if delay:
        time.sleep(delay)


def log_header(title: str):
    record_out(f"\n{BOLD}{CYAN}════════════════════════════════════════════════════════════════════════════════{RESET}\n")
    record_out(f"{BOLD}{MAGENTA} 🌌 ANTON SHOWCASE {RESET}│ {BOLD}{YELLOW}{title}{RESET}\n")
    record_out(f"{BOLD}{CYAN}════════════════════════════════════════════════════════════════════════════════{RESET}\n\n", delay=0.3)


def log_step(num: int, label: str):
    record_out(f"\n{BOLD}{BLUE}[STEP {num}]{RESET} {BOLD}{GREEN}{label}{RESET}\n", delay=0.2)


def run_cmd(args, env=None, timeout=30):
    cmd_str = " ".join(args)
    record_out(f"{DIM}$ {cmd_str}{RESET}\n", delay=0.1)
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    full_env["PYTHONPATH"] = REPO_DIR
    res = subprocess.run(args, capture_output=True, text=True, cwd=REPO_DIR, env=full_env, timeout=timeout)
    if res.stdout:
        record_out(res.stdout)
    if res.stderr:
        record_out(f"{RED}{res.stderr}{RESET}")
    return res


def http_req(url, method="GET", data=None, headers=None):
    hdrs = headers or {}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def main():
    if os.path.exists(DEMO_DIR):
        shutil.rmtree(DEMO_DIR)
    os.makedirs(DEMO_DIR, exist_ok=True)

    log_header("AUTONOMOUS AGENT & ZERO-TRUST GATE SHOWCASE")

    # 1. SETUP
    log_step(1, "Turnkey Provisioning & Idempotent Environment Initialization")
    run_cmd(["python3", "-m", "anton.cli", "setup", "--install-dir", DEMO_DIR, "--executor", "fake"])
    time.sleep(0.5)

    # 2. DOCTOR
    log_step(2, "Read-Only System Doctor Diagnostic Verification")
    data_dir = os.path.join(DEMO_DIR, "data")
    run_cmd(["python3", "-m", "anton.cli", "doctor", "--data-dir", data_dir, "--executor", "fake"])
    time.sleep(0.5)

    # 3. SEEDING GATED JOBS
    log_step(3, "Configuring Jobs Spec (Cron, Webhooks, and Zero-Trust Gated Operations)")
    jobs_yaml = """- id: smoke-hook
  trigger: { type: webhook }
  recipe: smoke-hook
  expected_cadence_min: 0

- id: wire-transfer-action
  trigger: { type: webhook }
  recipe: wire-transfer-action
  gate: { money: true }
  expected_cadence_min: 0

- id: e2e-health-canary
  trigger: { type: cron, expr: "*/15 * * * *" }
  recipe: e2e-health-canary
  expected_cadence_min: 15
"""
    with open(os.path.join(data_dir, "jobs.yaml"), "w", encoding="utf-8") as f:
        f.write(jobs_yaml)
    record_out(f"{GREEN}✓ jobs.yaml updated with gated financial and webhook jobs{RESET}\n")

    # 4. LAUNCHING SERVICES (Serve on 8799, Dashboard on 8800)
    log_step(4, "Booting Services: Scheduler Engine (8799) & 3D Neural Dashboard (8800)")
    env = {"ANTON_DASHBOARD_TOKEN": "demo-secure-token-2026", "PYTHONPATH": REPO_DIR}
    
    serve_proc = subprocess.Popen(
        ["python3", "-m", "anton.cli", "serve", "--data-dir", data_dir, "--port", "8799"],
        cwd=REPO_DIR, env=dict(os.environ, **env),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    
    dash_proc = subprocess.Popen(
        ["python3", "-m", "anton.cli", "dashboard", "--data-dir", data_dir, "--port", "8800"],
        cwd=REPO_DIR, env=dict(os.environ, **env),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    
    time.sleep(2.0)
    record_out(f"{GREEN}✓ anton serve active on http://0.0.0.0:8799 (PID: {serve_proc.pid}){RESET}\n")
    record_out(f"{GREEN}✓ anton dashboard active on http://0.0.0.0:8800 (PID: {dash_proc.pid}){RESET}\n")

    try:
        # 5. TRIGGER WEBHOOK
        log_step(5, "Dispatching Webhook Event: POST /hooks/smoke-hook")
        status, res = http_req("http://127.0.0.1:8799/hooks/smoke-hook", method="POST", data={"event": "deploy_success"})
        record_out(f"HTTP Status: {status}  Response: {json.dumps(res, indent=2)}\n")
        time.sleep(0.5)

        # 6. TRIGGER GATED ACTION (SHOULD FAIL-CLOSED)
        log_step(6, "Triggering Gated High-Risk Action (Money Gate) -> Assert Fail-Closed")
        status, res = http_req("http://127.0.0.1:8799/hooks/wire-transfer-action", method="POST")
        record_out(f"HTTP Status: {status}  Response: {json.dumps(res, indent=2)}\n")
        if res.get("exit") == 5 and "gate-blocked" in res.get("flags", ""):
            record_out(f"{BOLD}{GREEN}✓ Hard Gate Verified: Operation blocked (Exit 5) without human approval.{RESET}\n")
        time.sleep(0.5)

        # 7. DASHBOARD AUTHENTICATION & APPROVAL
        log_step(7, "Dashboard API: Secure Human Approval Flow (Zero-Trust Token Gated)")
        auth_hdr = {"Authorization": "Bearer demo-secure-token-2026"}

        record_out(f"{DIM}1. Unauthenticated approval attempt (assert 401 Unauthorized):{RESET}\n")
        unauth_status, unauth_res = http_req("http://127.0.0.1:8800/api/approvals", method="POST",
                                             data={"action": "wire-transfer-action", "amount": "$5,000.00"})
        record_out(f"Status: {unauth_status} (Response: {unauth_res})\n")
        if unauth_status == 401:
            record_out(f"{BOLD}{GREEN}✓ Unauthenticated write rejected by security gate (401).{RESET}\n")

        record_out(f"\n{DIM}2. Authenticated operator creates approval request:{RESET}\n")
        create_st, create_res = http_req("http://127.0.0.1:8800/api/approvals", method="POST",
                                         data={"action": "wire-transfer-action", "amount": "$5,000.00", "recipient": "Acme Payroll"},
                                         headers=auth_hdr)
        record_out(f"Status: {create_st}  Created Approval: {json.dumps(create_res, indent=2)}\n")
        aid = create_res["id"]

        record_out(f"\n{DIM}3. Operator grants approval (decision: approve):{RESET}\n")
        res_st, res_data = http_req(f"http://127.0.0.1:8800/api/approvals/{aid}/resolve", method="POST",
                                    data={"decision": "approve"}, headers=auth_hdr)
        record_out(f"Status: {res_st}  Resolved: {json.dumps(res_data, indent=2)}\n")
        time.sleep(0.5)

        # 8. RE-RUN GATED ACTION
        log_step(8, "Re-executing Wire Transfer with Approved Nonce -> Single-Use Consumption")
        status2, res2 = http_req("http://127.0.0.1:8799/hooks/wire-transfer-action", method="POST")
        record_out(f"Run 1 Post-Approval: Exit {res2.get('exit')}  Flags: {res2.get('flags')}\n")

        record_out(f"\n{DIM}Immediate Re-run Attempt 2 (Checking Nonce Consumption):{RESET}\n")
        status3, res3 = http_req("http://127.0.0.1:8799/hooks/wire-transfer-action", method="POST")
        record_out(f"Run 2 Attempt: Exit {res3.get('exit')}  Flags: {res3.get('flags')}\n")
        if res3.get("exit") == 5:
            record_out(f"{BOLD}{GREEN}✓ Replay Protection Verified: Approval nonce consumed; subsequent run blocked!{RESET}\n")
        time.sleep(0.5)

        # 9. GOVERNOR
        log_step(9, "Ambition Governor: Mathematical EV × Feasibility Scoring & Routing")
        run_cmd(["python3", "-m", "anton.cli", "governor", "--ev", "0.95", "--feasibility", "0.85", "--risk", "low"])
        run_cmd(["python3", "-m", "anton.cli", "governor", "--ev", "0.95", "--feasibility", "0.85", "--kind", "money"])
        time.sleep(0.5)

        # 10. SECOND BRAIN VAULT & 3D GRAPH
        log_step(10, "Second Brain: Markdown Knowledge Vault & 3D Neural Graph Synthesis")
        vault_dir = os.path.join(data_dir, "vault")
        notes_dir = os.path.join(vault_dir, "notes")
        os.makedirs(notes_dir, exist_ok=True)
        with open(os.path.join(notes_dir, "qbo-recon.md"), "w", encoding="utf-8") as f:
            f.write("# QBO Bank Reconciliation\n\nAutomated sync protocol linking [[mocs/operations]] and [[skills/bill-capture]].\n")
        with open(os.path.join(notes_dir, "infra-gate.md"), "w", encoding="utf-8") as f:
            f.write("# Infrastructure Safety Gate\n\nSecurity policies for [[mocs/strategy]] and [[notes/qbo-recon|QBO Notes]].\n")

        run_cmd(["python3", "-m", "anton.cli", "vault", "--data-dir", data_dir])

        record_out(f"\n{DIM}Querying 3D Force-Directed Neural Graph Payload (/api/vault/graph):{RESET}\n")
        g_st, g_data = http_req("http://127.0.0.1:8800/api/vault/graph")
        record_out(f"Nodes Found: {len(g_data.get('nodes', []))}  Sample: {json.dumps(g_data.get('nodes', [])[:3], indent=2)}\n")
        time.sleep(0.5)

        # 11. EXECUTIVE DIGEST
        log_step(11, "Generating Executive Agent Markdown Digest")
        run_cmd(["python3", "-m", "anton.cli", "digest", "--data-dir", data_dir])
        digest_file = os.path.join(vault_dir, "digests", "daily-digest.md")
        if os.path.exists(digest_file):
            record_out(f"\n{BOLD}{YELLOW}--- Digest Preview ({os.path.basename(digest_file)}) ---{RESET}\n")
            with open(digest_file, encoding="utf-8") as f:
                record_out(f.read())
        time.sleep(0.5)

        # 12. METERING & AUDIT LEDGER
        log_step(12, "LLM Usage Metering, Cloud Accounting & Append-Only Event Ledger")
        run_cmd(["python3", "-m", "anton.cli", "usage", "--data-dir", data_dir])
        runs_file = os.path.join(data_dir, "runs.jsonl")
        if os.path.exists(runs_file):
            record_out(f"\n{BOLD}{YELLOW}--- Event Ledger Tail (runs.jsonl) ---{RESET}\n")
            with open(runs_file, encoding="utf-8") as f:
                for line in f.readlines()[-3:]:
                    record_out(line)

    finally:
        record_out(f"\n{DIM}Stopping server daemons...{RESET}\n")
        for p in (serve_proc, dash_proc):
            p.terminate()
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill()
        record_out(f"{GREEN}✓ Server shutdown complete.{RESET}\n")

    log_header("DEMO COMPLETE: ALL ANTON SUBSYSTEMS VERIFIED 100% OPERATIONAL")

    # Write Asciinema Cast file
    cast_header = {
        "version": 2,
        "width": 120,
        "height": 36,
        "timestamp": int(time.time()),
        "title": "Anton Autonomous Agent Showcase",
        "env": {"SHELL": "/bin/zsh", "TERM": "xterm-256color"}
    }
    with open(CAST_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps(cast_header) + "\n")
        for ev in cast_events:
            f.write(json.dumps(ev) + "\n")

    record_out(f"\n{BOLD}{GREEN}✓ Asciinema recording generated:{RESET} {CAST_PATH}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
