import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

const backendPort = Number(process.env.FORMA_TEST_BACKEND_PORT || 8129)
const proxyPort = Number(process.env.FORMA_TEST_PROXY_PORT || 8130)
const backendUrl = `http://127.0.0.1:${backendPort}`
process.env.FORMA_TEST_BACKEND_URL = backendUrl
process.env.FORMA_TEST_STUDIO_PREFIX = '/forma'
const publicUrl = `http://127.0.0.1:${proxyPort}`
const python = process.env.FORMA_TEST_PYTHON || 'python'
const data = process.env.FORMA_TEST_DATA_DIR || mkdtempSync(path.join(tmpdir(), 'forma-subpath-test-'))
process.env.FORMA_TEST_DATA_DIR = data

export default defineConfig({
  testDir: './e2e', testMatch: ['**/*.subpath.ts', '**/i18n.spec.ts'], workers: 1, timeout: 90_000,
  use: { baseURL: publicUrl, viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: [
    {
      command: `"${python}" -m uvicorn browser_app:app --app-dir tests --host 127.0.0.1 --port ${backendPort}`,
      cwd: '../backend', url: `${backendUrl}/api/health`, reuseExistingServer: false,
      env: { DATA_DIR: data, FORMA_TEST_DATA_DIR: data, STUDIO_BASE_URL: publicUrl, STUDIO_PATH_PREFIX: '/forma',
        CORS_ORIGINS: `${publicUrl},${backendUrl}`, APPS_BASE_URL: `http://apps.localhost:${backendPort}`,
        DURABLE_JOBS_V1: 'true', ACCEPTANCE_GATE_V1: 'false', SANDBOX_V1: 'false' },
    },
    {
      command: 'node e2e/subpath-proxy.mjs', url: `${publicUrl}/forma/api/health`, reuseExistingServer: false,
      env: { FORMA_TEST_BACKEND_PORT: String(backendPort), FORMA_TEST_PROXY_PORT: String(proxyPort) },
    },
  ],
})
