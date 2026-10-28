import { useEffect, useState } from 'react'
import { Activity, Clock3, Cpu, DollarSign, Fingerprint, HeartPulse } from 'lucide-react'
import { api } from '../api'
import type { UsageMetrics, UsageReport } from '../usage'
import './UsagePanel.css'

function duration(value: number) {
  if (value < 1000) return `${value} ms`
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`
  return `${(value / 60_000).toFixed(1)} min`
}

function tokens(value: number | null) {
  return value === null ? '—' : value.toLocaleString()
}

function cost(metrics: Pick<UsageMetrics, 'cost_status' | 'estimated_cost' | 'currency'>) {
  if (metrics.cost_status === 'unknown' || metrics.estimated_cost === null) return 'Unknown'
  const value = metrics.estimated_cost
  const formatted = metrics.currency
    ? new Intl.NumberFormat('en-US', { style: 'currency', currency: metrics.currency, maximumFractionDigits: 6 }).format(value)
    : value.toString()
  return `${metrics.cost_status === 'partial' ? 'Partial ' : ''}${formatted}`
}

function hashes(values: string[]) {
  return values.length ? values.map(value => value.slice(0, 12)).join(', ') : 'Not recorded'
}

export function UsageReportView({ report, error = '' }: { report: UsageReport; error?: string }) {
  const { summary } = report
  return <section className="usage-panel" aria-label="Usage and provenance">
    <header className="usage-heading"><div><span className="eyebrow">USAGE & PROVENANCE</span><h2>Work, measured honestly.</h2><p>Provider observations and deterministic tool evidence. Unknown values are never treated as zero.</p></div><span className={`runtime-status ${summary.runtime_health}`}><HeartPulse size={13} />{summary.runtime_health}</span></header>
    {error && <p className="usage-error">{error}</p>}
    <div className="usage-summary">
      <article><span><Cpu size={15} /></span><div><small>Model tokens · {summary.token_status}</small><strong>{tokens(summary.total_tokens)}</strong><p>{tokens(summary.input_tokens)} in · {tokens(summary.output_tokens)} out</p></div></article>
      <article><span><DollarSign size={15} /></span><div><small>Cost · {summary.cost_status}</small><strong>{cost(summary)}</strong><p>Provider price snapshots</p></div></article>
      <article><span><Activity size={15} /></span><div><small>Tool activity</small><strong>{summary.tool_run_count}</strong><p>{summary.job_count} jobs · {summary.retry_count} retries</p></div></article>
      <article><span><Clock3 size={15} /></span><div><small>Total tool time</small><strong>{duration(summary.duration_ms)}</strong><p>{summary.request_count} observed requests</p></div></article>
    </div>
    <div className="usage-provenance"><span><Fingerprint size={12} />Spec {hashes(summary.spec_hashes)}</span><span>Source {hashes(summary.source_hashes)}</span></div>
    {!report.jobs.length && <div className="usage-empty"><Activity size={22} /><p>No durable jobs yet. Usage appears after generation begins.</p></div>}
    <div className="usage-jobs">{report.jobs.map(job => <details className="usage-job" key={job.job_id} open>
      <summary><span className={`usage-status ${job.status}`}>{job.status}</span><strong>{job.stage}</strong><span>Attempt {job.current_attempt}</span><span>{job.tool_run_count} tools</span><span>{tokens(job.total_tokens)} tokens</span><span>{cost(job)}</span><span>{duration(job.duration_ms)}</span></summary>
      <div className="usage-job-body">
        <div className="usage-job-facts"><span>Runtime {job.runtime_health}</span><span>{job.request_count} model requests</span><span>{job.retry_count} retries</span><span>Spec {hashes(job.spec_hashes)}</span><span>Source {hashes(job.source_hashes)}</span></div>
        {!job.tool_runs.length && <p className="usage-muted">No tool runs are recorded for this job.</p>}
        <div className="usage-tools">{job.tool_runs.map(run => <article className="usage-tool" key={run.id}>
          <header><div><strong>{run.tool_name}</strong><small>{run.tool_version}</small></div><span className={`usage-status ${run.status}`}>{run.status}</span></header>
          <div className="usage-tool-meta"><span>{duration(run.duration_ms)}</span><span>Retry {run.retry_count}</span><span>Attempt {run.attempt_id}</span>{typeof run.provenance.cache_hit === 'boolean' && <span>{run.provenance.cache_hit ? 'Cache hit' : 'Cache miss'}</span>}</div>
          {run.usage && <div className="usage-model"><strong>{run.usage.provider} · {run.usage.model}</strong><span>{run.usage.usage_status} tokens: {tokens(run.usage.total_tokens)}</span><span>{cost(run.usage)}</span>{run.usage.provider_request_id && <code>{run.usage.provider_request_id}</code>}</div>}
          <div className="usage-tool-hashes">{Boolean(run.provenance.spec_hash) && <span>Spec {String(run.provenance.spec_hash).slice(0, 12)}</span>}{Boolean(run.provenance.source_hash) && <span>Source {String(run.provenance.source_hash).slice(0, 12)}</span>}</div>
        </article>)}</div>
      </div>
    </details>)}</div>
  </section>
}

export function UsagePanel({ projectId, updatedAt }: { projectId: string; updatedAt: string }) {
  const [report, setReport] = useState<UsageReport | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let active = true
    api<UsageReport>(`/projects/${projectId}/usage`).then(data => {
      if (active) { setReport(data); setError('') }
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : String(reason))
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [projectId, updatedAt])

  if (loading && !report) return <section className="usage-panel"><p className="usage-muted">Loading usage and provenance…</p></section>
  if (error && !report) return <section className="usage-panel"><p className="usage-error">{error}</p></section>
  return report ? <UsageReportView report={report} error={error} /> : null
}
