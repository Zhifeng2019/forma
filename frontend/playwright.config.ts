import { defineConfig } from '@playwright/test'

const backendPort = Number(process.env.FORMA_TEST_BACKEND_PORT || 8000)
const frontendPort = Number(process.env.FORMA_TEST_FRONTEND_PORT || 5173)
const backendUrl = `http://127.0.0.1:${backendPort}`
const frontendUrl = `http://127.0.0.1:${frontendPort}`
const isolated = Boolean(process.env.FORMA_TEST_BACKEND_PORT || process.env.FORMA_TEST_FRONTEND_PORT)
const reuseExistingServer = !isolated

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  use: { baseURL: frontendUrl, viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: [
    {
      command: `/Users/zhifengzhang/python_env/env_ai_build/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: '../backend', url: `${backendUrl}/api/health`, reuseExistingServer, timeout: 30_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      cwd: '.', url: frontendUrl, reuseExistingServer, timeout: 30_000,
      env: { FORMA_BACKEND_URL: backendUrl },
    },
  ],
})
