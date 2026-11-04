import { systemText } from '../systemMessages'
import { useTranslation, relativeDate } from '../i18n'
import { FormEvent, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Check, Clock3, Code2, FileText, Globe2, Lightbulb, MoreHorizontal, Plus, Search, Server, Sparkles, Trash2 } from 'lucide-react'
import { api } from '../api'
import type { BackendMode, Project, StudioPolicy, User } from '../types'
import { Layout } from '../components/Layout'
import { Modal } from '../components/Modal'

type ProjectSummary = Pick<Project, 'id' | 'name' | 'brief' | 'stage' | 'stage_index' | 'status' | 'updated_at' | 'published_version' | 'current_version' | 'backend_mode' | 'hosting_expires_at' | 'hosting_expired'>
const examples = [
  { icon: '📊', title: 'Client portal', text: 'A polished client portal for a boutique consultancy with project progress, files, invoices, and a calm weekly overview.' },
  { icon: '🌿', title: 'Habit tracker', text: 'A gentle habit tracker for busy people with streaks, weekly momentum, and encouraging progress insights.' },
  { icon: '🎟️', title: 'Event hub', text: 'An event community hub with upcoming sessions, speaker profiles, registration, and a personal schedule.' },
]
const stageNames = ['Description', 'Design', 'Plan', 'Building', 'Review', 'Published']

export function Dashboard({ user, onUser }: { user: User; onUser: (user: User | null) => void }) {
  const { t } = useTranslation()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [create, setCreate] = useState(false)
  const [query, setQuery] = useState('')
  const [name, setName] = useState('')
  const [brief, setBrief] = useState('')
  const [auto, setAuto] = useState(false)
  const [backend, setBackend] = useState<BackendMode>('auto')
  const [sourceFormat, setSourceFormat] = useState<Project['source_format']>('multi-file')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [projectLimit, setProjectLimit] = useState<number | null>(null)
  const navigate = useNavigate()
  const load = () => api<ProjectSummary[]>('/projects').then(setProjects).finally(() => setLoading(false))
  useEffect(() => {
    void load().catch(reason => setError(reason.message))
    void api<StudioPolicy>('/policy').then(policy => setProjectLimit(policy.max_projects_per_user)).catch(reason => setError(reason.message))
    void api<{ auto_mode: boolean }>('/preferences').then(pref => setAuto(Boolean(pref.auto_mode))).catch(reason => setError(reason.message))
  }, [])
  const createProject = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try { const project = await api<Project>('/projects', { method: 'POST', body: JSON.stringify({ name, brief, auto_mode: auto, backend_mode: backend, source_format: sourceFormat, defer: true }) }); navigate(`/projects/${project.id}`) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); setBusy(false) }
  }
  const choose = (example: typeof examples[0]) => { setName(t(example.title)); setBrief(t(example.text)); setCreate(true) }
  const remove = async (id: string) => { if (!confirm(t("Delete this project and all of its versions?"))) return; await api(`/projects/${id}`, { method: 'DELETE' }); setProjects(p => p.filter(x => x.id !== id)) }
  const filtered = projects.filter(p => `${p.name} ${p.brief}`.toLowerCase().includes(query.toLowerCase()))
  const atLimit = projectLimit !== null && projects.length >= projectLimit
  return <Layout user={user} onUser={onUser}>
    <section className="dashboard-heading"><div><span className="eyebrow">{t("YOUR CREATIVE SPACE")}</span><h1>{t(new Date().getHours() < 12 ? 'Good morning, {{name}}.' : new Date().getHours() < 18 ? 'Good afternoon, {{name}}.' : 'Good evening, {{name}}.', { name: user.name.split(' ')[0] })}</h1><p>{t("What would you like to bring to life today?")}</p></div><button className="button primary" disabled={loading || atLimit} onClick={() => setCreate(true)}><Plus size={17} />{t("New application")}</button></section>
    {atLimit && <p className="quota-notice" role="status">{t("Project limit reached ({{limit}}). Delete a project before creating another.", { limit: projectLimit })}</p>}
    {error && !create && <div className="form-error" role="alert">{systemText(error)}</div>}
    <section className="quick-start"><div className="quick-label"><Sparkles size={15} /><span>{t("START WITH A SPARK")}</span></div><div className="spark-list">{examples.map(e => <button key={e.title} disabled={loading || atLimit} onClick={() => choose(e)}><span>{e.icon}</span>{t(e.title)}<ArrowUpRight size={14} /></button>)}</div></section>
    <section className="projects-section"><div className="section-title"><div><h2>{t("Your projects")}</h2><span>{projectLimit !== null ? t("{{used}} / {{limit}} applications", { used: projects.length, limit: projectLimit }) : t("{{count}} application", { count: projects.length })}</span></div><label className="search-field"><Search size={16} /><input value={query} onChange={e => setQuery(e.target.value)} placeholder={t("Search projects…")} /></label></div>
      {loading ? <div className="project-grid">{[1, 2, 3].map(i => <div className="project-card skeleton" key={i} />)}</div> : filtered.length ? <div className="project-grid">{filtered.map((project, i) => <article className="project-card" key={project.id} onClick={() => navigate(`/projects/${project.id}`)}>
        <div className={`project-visual tone-${i % 4}`}><div className="mini-browser"><span /><span /><span /><div className="mini-content"><i /><b /><b /><div><i /><i /><i /></div></div></div><span className={`status-chip ${project.published_version && !project.hosting_expired ? 'live' : ''}`}>{project.hosting_expired ? <><Clock3 size={11} />{t("Hosting expired")}</> : project.published_version ? <><Globe2 size={11} />{t("Live")}</> : project.stage === 'deploy' ? t("Ready to publish") : t(stageNames[project.stage_index])}</span></div>
        <div className="project-info"><div><h3>{project.name}</h3><p>{project.brief}</p></div><button className="icon-button subtle" onClick={e => { e.stopPropagation(); void remove(project.id) }} aria-label={t("Delete {{name}}", { name: project.name })}><Trash2 size={15} /></button></div>
        <footer><span><Clock3 size={13} />{relativeDate(project.updated_at)}</span>{project.backend_mode === 'fastapi' && <span className="backend-summary"><Server size={12} />FastAPI</span>}<span>{project.current_version ? `v${project.current_version}` : t("Draft")}<ArrowRight size={14} /></span></footer>
      </article>)}</div> : <div className="empty-state"><span><FileText size={28} /></span><h3>{query ? t("No matching projects") : t("Your next idea starts here")}</h3><p>{query ? t("Try another search term.") : t("Describe what you want to make. Forma will help with the rest.")}</p>{!query && <button className="button secondary" disabled={loading || atLimit} onClick={() => setCreate(true)}><Plus size={16} />{t("Create your first app")}</button>}</div>}
    </section>
    {create && <Modal title={t("What are we building?")} eyebrow={t("A NEW POSSIBILITY")} onClose={() => !busy && setCreate(false)} className="create-modal"><form onSubmit={createProject}>
      <p className="modal-intro">{t("Start with the idea, not the specifications. Your AI product team will help shape the details.")}</p>
      <label>{t("Application name")}<input value={name} onChange={e => setName(e.target.value)} placeholder={t("e.g. Northstar client portal")} required minLength={2} autoFocus /></label>
      <label>{t("Tell us about your idea")}<textarea value={brief} onChange={e => setBrief(e.target.value)} placeholder={t("Who is it for? What problem does it solve? What should people be able to do?")} required minLength={12} rows={6} /><small>{t("{{count}} characters · A few sentences is plenty", { count: brief.length })}</small></label>
      <div className="idea-tip"><Lightbulb size={17} /><span>{t("Tip: include your primary users and the one action they should be able to complete.")}</span></div>
      <fieldset className="architecture-picker" disabled={busy}><legend>{t("Application architecture")}</legend><p>{t("Not every app needs a server. Pick the simplest foundation that fits your idea.")}</p><div className="architecture-options">
        <label className={backend === 'auto' ? 'selected' : ''}><input type="radio" name="backend" value="auto" checked={backend === 'auto'} onChange={() => setBackend('auto')} /><Sparkles size={18} /><strong>{t("Let Forma decide")}</strong><small>{t("Recommended · Choose from the product brief")}</small>{backend === 'auto' && <Check className="architecture-check" size={13} />}</label>
        <label className={backend === 'static' ? 'selected' : ''}><input type="radio" name="backend" value="static" checked={backend === 'static'} onChange={() => setBackend('static')} /><Code2 size={18} /><strong>{t("Frontend only")}</strong><small>{t("Portable HTML with browser-side state")}</small>{backend === 'static' && <Check className="architecture-check" size={13} />}</label>
        <label className={backend === 'fastapi' ? 'selected' : ''}><input type="radio" name="backend" value="fastapi" checked={backend === 'fastapi'} onChange={() => setBackend('fastapi')} /><Server size={18} /><strong>{t("FastAPI backend")}</strong><small>{t("A dedicated Python API and runtime")}</small>{backend === 'fastapi' && <Check className="architecture-check" size={13} />}</label>
      </div></fieldset>
      <fieldset className="architecture-picker" disabled={busy}><legend>{t("Project format")}</legend><p>{t("Choose a deployable source package or the original single-file format.")}</p><div className="source-format-options">
        <label className={sourceFormat === 'multi-file' ? 'selected' : ''}><input type="radio" name="source_format" value="multi-file" checked={sourceFormat === 'multi-file'} onChange={() => setSourceFormat('multi-file')} /><strong>{t("Project package")}</strong><small>{t("Multi-file React, production build, and deployment download")}</small></label>
        <label className={sourceFormat === 'single-file' ? 'selected' : ''}><input type="radio" name="source_format" value="single-file" checked={sourceFormat === 'single-file'} onChange={() => setSourceFormat('single-file')} /><strong>{t("Single file")}</strong><small>{t("Portable HTML with an optional FastAPI module")}</small></label>
      </div></fieldset>
      <label className="toggle-row"><span><strong>{t("Autopilot mode")}</strong><small>{t("Move through stages without approval gates")}</small></span><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /><i /></label>
      {error && <div className="form-error">{systemText(error)}</div>}
      <footer className="modal-actions"><button type="button" className="button ghost" onClick={() => setCreate(false)} disabled={busy}>{t("Cancel")}</button><button className="button primary" disabled={busy || atLimit}>{busy ? <><span className="spinner" />{t("Shaping your idea…")}</> : <>{t("Start building")}<ArrowRight size={16} /></>}</button></footer>
    </form></Modal>}
  </Layout>
}
