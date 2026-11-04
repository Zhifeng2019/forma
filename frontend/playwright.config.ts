import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const backendPort = Number(process.env.FORMA_TEST_BACKEND_PORT || 8000)
const frontendPort = Number(process.env.FORMA_TEST_FRONTEND_PORT || 5173)
const backendUrl = `http://127.0.0.1:${backendPort}`
const production = process.env.FORMA_TEST_PRODUCTION === '1'
const frontendUrl = production ? backendUrl : `http://127.0.0.1:${frontendPort}`
const testDataDir = process.env.FORMA_TEST_DATA_DIR || mkdtempSync(path.join(tmpdir(), 'forma-browser-test-'))
process.env.FORMA_TEST_DATA_DIR = testDataDir
const reuseExistingServer = false

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  use: { baseURL: frontendUrl, viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: [
    {
      command: `/Users/zhifengzhang/python_env/env_ai_build/bin/python -m uvicorn browser_app:app --app-dir tests --host 127.0.0.1 --port ${backendPort}`,
      cwd: '../backend', url: `${backendUrl}/api/health`, reuseExistingServer, timeout: 30_000,
      env: { DATA_DIR: testDataDir, FORMA_TEST_DATA_DIR: testDataDir, STUDIO_BASE_URL: backendUrl, APPS_BASE_URL: `http://apps.localhost:${backendPort}`, CORS_ORIGINS: frontendUrl },
    },
    ...(!production ? [{
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort}`,
      cwd: '.', url: frontendUrl, reuseExistingServer, timeout: 30_000,
      env: { FORMA_BACKEND_URL: backendUrl },
    }] : []),
  ],
})
