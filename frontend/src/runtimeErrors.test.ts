import { describe, expect, it } from 'vitest'
import { summarizeRuntimeError } from './runtimeErrors'

describe('runtime error summaries', () => {
  it('puts the actionable dependency failure before technical noise', () => {
    const error = `The generated backend exited during startup.
Runtime note: memory rlimit is unsupported on this macOS host; continuing without it (non-fatal).
Traceback (most recent call last):
  File "/workspace/main.py", line 4, in <module>
ImportError: email-validator is not installed, run pip install 'pydantic[email]'`
    expect(summarizeRuntimeError(error)).toBe("ImportError: email-validator is not installed, run pip install 'pydantic[email]'")
  })

  it('finds a missing module instead of presenting the macOS warning as the failure', () => {
    const error = `Runtime note: memory rlimit is unsupported on this macOS host; continuing without it (non-fatal).
/app/python: No module named uvicorn`
    expect(summarizeRuntimeError(error)).toBe('/app/python: No module named uvicorn')
  })

  it('preserves a concise API error unchanged', () => {
    expect(summarizeRuntimeError('The application backend did not respond in time.')).toBe('The application backend did not respond in time.')
  })
})
