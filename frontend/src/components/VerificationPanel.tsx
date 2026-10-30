import { useState } from 'react'
import { AlertTriangle, CheckCircle2, Clock3, Download, LoaderCircle, Play, ShieldCheck, Sparkles, XCircle } from 'lucide-react'
import { getToken } from '../api'
import type { Project, VerificationCheck } from '../types'
import './VerificationReview.css'

function duration(value: number) {
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`
}

function ArtifactButton({ projectId, version, path, kind, label }: {
  projectId: string; version: number; path: string; kind: 'diagnostics' | 'evidence'; label: string
}) {
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const download = async () => {
    setBusy(true); setError('')
    try {
      const token = getToken()
      const response = await fetch(
        `/api/projects/${projectId}/verification/${kind}?path=${encodeURIComponent(path)}&version=${version}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      )
      if (!response.ok) throw new Error('The verification artifact is unavailable.')
      const url = URL.createObjectURL(await response.blob())
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = path.split('/').pop() || 'verification-artifact'
      document.body.append(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The verification artifact is unavailable.')
    } finally {
      setBusy(false)
    }
  }
  return <span className="artifact-action"><button type="button" className="button ghost artifact-button" disabled={busy} onClick={download}><Download size={12} />{busy ? 'Downloading…' : label}</button>{error && <small className="artifact-error" role="alert">{error}</small>}</span>
}

function CheckStatus({ status }: { status: VerificationCheck['status'] }) {
  if (status === 'passed') return <CheckCircle2 className="check-passed" size={15} />
  if (status === 'failed') return <XCircle className="check-failed" size={15} />
  return <AlertTriangle className="check-blocked" size={15} />
}

export function VerificationPanel({ project, onVerify, busy }: {
  project: Project; onVerify: (includeOptional: boolean, includeReview?: boolean) => void; busy: boolean
}) {
  const report = project.verification
  const running = Boolean(project.verification_running)
  const canRun = Boolean(project.current_version && project.appspec && project.appspec_valid !== false && !busy)
  return <div className="verification-view">
    <header className="verification-heading"><div><span className="eyebrow">DETERMINISTIC VERIFICATION</span><h2>Evidence before release.</h2><p>Results come from builds, API calls, browser checks, and security inspection—not model review.</p></div><div className="verification-actions"><button className="button secondary" disabled={!canRun} onClick={() => onVerify(false)}>{busy ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}Verify application</button><button className="button ghost" disabled={!canRun} onClick={() => onVerify(true)} title="Also run migration and republishing checks on this application">Include migration checks</button>{project.specialist_workers_enabled && <button className="button ghost" disabled={!canRun} onClick={() => onVerify(false, true)} title="Generate optional model suggestions. This does not affect the release decision."><Sparkles size={14} />Advisory AI review</button>}</div></header>
    {!project.appspec && <div className="empty-state"><span><ShieldCheck size={27} /></span><h3>AppSpec is required for verification</h3><p>Enable AppSpec and build a version to generate a typed contract and acceptance checks.</p></div>}
    {running && <div className="verification-running" aria-live="polite"><LoaderCircle className="spin" size={17} /><div><strong>Verification is running</strong><p>Build, runtime, browser, and security checks are executing. You can review the latest completed report below.</p></div></div>}
    {!report && !running && project.appspec && <div className="empty-state"><span><ShieldCheck size={27} /></span><h3>No verification report yet</h3><p>Run deterministic verification to evaluate this application before publishing.</p></div>}
    {report && <>
      <section className={`verification-summary ${report.status}`} aria-live="polite"><div className="verification-status-icon">{report.status === 'passed' ? <CheckCircle2 size={22} /> : report.status === 'failed' ? <XCircle size={22} /> : <AlertTriangle size={22} />}</div><div><span className="eyebrow">ATTEMPT {report.attempt_id}</span><h3>{report.status === 'passed' ? 'All required checks passed' : report.status === 'failed' ? 'Verification failed' : 'Passed with warnings'}</h3><p>{report.can_publish ? 'This version is ready to publish.' : report.complete_coverage ? 'This version is not ready to publish.' : 'Full required-check coverage is required before publishing.'}</p></div><div className="verification-score"><strong>{report.summary.passed} / {report.summary.total}</strong><span>checks passed</span></div></section>
      <div className="verification-facts"><span><Clock3 size={13} />{duration(report.duration_ms)}</span><span>Coverage {report.complete_coverage ? 'Complete' : 'Partial'}</span><span>Spec {report.spec_hash.slice(0, 12)}</span><span>Source {report.source_hash.slice(0, 12)}</span></div>
      {report.summary.required_failures.length > 0 && <div className="verification-failures"><strong>Required failures</strong><ul>{report.summary.required_failures.map(id => <li key={id}>{id}</li>)}</ul></div>}
      {report.summary.optional_failures.length > 0 && <div className="verification-warnings"><strong>Optional failures</strong><ul>{report.summary.optional_failures.map(id => <li key={id}>{id}</li>)}</ul></div>}
      {report.review && <section className={`model-review ${report.review.status}`}><header><span className="model-review-icon"><Sparkles size={17} /></span><div><h3>Advisory model review</h3><p>Suggestions only. This review does not affect verification or release decisions.</p></div><span className="model-review-status">{report.review.status}</span></header>{report.review.summary && <p className="model-review-summary">{report.review.summary}</p>}{report.review.error && <p className="verification-error">{report.review.error}</p>}{report.review.suggestions.length > 0 && <ul className="model-suggestions">{report.review.suggestions.map((suggestion, index) => <li key={`${suggestion.title}-${index}`}><span className={`model-severity ${suggestion.severity}`}>{suggestion.severity}</span><div><strong>{suggestion.title}</strong><p>{suggestion.detail}</p>{suggestion.target && <code>{suggestion.target}</code>}</div></li>)}</ul>}</section>}
      <section className="verification-checks"><header><h3>Check results</h3><span>{report.checks.length} checks</span></header>{report.checks.map(check => <article className={`verification-check ${check.status}`} key={`${check.tool_run_id}-${check.id}`}><span className="verification-check-icon"><CheckStatus status={check.status} /></span><div className="verification-check-main"><div className="verification-check-title"><strong>{check.id}</strong><span className={`check-kind ${check.status}`}>{check.status}</span>{check.required ? <span className="check-required">required</span> : <span className="check-optional">optional</span>}{check.mutates && <span className="check-mutates">mutates</span>}</div><div className="verification-check-meta"><span>{check.kind}</span><code>{check.target}</code><span>{duration(check.duration_ms)}</span></div><small>Tool: {check.output_ref}</small><div className="verification-artifacts">{check.diagnostic_ref && <ArtifactButton projectId={project.id} version={report.version} path={check.diagnostic_ref} kind="diagnostics" label="Download full log" />}{check.evidence?.map((item, index) => <ArtifactButton key={item.path} projectId={project.id} version={report.version} path={item.path} kind="evidence" label={`Download screenshot ${index + 1}`} />)}</div>{check.error && <p className="verification-error">{check.error}</p>}</div></article>)}</section>
    </>}
  </div>
}
