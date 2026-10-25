export type User = { id: number; email: string; name: string; role: 'admin' | 'user'; status?: string; created_at?: string; project_count?: number }
export type Provider = { id: number; name: string; base_url: string; model: string; enabled: number; has_key: boolean; created_at: string }
export type Message = { id: number; role: 'user' | 'agent'; content: string; kind: string; metadata: string; created_at: string }
export type Artifact = { id: number; path: string; stage: string; content: string; version: number; created_at: string }
export type Version = { id: number; version: number; label: string; note: string; created_at: string }
export type StudioEvent = { id: number; message: string; level: string; created_at: string }
export type Project = {
  id: string; name: string; brief: string; description: string; stage: string; stage_index: number
  phase_index: number; status: 'ready' | 'working' | 'error'; auto_mode: boolean; current_version: number
  published_version: number | null; published_url?: string; created_at: string; updated_at: string
  messages: Message[]; artifacts: Artifact[]; versions: Version[]; events: StudioEvent[]
}
export type Selection = { selector: string; text: string } | null
