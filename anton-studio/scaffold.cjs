const fs = require('fs')
const path = require('path')

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

pkgs.forEach(pkg => {
  const dir = path.join('packages/client', pkg)
  fs.mkdirSync(path.join(dir, 'src/client'), { recursive: true })
  
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({
    name: `@deepseek-ai/dsh-client-${pkg}`,
    version: "0.1.0-rc.8",
    private: true,
    type: "module",
    main: "lib/index.js",
    types: "lib/types/index.d.ts",
    exports: {
      ".": {
        "types": "./lib/types/index.d.ts",
        "default": "./lib/index.js"
      },
      "./client": {
        "types": "./lib/types/client/index.d.ts",
        "default": "./lib/client.js"
      }
    },
    dependencies: {
      "clsx": "^2.0.0"
    },
    peerDependencies: {
      "@deepseek-ai/cordis": "workspace:*",
      "@deepseek-ai/dsh-client-runtime": "workspace:*",
      "@deepseek-ai/dsh-client-ui-layout": "workspace:*",
      "react": "^18.2.0"
    }
  }, null, 2))

  fs.writeFileSync(path.join(dir, 'tsconfig.json'), JSON.stringify({
    extends: "../../../tsconfig.base.client.json",
    compilerOptions: { rootDir: "src", outDir: "lib/types" },
    include: ["src"]
  }, null, 2))

  fs.writeFileSync(path.join(dir, 'src/index.ts'), `export function apply(): void {}\n`)

  fs.writeFileSync(path.join(dir, 'src/client/index.ts'), `import { type ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
export const inject = ['slots']
export function apply(ctx: ClientContext): void {
  // ${pkg}
}
`)
})

// update tsconfig.client.json
const clientTsConfigPath = 'tsconfig.client.json'
const clientTsConfig = JSON.parse(fs.readFileSync(clientTsConfigPath, 'utf8'))
pkgs.forEach(pkg => {
  if (!clientTsConfig.references.find(r => r.path === `./packages/client/${pkg}`)) {
    clientTsConfig.references.push({ path: `./packages/client/${pkg}` })
  }
})
fs.writeFileSync(clientTsConfigPath, JSON.stringify(clientTsConfig, null, 2))

// update tsconfig.host.json
const hostTsConfigPath = 'tsconfig.host.json'
const hostTsConfig = JSON.parse(fs.readFileSync(hostTsConfigPath, 'utf8'))
pkgs.forEach(pkg => {
  if (!hostTsConfig.references.find(r => r.path === `./packages/client/${pkg}`)) {
    hostTsConfig.references.push({ path: `./packages/client/${pkg}` })
  }
})
fs.writeFileSync(hostTsConfigPath, JSON.stringify(hostTsConfig, null, 2))

console.log('done scaffolding')
