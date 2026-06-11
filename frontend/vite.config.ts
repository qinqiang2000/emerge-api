// frontend/vite.config.ts
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Shared proxy for local `vite` (dev) and `vite preview`. In prod the built
// `dist/` is served by nginx (see deploy.sh → emerge.conf), which owns the
// static caching + API proxy there; this block only matters for local runs.
const apiProxy = {
  '/lab': { target: 'http://localhost:8080', changeOrigin: true },
  '/v1': { target: 'http://localhost:8080', changeOrigin: true },
  '/auth': { target: 'http://localhost:8080', changeOrigin: true },
  '/healthz': { target: 'http://localhost:8080', changeOrigin: true },
}

export default defineConfig({
  plugins: [react()],
  // excalidraw (board) reads process.env.IS_PREACT at runtime; Vite doesn't
  // polyfill process — define it or the canvas crashes on mount.
  define: { 'process.env.IS_PREACT': JSON.stringify('false') },
  resolve: {
    alias: {
      // Audit-board geometry single source — lives with the backend skills
      // because board_app.html injects the same file verbatim at serve time.
      // Classic script, side-effect import only (assigns globalThis.BoardGeom);
      // types in src/components/Board/board-geometry.d.ts. Vitest shares this
      // config (`defineConfig` from vitest/config above), so no second alias.
      '@board-geometry': fileURLToPath(
        new URL('../backend/app/skills/board_geometry.js', import.meta.url),
      ),
    },
  },
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
  build: {
    rollupOptions: {
      output: {
        // Pin React/ReactDOM into their own chunk. They change far less often
        // than app code, so this chunk stays cached (its content hash holds)
        // across deploys even when feature code churns.
        manualChunks(id) {
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) {
            return 'react-vendor'
          }
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    exclude: ['**/node_modules/**', '**/tests/e2e/**'],
  },
})
