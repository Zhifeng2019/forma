import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: [
    {
      command: '/Users/zhifengzhang/python_env/env_ai_build/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000',
      cwd: '../backend', url: 'http://127.0.0.1:8000/api/health', reuseExistingServer: true, timeout: 30_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173',
      cwd: '.', url: 'http://127.0.0.1:5173', reuseExistingServer: true, timeout: 30_000,
    },
  ],
})
