// frontend/vite.config.ts
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Same proxy for `vite` (dev) and `vite preview` (prod static serve behind a
// single port). The prod deploy serves the built app via `vite preview` and
// relies on `preview.proxy` to forward API calls to the local backend.
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
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    exclude: ['**/node_modules/**', '**/tests/e2e/**'],
  },
})
