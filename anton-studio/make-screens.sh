for name in ui-ops-now ui-ops-automations ui-ops-approvals ui-ops-schedule ui-ops-memory ui-ops-learning ui-ops-alerts ui-ops-addons ui-ops-setup; do
  mkdir -p packages/client/$name/src/client
  
  cat << PKG > packages/client/$name/package.json
{
  "name": "@deepseek-ai/dsh-client-$name",
  "version": "0.1.0-rc.8",
  "private": true,
  "type": "module",
  "exports": {
    "./client": {
      "import": "./lib/client/index.js",
      "types": "./lib/types/client/index.d.ts"
    }
  },
  "dependencies": {
    "@deepseek-ai/cordis": "workspace:*",
    "@deepseek-ai/dsh-client-runtime": "workspace:*"
  },
  "peerDependencies": {
    "react": "^18.3.1"
  }
}
PKG

  cat << TS > packages/client/$name/tsconfig.json
{
  "extends": "../../../tsconfig.client.json",
  "compilerOptions": {
    "rootDir": "src",
    "outDir": "lib/types",
    "declarationDir": "lib/types"
  },
  "include": ["src/**/*"]
}
TS

  cat << IDX > packages/client/$name/src/client/index.ts
import { type ClientContext } from '@deepseek-ai/dsh-client-runtime/client'

export const inject = ['slots']

export function apply(ctx: ClientContext): void {
  // Skeleton implementation for $name
}
IDX

done
