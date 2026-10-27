export type User = { id: number; email: string; name: string; role: 'admin' | 'user'; status?: string; created_at?: string; project_count?: number }
export type Provider = { id: number; name: string; base_url: string; model: string; enabled: number; has_key: boolean; created_at: string }
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
export type Project = {
  id: string; name: string; brief: string; description: string; stage: string; stage_index: number
  phase_index: number; status: 'ready' | 'working' | 'error'; auto_mode: boolean; current_version: number
  backend_mode: BackendMode; backend_reason: string; backend_enabled: boolean; source_format: SourceFormat
  published_version: number | null; published_url?: string; created_at: string; updated_at: string
  messages: Message[]; artifacts: Artifact[]; versions: Version[]; events: StudioEvent[]
  appspec_enabled?: boolean; appspec?: AppSpecEnvelope | null
  appspec_valid?: boolean | null; appspec_error?: string | null
}
export type Selection = { selector: string; text: string } | null
