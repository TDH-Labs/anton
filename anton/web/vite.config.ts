import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into anton/web/dist and served by FastAPI's StaticFiles mount, so
// assets resolve from the app root rather than a CDN. The dev server proxies
// /api to a locally running `anton dashboard` so the real endpoints back the
// UI during development instead of fixtures.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8799', changeOrigin: true } },
  },
})
