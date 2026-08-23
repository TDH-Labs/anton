# NEXT SESSION — START HERE
Frozen spec: docs/AUTHZ-SPEC.md (v1.1, FROZEN — build against it, do not redesign).
Reviews (binding requirements): docs/AUTHZ-ADVERSARIAL-REVIEW{,-2,-3}.md
Convergence threshold: two consecutive independent PROCEED verdicts, zero BLOCKER/MAJOR.

## Remaining build order (todo mirror)
1. #10 Phase 1 authZ spine — users/sessions/RBAC, route+data-layer guards,
   credential broker, adversarial CI suite WRITTEN FIRST. Commit as Vibherpunk.
2. #12 Secrets vault + BYO password-manager adapters (broker resolves op:// bw:// vault:// refs)
3. #11 AgentPhone/Email (opt-in connections; egress tags + governor apply)
4. #5 QBO OAuth end-to-end (creds: ~/secrets/harwell/secrets.env on Mac AND
   /home/umbrel/secrets/harwell/secrets.env on Umbrel; oauth.quickbooks already in
   Umbrel config via mounted entrypoint patch — see ~/umbrel/app-data/anton/entrypoint.sh)

## Deploy notes
- Umbrel app at ~/umbrel/app-data/anton has LOCAL overrides (app-proxy service,
  entrypoint mount, config-override.yaml) — upstream into repo compose/manifest.
- Image is amd64-only; deploy = docker compose pull && up -d --force-recreate
  (verify digest matches GHCR latest — stale-tag issues seen).

## Rules
- NEVER push secrets or PII. Adversarial tests must stay green before any "done".
