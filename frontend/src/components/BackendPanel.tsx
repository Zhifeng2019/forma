import { useCallback, useEffect, useState } from 'react'
import { Activity, CheckCircle2, Database, FileText, Globe2, RefreshCw, RotateCcw, Server } from 'lucide-react'
import { api } from '../api'
import type { Project, RuntimeState } from '../types'

export function BackendPanel({ project, onChanged }: { project: Project; onChanged: () => void }) {
  const [state, setState] = useState<RuntimeState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sourcePath, setSourcePath] = useState('backend/main.py')
  const load = useCallback(async (check = false) => {
    try {
      const next = await api<RuntimeState>(`/projects/${project.id}/runtime${check ? '?check=true' : ''}`)
      setState(next); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }, [project.id])
  useEffect(() => { void load(true) }, [load, project.current_version])

  const restart = async () => {
    setBusy(true); setError('')
    try {
      const next = await api<RuntimeState>(`/projects/${project.id}/runtime/restart`, { method: 'POST' })
      setState(next); onChanged()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason)); await load()
    } finally { setBusy(false) }
  }
  const source = project.artifacts.find(artifact => artifact.path === sourcePath)
  const healthy = state?.status === 'running' && state.healthy
  return <div className="backend-view">
    <section className="runtime-overview">
      <header><div className="runtime-title"><span><Server size={21} /></span><div><span className="eyebrow">DEDICATED APPLICATION SERVICE</span><h2>FastAPI backend</h2></div></div><span className={`runtime-status ${healthy ? 'healthy' : state?.status || ''}`}><i />{state ? state.status === 'running' && state.healthy ? 'Healthy' : state.status : 'Checking…'}</span></header>
      <p className="architecture-reason">{project.backend_reason || 'A dedicated Python API for this application.'}</p>
      <div className="runtime-facts"><div><Activity size={16} /><span>Runtime<strong>{state?.status === 'running' ? 'On-demand process' : 'Starts on request'}</strong></span></div><div><Database size={16} /><span>Environment<strong>Per-app Python + SQLite</strong></span></div><div><Globe2 size={16} /><span>API contract<strong>/api/health · v{project.current_version || '—'}</strong></span></div></div>
      <div className="runtime-actions"><button className="button secondary" onClick={() => void load(true)} disabled={busy || !project.current_version}><RefreshCw size={14} />Check health</button><button className="button primary" onClick={restart} disabled={busy || !project.current_version}><RotateCcw className={busy ? 'spin' : ''} size={14} />{busy ? 'Restarting…' : 'Restart preview'}</button></div>
      {state?.started_at && <small className="runtime-started">Preview started {new Date(state.started_at).toLocaleString()} · Published versions run independently.</small>}
      {state?.last_error && <div className="runtime-error">{state.last_error}</div>}
      {error && <div className="runtime-error">{error}</div>}
    </section>
    <section className="runtime-workspace">
      <div className="runtime-log"><header><span><Activity size={14} />Runtime output</span><small>Latest 60 lines</small></header><pre>{state?.logs || 'The runtime log will appear after the first API request. Open the preview to start the backend on demand.'}</pre></div>
      <div className="backend-source"><nav><button className={sourcePath === 'backend/main.py' ? 'active' : ''} onClick={() => setSourcePath('backend/main.py')}><FileText size={14} />main.py</button><button className={sourcePath === 'backend/requirements.txt' ? 'active' : ''} onClick={() => setSourcePath('backend/requirements.txt')}><FileText size={14} />requirements.txt</button></nav><pre><code>{source?.content || 'Backend source will appear after the first build phase.'}</code></pre></div>
    </section>
    <footer className="runtime-footnote"><CheckCircle2 size={14} /><p>Each version has immutable source. Preview and published processes are separate, and dependencies are pinned. Published APIs are reachable by anyone with the app URL; do not use sensitive data until product-level authentication is added.</p></footer>
  </div>
}
