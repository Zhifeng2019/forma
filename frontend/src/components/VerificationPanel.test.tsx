import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { VerificationPanel } from './VerificationPanel'
import type { Project, VerificationReport } from '../types'

const report: VerificationReport = {
  schema_version: '1.0', project_id: 'project-1', version: 1, job_id: 'job-1', attempt_id: 1,
  spec_hash: 'a'.repeat(64), source_hash: 'b'.repeat(64), status: 'passed',
  can_publish: true, complete_coverage: true,
  summary: { total: 1, passed: 1, failed: 0, blocked: 0, skipped: 0, required_failures: [], optional_failures: [] },
  started_at: '2026-01-01T00:00:00Z', ended_at: '2026-01-01T00:00:01Z', duration_ms: 1000,
  checks: [{
    id: 'api.health', kind: 'api', target: '/api/health', status: 'passed', required: true,
    mutates: false, tool_run_id: 'tool-1', duration_ms: 5,
    output_ref: 'acceptance/api_tests.py#test_health',
  }],
}

const project: Project = {
  id: 'project-1', name: 'Verified App', brief: 'A verified application.', description: '',
  stage: 'review', stage_index: 4, phase_index: 3, status: 'ready', auto_mode: false, current_version: 1,
  backend_mode: 'static', backend_reason: 'Browser state', backend_enabled: false, source_format: 'single-file',
  published_version: null, created_at: '', updated_at: '', messages: [], versions: [], events: [], artifacts: [],
  appspec_enabled: true, appspec: { spec: {} } as unknown as Project['appspec'], appspec_valid: true,
  verification: report, verification_running: false,
}

function withReport(changes: Partial<VerificationReport>): VerificationReport {
  return { ...report, ...changes }
}

describe('VerificationPanel', () => {
  it('shows a successful report and tool references', () => {
    const html = renderToStaticMarkup(<VerificationPanel project={project} onVerify={() => {}} busy={false} />)
    expect(html).toContain('All required checks passed')
    expect(html).toContain('ready to publish')
    expect(html).toContain('api.health')
    expect(html).toContain('acceptance/api_tests.py#test_health')
    expect(html).toContain('Coverage Complete')
  })

  it('shows failed checks and actionable errors', () => {
    const failed = withReport({
      status: 'failed', can_publish: false,
      summary: { ...report.summary, passed: 0, failed: 1, required_failures: ['api.health'] },
      checks: [{ ...report.checks[0], status: 'failed', error: 'Health check failed' }],
    })
    const html = renderToStaticMarkup(<VerificationPanel project={{ ...project, verification: failed }} onVerify={() => {}} busy={false} />)
    expect(html).toContain('Verification failed')
    expect(html).toContain('api.health')
    expect(html).toContain('Health check failed')
    expect(html).toContain('not ready to publish')
  })

  it('shows warning, empty, and running states', () => {
    const warning = withReport({
      status: 'passed_with_warnings',
      summary: { ...report.summary, optional_failures: ['migration.republish-preserves-history'] },
    })
    const warningHtml = renderToStaticMarkup(<VerificationPanel project={{ ...project, verification: warning }} onVerify={() => {}} busy={false} />)
    expect(warningHtml).toContain('Passed with warnings')
    expect(warningHtml).toContain('Optional failures')
    const emptyHtml = renderToStaticMarkup(<VerificationPanel project={{ ...project, verification: null }} onVerify={() => {}} busy={false} />)
    expect(emptyHtml).toContain('No verification report yet')
    const runningHtml = renderToStaticMarkup(<VerificationPanel project={{ ...project, verification: null, verification_running: true }} onVerify={() => {}} busy />)
    expect(runningHtml).toContain('Verification is running')
    expect(runningHtml).toContain('latest completed report')
  })
})
