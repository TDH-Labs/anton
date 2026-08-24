# New Client Onboarding Checklist (per firm)

## Automated (provision_client.py)
- [ ] Install root created; config/jobs/vault/skills seeded
- [ ] authz enabled (multi_user); decision + webhook secrets generated (0600)
- [ ] Vendor QBO app credentials persisted deployment-local

## Operator (KPF staff) — ~10 min
- [ ] Start dashboard; read FIRST-RUN OWNER CLAIM CODE from logs
- [ ] Client's designated owner claims account with code (their login)
- [ ] Create operator accounts for client staff (role: Operator)
- [ ] Verify isolation: client sees only their box; no cross-firm accounts

## Client (their two minutes of provider logins)
- [ ] Connect QuickBooks (their QBO login on Intuit's hosted page)
- [ ] Any additional Connect flows per subscription (Gmail, Slack...)
- [ ] Paste API keys into Settings forms directly (never via chat/email)

## AI-assisted configuration
- [ ] Onboarding interview: workflows wanted (PO approvals, alerts, digests)
- [ ] Review AI-drafted job configs BEFORE activation (approval gate applies)
- [ ] Activate; confirm first gated action routes correctly

## Sign-off
- [ ] First gated execution completed end-to-end (approved -> consumed once)
- [ ] Audit chain verified post-onboarding
