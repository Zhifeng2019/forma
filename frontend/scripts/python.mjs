import { existsSync } from 'node:fs'
import path from 'node:path'

// PYTHON wins; otherwise prefer a project virtual environment, then the system interpreter.
export function studioPython(backendRoot) {
  if (process.env.PYTHON) return process.env.PYTHON
  const candidates = [
    path.join(backendRoot, '.venv', 'bin', 'python'),
    '/Users/zhifengzhang/python_env/env_ai_build/bin/python',
  ]
  return candidates.find(candidate => existsSync(candidate)) || 'python3'
}
