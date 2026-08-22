for name in ui-ops-now ui-ops-automations ui-ops-approvals ui-ops-schedule ui-ops-memory ui-ops-learning ui-ops-alerts ui-ops-addons ui-ops-setup; do
  mkdir -p packages/client/$name/src/client
  
  cat << PKG > packages/client/$name/package.json
{
  "name": "@deepseek-ai/dsh-client-$name",
  "version": "0.1.0-rc.8",
  "private": true,
  "type": "module",
  "main": "lib/index.js",
  "types": "lib/types/index.d.ts",
  "exports": {
    ".": {
      "types": "./lib/types/index.d.ts",
      "default": "./lib/index.js"
    },
    "./client": {
      "types": "./lib/types/client/index.d.ts",
      "default": "./lib/client.js"
    }
  },
  "dependencies": {
    "clsx": "^2.0.0"
  },
  "peerDependencies": {
    "@deepseek-ai/cordis": "workspace:*",
    "@deepseek-ai/dsh-client-runtime": "workspace:*",
    "@deepseek-ai/dsh-client-ui-layout": "workspace:*",
    "react": "^18.2.0"
  }
}
PKG

  cat << TS > packages/client/$name/tsconfig.json
{
  "extends": "../../../tsconfig.base.client.json",
  "compilerOptions": { "rootDir": "src", "outDir": "lib/types" },
  "include": ["src"]
}
TS

  cat << IDX > packages/client/$name/src/index.ts
export function apply(): void {}
IDX

  cat << CLIDX > packages/client/$name/src/client/index.ts
import { type ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
export const inject = ['slots']
export function apply(ctx: ClientContext): void {}
CLIDX

  sed -i '' -e 's/  \]/    { "path": ".\/packages\/client\/'$name'" },\
  \]/g' tsconfig.client.json

  sed -i '' -e 's/  \]/    { "path": ".\/packages\/client\/'$name'" },\
  \]/g' tsconfig.host.json
done
