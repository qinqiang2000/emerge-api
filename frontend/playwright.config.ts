import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5172',
    // Bypass any system HTTP proxy for localhost — required for SSE streaming.
    launchOptions: { args: ['--proxy-server=direct://'] },
  },
  webServer: [
    {
      command: 'rm -rf ../backend/.tmp_workspace && EMERGE_TEST_MODE=1 EMERGE_WORKSPACE_ROOT=./.tmp_workspace uv --directory ../backend run python -m tests.e2e_seed && EMERGE_TEST_MODE=1 EMERGE_WORKSPACE_ROOT=./.tmp_workspace uv --directory ../backend run uvicorn app.main:app --port 8080',
      url: 'http://127.0.0.1:8080/healthz',
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'npm run dev -- --port 5172',
      url: 'http://127.0.0.1:5172',
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
