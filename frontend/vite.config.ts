// frontend/vite.config.ts
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
