import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { UsageJob, UsageReport, UsageSummary } from '../usage'
import { UsageReportView } from './UsagePanel'

const summary: UsageSummary = {
  job_count: 1, tool_run_count: 1, request_count: 1, retry_count: 1, duration_ms: 35,
  token_status: 'partial', input_tokens: 100, output_tokens: 50, total_tokens: 150,
  cost_status: 'partial', estimated_cost: 0.0002, currency: 'USD', currencies: ['USD'],
  runtime_health: 'healthy', spec_hashes: ['spec-1'], source_hashes: ['source-1'],
}
const job: UsageJob = {
  ...summary, job_id: 'job-1', stage: 'build', status: 'succeeded', current_attempt: 2,
  trace_id: 'trace-1', created_at: '2026-01-01', updated_at: '2026-01-02',
  tool_runs: [{
    id: 'tool-1', attempt_id: 2, tool_name: 'frontend.staging', tool_version: 'forma-builder-v1',
    input_hash: 'input-hash', output_ref: 'tool-run://tool-1/output', status: 'succeeded', retry_count: 1,
    started_at: '2026-01-01', ended_at: '2026-01-02', duration_ms: 35,
    provenance: { cache_hit: true, spec_hash: 'spec-1', source_hash: 'source-1' },
    usage: {
      provider: 'Provider', model: 'model-1', provider_request_id: 'request-1', finish_reason: 'stop',
      latency_ms: 35, usage_status: 'reported', input_tokens: 100, output_tokens: 50, total_tokens: 150,
      cost_status: 'estimated', estimated_cost: 0.0002, currency: 'USD',
      input_price_per_million: 1, output_price_per_million: 2, metadata: {},
    },
  }],
}
const report: UsageReport = {
  schema_version: '1.0', project_id: 'project-1', generated_at: '2026-01-02', summary, jobs: [job],
}

describe('UsageReportView', () => {
  it('renders project, job, and tool evidence', () => {
    const html = renderToStaticMarkup(<UsageReportView report={report} />)
    expect(html).toContain('Work, measured honestly.')
    expect(html).toContain('150')
    expect(html).toContain('Partial $0.0002')
    expect(html).toContain('frontend.staging')
    expect(html).toContain('Spec spec-1')
    expect(html).toContain('Source source-1')
    expect(html).toContain('Cache hit')
    expect(html).toContain('healthy')
  })

  it('keeps local and missing usage explicitly unknown', () => {
    const empty = {
      ...report,
      summary: {
        ...summary, job_count: 0, tool_run_count: 0, request_count: 0, retry_count: 0, duration_ms: 0,
        token_status: 'unavailable' as const, input_tokens: null, output_tokens: null, total_tokens: null,
        cost_status: 'unknown' as const, estimated_cost: null, currency: null, currencies: [],
        runtime_health: 'unavailable', spec_hashes: [], source_hashes: [],
      },
      jobs: [],
    }
    const html = renderToStaticMarkup(<UsageReportView report={empty} />)
    expect(html).toContain('Unknown')
    expect(html).toContain('unavailable')
    expect(html).toContain('No durable jobs yet')
  })
})
