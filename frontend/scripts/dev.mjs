import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backendRoot = path.resolve(frontendRoot, '../backend')
const python = process.env.PYTHON || '/Users/zhifengzhang/python_env/env_ai_build/bin/python'
let backend

try {
  const health = await fetch('http://127.0.0.1:8000/api/health', { signal: AbortSignal.timeout(800) })
  if (!health.ok) throw new Error('Backend unavailable')
} catch {
  backend = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], {
    cwd: backendRoot,
    stdio: 'inherit',
    env: process.env,
  })
}

const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', ...process.argv.slice(2)], {
  cwd: frontendRoot,
  stdio: 'inherit',
  env: process.env,
})

const shutdown = () => {
  vite.kill('SIGTERM')
  backend?.kill('SIGTERM')
}
process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)
vite.on('exit', code => {
  backend?.kill('SIGTERM')
  process.exit(code ?? 0)
})
backend?.on('exit', code => {
  if (code && code !== 0) {
    console.error(`FastAPI stopped unexpectedly (${code}).`)
    vite.kill('SIGTERM')
  }
})
