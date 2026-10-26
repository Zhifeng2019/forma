const NOISE = /^(Traceback|File\s|During handling|Runtime note:|Starting FastAPI|Health check passed|INFO:|WARNING:|The generated backend exited during startup)/i
const ACTIONABLE = /(error|exception|failed|not installed|no module named|timed out|unavailable|invalid|could not|missing|unsupported)/i

export function summarizeRuntimeError(value: string): string {
  const lines = value.split('\n').map(line => line.trim()).filter(Boolean)
  const useful = lines.filter(line => !NOISE.test(line))
  const actionable = [...useful].reverse().find(line => ACTIONABLE.test(line))
  const summary = actionable || useful.at(-1) || 'The backend could not start. Review the technical details for more information.'
  return summary.length > 280 ? `${summary.slice(0, 277)}…` : summary
}
