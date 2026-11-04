import { systemText, statusLabel } from '../systemMessages'
import { t, useTranslation, locale, formatNumber } from '../i18n'
import { useEffect, useState } from 'react'
import { Activity, Clock3, Cpu, DollarSign, Fingerprint, HeartPulse } from 'lucide-react'
import { api } from '../api'
import type { UsageMetrics, UsageReport } from '../usage'
import './UsagePanel.css'

function duration(value: number) {
  if (value < 1000) return t("{{value}} ms", { value: formatNumber(value) })
  if (value < 60_000) return t("{{value}} s", { value: formatNumber(value / 1000, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) })
  return t("{{value}} min", { value: formatNumber(value / 60_000, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) })
}

function tokens(value: number | null) {
  return value === null ? '—' : formatNumber(value)
}

function cost(metrics: Pick<UsageMetrics, 'cost_status' | 'estimated_cost' | 'currency'>) {
  if (metrics.cost_status === 'unknown' || metrics.estimated_cost === null) return t("Unknown")
  const value = metrics.estimated_cost
  const formatted = metrics.currency
    ? new Intl.NumberFormat(locale(), { style: 'currency', currency: metrics.currency, maximumFractionDigits: 6 }).format(value)
    : value.toString()
  return metrics.cost_status === "partial" ? t("Partial {{amount}}", { amount: formatted }) : formatted
}

function hashes(values: string[]) {
  return values.length ? values.map(value => value.slice(0, 12)).join(', ') : t("Not recorded")
}

export function UsageReportView({ report, error = '' }: { report: UsageReport; error?: string }) {
  const { t } = useTranslation()
  const { summary } = report
  return <section className="usage-panel" aria-label={t("Usage and provenance")}>
    <header className="usage-heading"><div><span className="eyebrow">{t("USAGE & PROVENANCE")}</span><h2>{t("Work, measured honestly.")}</h2><p>{t("Provider observations and deterministic tool evidence. Unknown values are never treated as zero.")}</p></div><span className={`runtime-status ${summary.runtime_health}`}><HeartPulse size={13} />{statusLabel(summary.runtime_health)}</span></header>
    {error && <p className="usage-error">{systemText(error)}</p>}
    <div className="usage-summary">
      <article><span><Cpu size={15} /></span><div><small>{t("Model tokens · {{status}}", { status: statusLabel(summary.token_status) })}</small><strong>{tokens(summary.total_tokens)}</strong><p>{t("{{input}} in · {{output}} out", { input: tokens(summary.input_tokens), output: tokens(summary.output_tokens) })}</p></div></article>
      <article><span><DollarSign size={15} /></span><div><small>{t("Cost · {{status}}", { status: statusLabel(summary.cost_status) })}</small><strong>{cost(summary)}</strong><p>{t("Provider price snapshots")}</p></div></article>
      <article><span><Activity size={15} /></span><div><small>{t("Tool activity")}</small><strong>{summary.tool_run_count}</strong><p>{t("{{jobs}} jobs · {{retries}} retries", { jobs: formatNumber(summary.job_count), retries: formatNumber(summary.retry_count) })}</p></div></article>
      <article><span><Clock3 size={15} /></span><div><small>{t("Total tool time")}</small><strong>{duration(summary.duration_ms)}</strong><p>{t("{{count}} observed requests", { count: summary.request_count })}</p></div></article>
    </div>
    <div className="usage-provenance"><span><Fingerprint size={12} />{t("Spec")} {hashes(summary.spec_hashes)}</span><span>{t("Source")} {hashes(summary.source_hashes)}</span></div>
    {!report.jobs.length && <div className="usage-empty"><Activity size={22} /><p>{t("No durable jobs yet. Usage appears after generation begins.")}</p></div>}
    <div className="usage-jobs">{report.jobs.map(job => <details className="usage-job" key={job.job_id} open>
      <summary><span className={`usage-status ${job.status}`}>{statusLabel(job.status)}</span><strong>{statusLabel(job.stage)}</strong><span>{t("Attempt {{count}}", { count: job.current_attempt })}</span><span>{t("{{count}} tools", { count: job.tool_run_count })}</span><span>{t("{{value}} tokens", { value: tokens(job.total_tokens) })}</span><span>{cost(job)}</span><span>{duration(job.duration_ms)}</span></summary>
      <div className="usage-job-body">
        <div className="usage-job-facts"><span>{t("Runtime")} {statusLabel(job.runtime_health)}</span><span>{t("{{count}} model requests", { count: job.request_count })}</span><span>{t("{{count}} retries", { count: job.retry_count })}</span><span>{t("Spec")} {hashes(job.spec_hashes)}</span><span>{t("Source")} {hashes(job.source_hashes)}</span></div>
        {!job.tool_runs.length && <p className="usage-muted">{t("No tool runs are recorded for this job.")}</p>}
        <div className="usage-tools">{job.tool_runs.map(run => <article className="usage-tool" key={run.id}>
          <header><div><strong>{run.tool_name}</strong><small>{run.tool_version}</small></div><span className={`usage-status ${run.status}`}>{statusLabel(run.status)}</span></header>
          <div className="usage-tool-meta"><span>{duration(run.duration_ms)}</span><span>{t("Retry {{count}}", { count: run.retry_count })}</span><span>{t("Attempt {{count}}", { count: run.attempt_id })}</span>{typeof run.provenance.cache_hit === 'boolean' && <span>{run.provenance.cache_hit ? t("Cache hit") : t("Cache miss")}</span>}</div>
          {run.usage && <div className="usage-model"><strong>{run.usage.provider} · {run.usage.model}</strong><span>{t("{{status}} tokens: {{value}}", { status: statusLabel(run.usage.usage_status), value: tokens(run.usage.total_tokens) })}</span><span>{cost(run.usage)}</span>{run.usage.provider_request_id && <code>{run.usage.provider_request_id}</code>}</div>}
          <div className="usage-tool-hashes">{Boolean(run.provenance.spec_hash) && <span>{t("Spec")} {String(run.provenance.spec_hash).slice(0, 12)}</span>}{Boolean(run.provenance.source_hash) && <span>{t("Source")} {String(run.provenance.source_hash).slice(0, 12)}</span>}</div>
        </article>)}</div>
      </div>
    </details>)}</div>
  </section>
}

export function UsagePanel({ projectId, updatedAt }: { projectId: string; updatedAt: string }) {
  const { t } = useTranslation()
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

  if (loading && !report) return <section className="usage-panel"><p className="usage-muted">{t("Loading usage and provenance…")}</p></section>
  if (error && !report) return <section className="usage-panel"><p className="usage-error">{systemText(error)}</p></section>
  return report ? <UsageReportView report={report} error={systemText(error)} /> : null
}
