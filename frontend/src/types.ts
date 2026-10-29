export type User = { id: number; email: string; name: string; role: 'admin' | 'user'; status?: string; created_at?: string; project_count?: number }
export type Provider = {
  id: number; name: string; base_url: string; model: string; enabled: number; has_key: boolean; created_at: string
  input_price_per_million: number | null; output_price_per_million: number | null; currency: string
}
export type Message = { id: number; role: 'user' | 'agent'; content: string; kind: string; metadata: string; created_at: string }
export type Artifact = { id: number; path: string; stage: string; content: string; version: number; created_at: string }
export type Version = { id: number; version: number; label: string; note: string; backend_mode: BackendMode; source_format: SourceFormat; created_at: string }
export type StudioEvent = { id: number; message: string; level: string; created_at: string }
export type BackendMode = 'auto' | 'static' | 'fastapi'
export type SourceFormat = 'single-file' | 'multi-file'
export type RuntimeState = {
  enabled: boolean; status: 'starting' | 'running' | 'stopped' | 'error' | 'frontend-only'
  healthy: boolean; version: number; started_at?: string | null; last_error?: string | null
  logs: string; execution?: string
}
export type AppSpecEntityField = {
  name: string; kind: string; required: boolean; constraints: Record<string, string | number | boolean>
}
export type AppSpecEntity = { name: string; fields: AppSpecEntityField[]; relationships: string[] }
export type AppSpecOperation = { name: string; method: string; path: string; entity?: string | null; errors: string[] }
export type AppSpecDocument = {
  schema_version: string; compiler_version: string
  product: { name: string; brief: string; users: string[]; primary_workflow: string; acceptance_goals: string[] }
  architecture: { backend_mode: BackendMode; source_format: SourceFormat; state_ownership: 'browser' | 'server' }
  entities: AppSpecEntity[]; api: AppSpecOperation[]
  frontend: { components: string[]; routes: string[]; state_adapter: string; accessibility: string[] }
  dependencies: { python: string[]; npm: string[] }
  manifest: { files: { path: string; owner: string; max_bytes: number }[]; generation_order: string[] }
  acceptance: { name: string; kind: string; target: string }[]
}
export type AppSpecEnvelope = {
  schema_version: string; compiler_version: string; spec_hash: string; spec: AppSpecDocument
}
export type VerificationCheck = {
  id: string; kind: string; target: string; status: 'passed' | 'failed' | 'blocked' | 'skipped'
  required: boolean; mutates: boolean; tool_run_id: string; duration_ms: number
  output_ref: string; error?: string
}
export type ModelReviewSuggestion = { title: string; detail: string; severity: 'low' | 'medium' | 'high'; target: string }
export type ModelReview = {
  schema_version: string; kind: 'optional_model_review'; gating: false
  status: 'completed' | 'unavailable' | 'failed' | 'cancelled' | 'disabled'
  project_id: string; version: number; job_id: string; attempt_id: number
  spec_hash: string; source_hash: string; provider: string | null; model: string | null
  summary: string; suggestions: ModelReviewSuggestion[]; error: string | null
}
export type VerificationReport = {
  schema_version: string; project_id: string; version: number; job_id: string; attempt_id: number
  spec_hash: string; source_hash: string; status: 'passed' | 'failed' | 'passed_with_warnings'
  can_publish: boolean; complete_coverage: boolean
  summary: {
    total: number; passed: number; failed: number; blocked: number; skipped: number
    required_failures: string[]; optional_failures: string[]
  }
  started_at: string; ended_at: string; duration_ms: number; checks: VerificationCheck[]
  review?: ModelReview
}
export type ActiveJob = {
  id: string; stage: string; status: string; current_attempt: number
  trace_id: string; created_at: string; updated_at: string
}
export type Project = {
  id: string; name: string; brief: string; description: string; stage: string; stage_index: number
  phase_index: number; status: 'ready' | 'working' | 'error'; auto_mode: boolean; current_version: number
  backend_mode: BackendMode; backend_reason: string; backend_enabled: boolean; source_format: SourceFormat
  published_version: number | null; published_url?: string; created_at: string; updated_at: string
  messages: Message[]; artifacts: Artifact[]; versions: Version[]; events: StudioEvent[]; active_job?: ActiveJob | null
  appspec_enabled?: boolean; appspec?: AppSpecEnvelope | null
  appspec_valid?: boolean | null; appspec_error?: string | null
  durable_jobs_enabled?: boolean
  specialist_workers_enabled?: boolean
  verification?: VerificationReport | null; verification_running?: boolean
}
export type Selection = { selector: string; text: string } | null
