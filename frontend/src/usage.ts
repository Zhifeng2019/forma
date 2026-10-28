export type Availability = 'reported' | 'partial' | 'unavailable'
export type CostAvailability = 'estimated' | 'partial' | 'unknown'

export type ModelUsage = {
  provider: string; model: string; provider_request_id: string | null; finish_reason: string | null
  latency_ms: number; usage_status: Availability
  input_tokens: number | null; output_tokens: number | null; total_tokens: number | null
  cost_status: CostAvailability; estimated_cost: number | null; currency: string | null
  input_price_per_million: number | null; output_price_per_million: number | null
  metadata: Record<string, unknown>
}

export type UsageToolRun = {
  id: string; attempt_id: number; tool_name: string; tool_version: string
  input_hash: string; output_ref: string; status: string; retry_count: number
  started_at: string; ended_at: string | null; duration_ms: number
  provenance: Record<string, unknown>; usage: ModelUsage | null
}

export type UsageMetrics = {
  tool_run_count: number; request_count: number; retry_count: number; duration_ms: number
  token_status: Availability; input_tokens: number | null; output_tokens: number | null
  total_tokens: number | null; cost_status: CostAvailability; estimated_cost: number | null
  currency: string | null; currencies: string[]; runtime_health: string
  spec_hashes: string[]; source_hashes: string[]
}

export type UsageJob = UsageMetrics & {
  job_id: string; stage: string; status: string; current_attempt: number; trace_id: string
  created_at: string; updated_at: string; tool_runs: UsageToolRun[]
}

export type UsageSummary = UsageMetrics & { job_count: number }

export type UsageReport = {
  schema_version: string; project_id: string; generated_at: string
  summary: UsageSummary; jobs: UsageJob[]
}
