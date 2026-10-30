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
  durable_jobs_enabled?: boolean
}
export type Selection = { selector: string; text: string } | null
