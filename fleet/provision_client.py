#!/usr/bin/env python3
"""KPF fleet: provision a new client Anton deployment.

One command -> a ready-to-configure client box:
    python fleet/provision_client.py --client "ACME Manufacturing" \\
        --install-dir /srv/anton-clients/acme --admin-email kpf@tdhlabs.com

Steps performed (idempotent):
  1. run_setup for the client's install dir (config, jobs, vault, skills)
  2. authz enabled with AUTO-GENERATED decision/webhook secrets (0600 files)
  3. vendor QBO app credentials copied from the reference source
  4. prints the NEXT-STEPS checklist (owner claim, connect flows, staff accounts)

The client's people then complete their two minutes of provider logins via
the Ops Center wizard; KPF finishes with workflow config review.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help="client firm name")
    ap.add_argument("--slug", help="short slug (default: derived from name)")
    ap.add_argument("--install-dir", required=True,
                    help="absolute path for this client's install root")
    ap.add_argument("--executor", default="pi")
    args = ap.parse_args()

    slug = (args.slug or "".join(
        c for c in args.client.lower().replace(" ", "-") if c.isalnum() or c == "-"))
    install = os.path.abspath(args.install_dir)

    print(f"[fleet] provisioning {args.client!r} -> {install}")
    sys.path.insert(0, REPO)
    from anton.setup import run_setup
    run_setup(install, executor=args.executor)

    # enable hardened mode; authz enabled with NO inline secrets —
    # decision/webhook secrets auto-provision as 0600 files under
    # data/authz/ at first boot (R21-MAJOR: never in world-readable yaml)
    import yaml
    cfg_path = os.path.join(install, "config.yaml")
    cfg = yaml.safe_load(open(cfg_path)) or {}
    az = cfg.setdefault("authz", {})
    az["enabled"] = True
    az["mode"] = "multi_user"
    az.pop("decision_secret", None)
    cfg.setdefault("general", {}).pop("webhook_secret", None)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    os.chmod(cfg_path, 0o600)  # defense-in-depth: no world-readable config

    # vendor QBO credentials -> deployment-local copy under data/ (the dir
    # the dashboard reads at runtime; R21 path fix)
    sys.path.insert(0, REPO)
    from anton.qbo_oauth import load_vendor_credentials, persist_vendor_credentials
    cid, csec = load_vendor_credentials(os.path.join(REPO, ".dev-data"))
    if cid and csec:
        persist_vendor_credentials(os.path.join(install, "data"), cid, csec)
        print("[fleet] vendor QBO credentials persisted")

    print("[fleet] decision + webhook secrets will auto-generate (0600) on"
          " first dashboard boot")

    print(f"""
[fleet] DONE \u2014 {args.client} provisioned.

NEXT STEPS (operator):
  1. start the stack:
     anton --config {cfg_path} dashboard --data-dir {os.path.join(install, 'data')}
  2. read the FIRST-RUN OWNER CLAIM CODE from stdout/logs and claim Owner
     in the Ops Center wizard (browser)
  3. create operator accounts for the client's staff
  4. walk the client through Connect flows (QBO etc.) \u2014 they sign in at
     each provider with THEIR login; never share logins across firms
  5. review AI-drafted workflow configs before activation (approval gates
     apply to these too)
""")


if __name__ == "__main__":
    main()
