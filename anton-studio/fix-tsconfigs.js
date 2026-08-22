import fs from 'fs'

const pkgs = [
  'ui-ops-now',
  'ui-ops-automations',
  'ui-ops-approvals',
  'ui-ops-schedule',
  'ui-ops-memory',
  'ui-ops-learning',
  'ui-ops-alerts',
  'ui-ops-addons',
  'ui-ops-setup'
]

const sidebarTsConfig = JSON.parse(fs.readFileSync('packages/client/ui-sidebar/tsconfig.json', 'utf8'))
const references = sidebarTsConfig.references

for (const pkg of pkgs) {
  const tsconfigPath = `packages/client/${pkg}/tsconfig.json`
  const tsconfig = JSON.parse(fs.readFileSync(tsconfigPath, 'utf8'))
  tsconfig.references = references
  fs.writeFileSync(tsconfigPath, JSON.stringify(tsconfig, null, 2))
}
