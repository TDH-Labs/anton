# Intuit Developer App Registration — Fill-in-the-Blanks Worksheet

One-time vendor task (TDH Labs). Everything below maps field-for-field to
developer.intuit.com forms. Time: ~30 min of forms, then Intuit's review
queue (days\u2013weeks). Until production approval, customer QBO connections
run in development mode against designated test accounts \u2014 fully usable
for pilots.

## 1. Account & app creation
- [ ] Account at developer.intuit.com under the TDH Labs vendor email:
      ____________________
- [ ] Create App \u2192 name: `Anton`
- [ ] App description: "Self-hosted business operations agent \u2014 connects
      QuickBooks for bookkeeping automation with human approval gates."

## 2. Keys (Production tab)
- [ ] Client ID:  ____________________  \u2192 goes to config.yaml
      `oauth.quickbooks.client_id` or env `ANTON_QBO_CLIENT_ID`
- [ ] Client Secret: ____________________  \u2192 `oauth.quickbooks.client_secret`
      or env `ANTON_QBO_CLIENT_SECRET`
- Deployment note: these two values are the ONLY vendor secrets any Anton
  install needs. They ship via env/compose \u2014 never committed to git.

## 3. Redirect URIs (Settings \u2192 Redirect URIs)
Add one line PER deployed box (exact match required):
- Dev/testing: `http://localhost:8799/api/wizard/oauth/callback`
- Each customer box: `https://<box-host>/api/wizard/oauth/callback`

Anton serves the callback at `/api/wizard/oauth/callback` on the dashboard
origin \u2014 state-token validated server-side.

## 4. Scopes
- [ ] `com.intuit.quickbooks.accounting` (accounting scope)

## 5. Production review requirements (have these ready BEFORE submitting)
- [ ] Privacy policy URL: ____________________
- [ ] Terms of service URL: ____________________
- [ ] Landing page URL: ____________________
- [ ] Support/contact URL or email: ____________________
- [ ] Company logo (PNG/JPG)
- [ ] EULA acceptance (in-portal)

## 6. Review questionnaire answers (draft language)
- Data storage: "All QuickBooks tokens are stored AES-GCM encrypted in a
  local credential broker; refresh tokens rotate automatically; access is
  restricted by role-based accounts."
- Data use: "Tokens are used solely to read/write the connected company's
  QuickBooks data on behalf of its authorized users, gated behind explicit
  human approvals for money-movement and outbound actions."
- User consent: "Each customer authorizes per-company via Intuit's hosted
  OAuth consent screen."

## 7. After approval
- [ ] Flip app to Production in portal
- [ ] Set the client ID/secret env values on each customer install
- [ ] Operator clicks Connect QuickBooks \u2192 signs in \u2192 done
