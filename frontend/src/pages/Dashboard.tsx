import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Check, Clock3, Code2, FileText, Globe2, Lightbulb, MoreHorizontal, Plus, Search, Server, Sparkles, Trash2 } from 'lucide-react'
import { api } from '../api'
import type { BackendMode, Project, User } from '../types'
import { Layout } from '../components/Layout'
import { Modal } from '../components/Modal'

type ProjectSummary = Pick<Project, 'id' | 'name' | 'brief' | 'stage' | 'stage_index' | 'status' | 'updated_at' | 'published_version' | 'current_version' | 'backend_mode'>
const examples = [
  { icon: '📊', title: 'Client portal', text: 'A polished client portal for a boutique consultancy with project progress, files, invoices, and a calm weekly overview.' },
  { icon: '🌿', title: 'Habit tracker', text: 'A gentle habit tracker for busy people with streaks, weekly momentum, and encouraging progress insights.' },
  { icon: '🎟️', title: 'Event hub', text: 'An event community hub with upcoming sessions, speaker profiles, registration, and a personal schedule.' },
]
const stageNames = ['Description', 'Design', 'Plan', 'Building', 'Review', 'Published']

export function Dashboard({ user, onUser }: { user: User; onUser: (user: User | null) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [create, setCreate] = useState(false)
  const [query, setQuery] = useState('')
  const [name, setName] = useState('')
  const [brief, setBrief] = useState('')
  const [auto, setAuto] = useState(false)
  const [backend, setBackend] = useState<BackendMode>('auto')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const load = () => api<ProjectSummary[]>('/projects').then(setProjects).finally(() => setLoading(false))
  useEffect(() => {
    void load()
    void api<{ auto_mode: boolean }>('/preferences').then(pref => setAuto(pref.auto_mode))
  }, [])
  const createProject = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try { const project = await api<Project>('/projects', { method: 'POST', body: JSON.stringify({ name, brief, auto_mode: auto, backend_mode: backend, defer: true }) }); navigate(`/projects/${project.id}`) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(false) }
  }
  const choose = (example: typeof examples[0]) => { setName(example.title); setBrief(example.text); setCreate(true) }
  const remove = async (id: string) => { if (!confirm('Delete this project and all of its versions?')) return; await api(`/projects/${id}`, { method: 'DELETE' }); setProjects(p => p.filter(x => x.id !== id)) }
  const filtered = projects.filter(p => `${p.name} ${p.brief}`.toLowerCase().includes(query.toLowerCase()))
  return <Layout user={user} onUser={onUser}>
    <section className="dashboard-heading"><div><span className="eyebrow">YOUR CREATIVE SPACE</span><h1>Good {new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'}, {user.name.split(' ')[0]}.</h1><p>What would you like to bring to life today?</p></div><button className="button primary" onClick={() => setCreate(true)}><Plus size={17} />New application</button></section>
    <section className="quick-start"><div className="quick-label"><Sparkles size={15} /><span>START WITH A SPARK</span></div><div className="spark-list">{examples.map(e => <button key={e.title} onClick={() => choose(e)}><span>{e.icon}</span>{e.title}<ArrowUpRight size={14} /></button>)}</div></section>
    <section className="projects-section"><div className="section-title"><div><h2>Your projects</h2><span>{projects.length} {projects.length === 1 ? 'application' : 'applications'}</span></div><label className="search-field"><Search size={16} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search projects…" /></label></div>
      {loading ? <div className="project-grid">{[1, 2, 3].map(i => <div className="project-card skeleton" key={i} />)}</div> : filtered.length ? <div className="project-grid">{filtered.map((project, i) => <article className="project-card" key={project.id} onClick={() => navigate(`/projects/${project.id}`)}>
        <div className={`project-visual tone-${i % 4}`}><div className="mini-browser"><span /><span /><span /><div className="mini-content"><i /><b /><b /><div><i /><i /><i /></div></div></div><span className={`status-chip ${project.published_version ? 'live' : ''}`}>{project.published_version ? <><Globe2 size={11} />Live</> : stageNames[project.stage_index]}</span></div>
        <div className="project-info"><div><h3>{project.name}</h3><p>{project.brief}</p></div><button className="icon-button subtle" onClick={e => { e.stopPropagation(); void remove(project.id) }} aria-label={`Delete ${project.name}`}><Trash2 size={15} /></button></div>
        <footer><span><Clock3 size={13} />{formatDate(project.updated_at)}</span>{project.backend_mode === 'fastapi' && <span className="backend-summary"><Server size={12} />FastAPI</span>}<span>{project.current_version ? `v${project.current_version}` : 'Draft'}<ArrowRight size={14} /></span></footer>
      </article>)}</div> : <div className="empty-state"><span><FileText size={28} /></span><h3>{query ? 'No matching projects' : 'Your next idea starts here'}</h3><p>{query ? 'Try another search term.' : 'Describe what you want to make. Forma will help with the rest.'}</p>{!query && <button className="button secondary" onClick={() => setCreate(true)}><Plus size={16} />Create your first app</button>}</div>}
    </section>
    {create && <Modal title="What are we building?" eyebrow="A NEW POSSIBILITY" onClose={() => !busy && setCreate(false)} className="create-modal"><form onSubmit={createProject}>
      <p className="modal-intro">Start with the idea, not the specifications. Your AI product team will help shape the details.</p>
      <label>Application name<input value={name} onChange={e => setName(e.target.value)} placeholder="e.g. Northstar client portal" required minLength={2} autoFocus /></label>
      <label>Tell us about your idea<textarea value={brief} onChange={e => setBrief(e.target.value)} placeholder="Who is it for? What problem does it solve? What should people be able to do?" required minLength={12} rows={6} /><small>{brief.length} characters · A few sentences is plenty</small></label>
      <div className="idea-tip"><Lightbulb size={17} /><span>Tip: include your primary users and the one action they should be able to complete.</span></div>
      <fieldset className="architecture-picker" disabled={busy}><legend>Application architecture</legend><p>Not every app needs a server. Pick the simplest foundation that fits your idea.</p><div className="architecture-options">
        <label className={backend === 'auto' ? 'selected' : ''}><input type="radio" name="backend" value="auto" checked={backend === 'auto'} onChange={() => setBackend('auto')} /><Sparkles size={18} /><strong>Let Forma decide</strong><small>Recommended · Choose from the product brief</small>{backend === 'auto' && <Check className="architecture-check" size={13} />}</label>
        <label className={backend === 'static' ? 'selected' : ''}><input type="radio" name="backend" value="static" checked={backend === 'static'} onChange={() => setBackend('static')} /><Code2 size={18} /><strong>Frontend only</strong><small>Portable HTML with browser-side state</small>{backend === 'static' && <Check className="architecture-check" size={13} />}</label>
        <label className={backend === 'fastapi' ? 'selected' : ''}><input type="radio" name="backend" value="fastapi" checked={backend === 'fastapi'} onChange={() => setBackend('fastapi')} /><Server size={18} /><strong>FastAPI backend</strong><small>A dedicated Python API and runtime</small>{backend === 'fastapi' && <Check className="architecture-check" size={13} />}</label>
      </div></fieldset>
      <label className="toggle-row"><span><strong>Autopilot mode</strong><small>Move through stages without approval gates</small></span><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /><i /></label>
      {error && <div className="form-error">{error}</div>}
      <footer className="modal-actions"><button type="button" className="button ghost" onClick={() => setCreate(false)} disabled={busy}>Cancel</button><button className="button primary" disabled={busy}>{busy ? <><span className="spinner" />Shaping your idea…</> : <>Start building<ArrowRight size={16} /></>}</button></footer>
    </form></Modal>}
  </Layout>
}

function formatDate(value: string) {
  const date = new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z'))
  const diff = Date.now() - date.getTime()
  if (diff < 60_000) return 'Just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
