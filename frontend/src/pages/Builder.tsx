import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Activity, ArrowDown, ArrowLeft, ArrowRight, ArrowUpRight, Check, CheckCircle2, ChevronDown, Circle, Code2, Copy, ExternalLink, FileJson2, FileText, Globe2, History, Laptop, LoaderCircle, Maximize2, MessageSquareText, Monitor, MousePointer2, Paperclip, RefreshCw, Rocket, Send, Server, Smartphone, Sparkles, Tablet, X } from 'lucide-react'
import { api, getToken } from '../api'
import type { Message as ChatMessage, Project, Selection, User } from '../types'
import { LogoMark } from '../App'
import { Modal } from '../components/Modal'
import { BackendPanel } from '../components/BackendPanel'
import { SourcePanel } from '../components/SourcePanel'
import { contractApprovalError, SpecReview } from '../components/SpecReview'

const stages = [
  { id: 'discovery', short: 'Describe', title: 'Product description', action: 'Approve description' },
  { id: 'design', short: 'Design', title: 'Experience design', action: 'Approve design' },
  { id: 'plan', short: 'Plan', title: 'Implementation plan', action: 'Start building' },
  { id: 'build', short: 'Build', title: 'Phased implementation', action: 'Approve phase' },
  { id: 'review', short: 'Review', title: 'Review & improve', action: 'Approve release' },
  { id: 'deploy', short: 'Publish', title: 'Ready to publish', action: 'Publish app' },
]
type Tab = 'preview' | 'documents' | 'contract' | 'source' | 'server' | 'activity'

export function Builder({ user }: { user: User; onUser: (user: User | null) => void }) {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [tab, setTab] = useState<Tab>('preview')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [device, setDevice] = useState<'desktop' | 'tablet' | 'mobile'>('desktop')
  const [picking, setPicking] = useState(false)
  const [selection, setSelection] = useState<Selection>(null)
  const [previewKey, setPreviewKey] = useState(0)
  const [docPath, setDocPath] = useState('product.md')
  const [publish, setPublish] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showVersions, setShowVersions] = useState(false)
  const [showArchitecture, setShowArchitecture] = useState(false)
  const [migrationTarget, setMigrationTarget] = useState<'fastapi' | 'static' | null>(null)
  const [viewVersion, setViewVersion] = useState<number | null>(null)
  const frameRef = useRef<HTMLIFrameElement>(null)
  const chatEnd = useRef<HTMLDivElement>(null)

  const load = useCallback(() => api<Project>(`/projects/${id}`).then(data => {
    setProject(data)
    const documents = data.artifacts.filter(artifact => artifact.path.endsWith('.md'))
    if (documents.length && !documents.some(artifact => artifact.path === docPath)) setDocPath(documents[0].path)
  }).catch(reason => setError(reason.message)), [id, docPath])
  useEffect(() => { void load() }, [id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!project) return
    const autopilotInProgress = project.auto_mode && project.status !== 'error' && ['discovery', 'design', 'plan', 'build'].includes(project.stage)
    if (project.status !== 'working' && !autopilotInProgress) return
    let active = true, refreshing = false, failures = 0, version = project.current_version
    const refresh = async () => {
      if (refreshing) return
      refreshing = true
      try {
        const data = await api<Project>(`/projects/${id}`)
        if (!active) return
        failures = 0
        if (data.current_version !== version) {
          version = data.current_version
          setPreviewKey(key => key + 1)
          setTab('preview')
        }
        setProject(data)
      } catch (reason) {
        if (!active) return
        failures += 1
        if (failures >= 4) {
          setError(reason instanceof Error ? reason.message : String(reason))
          setProject(current => current ? { ...current, status: 'error' } : current)
        }
      } finally { refreshing = false }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [id, project?.status, project?.stage, project?.auto_mode])
  useEffect(() => {
    if (project?.stage === 'build' && project.current_version === 0 && project.appspec_enabled && project.appspec) setTab('contract')
  }, [project?.stage, project?.current_version, project?.appspec_enabled, project?.appspec])
  useEffect(() => { if (project?.status !== 'working') setMigrationTarget(null) }, [project?.status])
  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [project?.messages.length])
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.data?.type === 'forma-selection') { setSelection(event.data.selection); setPicking(false) }
    }
    window.addEventListener('message', handler); return () => window.removeEventListener('message', handler)
  }, [])
  useEffect(() => { frameRef.current?.contentWindow?.postMessage({ type: 'forma-picker', enabled: picking }, '*') }, [picking, previewKey])

  if (!project) return <div className="app-loading"><LogoMark /><span>{error || 'Preparing your workspace…'}</span>{error && <button className="button secondary" onClick={() => navigate('/')}>Back to projects</button>}</div>
  const stage = stages[project.stage_index] || stages[0]
  const html = project.artifacts.find(a => a.version === project.current_version && ['index.html', 'frontend/index.html'].includes(a.path))
  const document = project.artifacts.find(a => a.path === docPath)
  const isWorking = busy || project.status === 'working'
  const contractError = contractApprovalError(project)
  const currentWorkingLabel = migrationTarget ? `Migrating to ${migrationTarget === 'fastapi' ? 'FastAPI' : 'frontend only'}…` : workingLabel(project.stage)
  const publishUrl = `${window.location.origin}/apps/${project.id}/`

  const advance = async () => {
    if (project.stage === 'deploy') { setPublish(true); return }
    if (contractError) { setError(contractError); setTab('contract'); return }
    const previousVersion = project.current_version
    setBusy(true); setError('')
    try {
      const next = await api<Project>(`/projects/${id}/advance`, { method: 'POST', body: JSON.stringify({ feedback: '', defer: true }) })
      setProject(next)
      if (next.current_version !== previousVersion) setPreviewKey(k => k + 1)
      if (next.stage === 'build' && next.current_version === 0 && next.appspec_enabled) setTab('contract')
      else if (next.stage === 'build' || next.stage === 'review') setTab('preview')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } finally { setBusy(false) }
  }
  const send = async (event: FormEvent) => {
    event.preventDefault(); if (!message.trim() || isWorking) return
    const content = message, selected = selection, previousVersion = project.current_version
    const optimistic: ChatMessage = {
      id: -Date.now(), role: 'user', content, kind: 'chat',
      metadata: JSON.stringify({ selection: selected || {} }),
      created_at: new Date().toISOString().slice(0, 19).replace('T', ' '),
    }
    setProject(current => current ? { ...current, messages: [...current.messages, optimistic] } : current)
    setMessage(''); setSelection(null); setBusy(true); setError('')
    try {
      const next = await api<Project>(`/projects/${id}/messages`, { method: 'POST', body: JSON.stringify({ content, selection: selected, defer: true }) })
      setProject(next)
      if (next.current_version !== previousVersion) setPreviewKey(k => k + 1)
    } catch (reason) {
      setProject(current => current ? { ...current, messages: current.messages.filter(item => item.id !== optimistic.id) } : current)
      setMessage(current => current.trim() ? current : content)
      setSelection(current => current || selected)
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally { setBusy(false) }
  }
  const doPublish = async () => {
    setBusy(true)
    try { const next = await api<Project>(`/projects/${id}/publish`, { method: 'POST', body: JSON.stringify({ version: project.current_version }) }); setProject(next); setCopied(false) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } finally { setBusy(false) }
  }
  const migrateArchitecture = async () => {
    const targetMode = project.backend_mode === 'fastapi' ? 'static' : 'fastapi'
    const previousVersion = project.current_version
    setMigrationTarget(targetMode)
    setTab('preview'); setShowArchitecture(false); setBusy(true); setError('')
    try {
      const next = await api<Project>(`/projects/${id}/architecture`, {
        method: 'POST', body: JSON.stringify({ target_mode: targetMode, feedback: '', defer: true }),
      })
      setProject(next)
      if (next.current_version !== previousVersion) setPreviewKey(k => k + 1)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } finally { setBusy(false) }
  }
  const copy = async () => { await navigator.clipboard.writeText(publishUrl); setCopied(true); setTimeout(() => setCopied(false), 1800) }
  const chooseVersion = (version: number | null) => { setViewVersion(version); setPreviewKey(k => k + 1); setShowVersions(false) }

  return <div className="builder-shell">
    <header className="builder-header"><div className="builder-brand"><Link to="/" className="brand"><LogoMark /><span>forma</span></Link><i /><Link to="/" className="back-link"><ArrowLeft size={15} />Projects</Link><span className="project-name">{project.name}<ChevronDown size={13} /></span><span className="save-state"><Check size={12} />Saved</span><button className="architecture-label architecture-button" title={`${project.backend_reason} Click to change architecture.`} onClick={() => setShowArchitecture(true)} disabled={isWorking}>{project.backend_mode === 'fastapi' ? <Server size={12} /> : <Code2 size={12} />}{project.backend_mode === 'fastapi' ? 'FastAPI' : project.backend_mode === 'static' ? 'Frontend only' : 'Choosing architecture'}</button></div><div className="builder-header-actions"><button className="button ghost compact" onClick={() => setShowVersions(!showVersions)}><History size={15} />{viewVersion ? `Viewing v${viewVersion}` : 'History'}<ChevronDown size={12} /></button><button className="button primary compact" onClick={() => setPublish(true)}><Rocket size={15} />{project.published_version ? 'Manage release' : 'Publish'}</button><span className="avatar small">{user.name[0].toUpperCase()}</span></div>
      {showVersions && <div className="versions-menu"><header><strong>Version history</strong><button onClick={() => setShowVersions(false)}><X size={15} /></button></header><button className={!viewVersion ? 'selected' : ''} onClick={() => chooseVersion(null)}><span><strong>Current working version</strong><small>v{project.current_version || 'draft'} · Latest changes</small></span>{!viewVersion && <Check size={15} />}</button>{project.versions.map(v => <button key={v.id} className={viewVersion === v.version ? 'selected' : ''} onClick={() => chooseVersion(v.version)}><span><strong>Version {v.version} · {v.label}</strong><small>{v.note || new Date(v.created_at).toLocaleString()}</small></span>{project.published_version === v.version && <span className="tiny-live">LIVE</span>}<span className="version-mode">{v.backend_mode === 'fastapi' ? 'FastAPI' : 'Static'}</span></button>)}</div>}
    </header>
    <div className="stage-track">{stages.map((item, index) => <button key={item.id} className={`${index === project.stage_index ? 'active' : ''} ${index < project.stage_index ? 'complete' : ''}`} onClick={() => { const artifact = project.artifacts.find(a => a.stage === item.id); if (artifact) { setDocPath(artifact.path); setTab('documents') } }} disabled={index > project.stage_index}><span>{index < project.stage_index ? <Check size={12} /> : index + 1}</span>{item.short}{index < stages.length - 1 && <i />}</button>)}</div>
    <div className="builder-body">
      <aside className="agent-panel"><header><div className="agent-title"><span><Sparkles size={16} /></span><div><strong>Product team</strong><small><i className={isWorking ? 'working' : ''} />{isWorking ? 'Working on your app' : 'Ready to collaborate'}</small></div></div><button className="icon-button"><MoreIcon /></button></header>
        <div className="chat-scroll"><div className="context-card"><span>BUILDING</span><strong>{project.name}</strong><p>{project.brief}</p></div>{project.messages.map(msg => <div key={msg.id} className={`chat-message ${msg.role}`} >{msg.role === 'agent' && <span className="agent-avatar"><Sparkles size={13} /></span>}<div><span className="message-author">{msg.role === 'agent' ? 'Forma' : 'You'}<time>{timeLabel(msg.created_at)}</time></span><p>{msg.content}</p>{msg.kind === 'stage' && msg.role === 'agent' && <span className="message-receipt"><CheckCircle2 size={12} />Workspace updated</span>}</div></div>)}{isWorking && <div className="chat-message agent"><span className="agent-avatar"><Sparkles size={13} /></span><div><span className="message-author">Forma</span><div className="thinking"><i /><i /><i /><span>{currentWorkingLabel}</span></div></div></div>}<div ref={chatEnd} /></div>
        <div className="composer-wrap">{selection && <div className="selection-pill"><MousePointer2 size={13} /><span>{selection.selector}</span><button onClick={() => setSelection(null)}><X size={12} /></button></div>}<form className="composer" onSubmit={send}><textarea value={message} onChange={e => setMessage(e.target.value)} placeholder={selection ? 'What should change here?' : 'Ask for a change or share feedback…'} rows={3} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(e) } }} /><div><button type="button" className={`icon-button ${picking ? 'active' : ''}`} title="Select an element in the preview" onClick={() => { setTab('preview'); setPicking(!picking) }}><Paperclip size={16} /></button><span>↵ to send</span><button className="send-button" disabled={!message.trim() || isWorking}><Send size={15} /></button></div></form><p className="composer-note">Forma can make mistakes. Review before publishing.</p></div>
      </aside>
      <main className="work-panel"><header className="work-tabs"><div><button className={tab === 'preview' ? 'active' : ''} onClick={() => setTab('preview')}><Monitor size={15} />Preview</button><button className={tab === 'documents' ? 'active' : ''} onClick={() => setTab('documents')}><FileText size={15} />Documents<span>{project.artifacts.filter(a => a.path.endsWith('.md')).length}</span></button>{(project.appspec_enabled || project.appspec) && <button className={tab === 'contract' ? 'active' : ''} onClick={() => setTab('contract')}><FileJson2 size={15} />Contract</button>}<button className={tab === 'source' ? 'active' : ''} onClick={() => setTab('source')}><Code2 size={15} />Source</button>{project.backend_mode === 'fastapi' && <button className={tab === 'server' ? 'active' : ''} onClick={() => setTab('server')}><Server size={15} />Server</button>}<button className={tab === 'activity' ? 'active' : ''} onClick={() => setTab('activity')}><Activity size={15} />Activity</button></div>{tab === 'preview' && html && <div className="preview-tools"><span className="device-switch"><button className={device === 'desktop' ? 'active' : ''} onClick={() => setDevice('desktop')} title="Desktop"><Laptop size={15} /></button><button className={device === 'tablet' ? 'active' : ''} onClick={() => setDevice('tablet')} title="Tablet"><Tablet size={15} /></button><button className={device === 'mobile' ? 'active' : ''} onClick={() => setDevice('mobile')} title="Mobile"><Smartphone size={15} /></button></span><button className={`icon-button ${picking ? 'active picker-on' : ''}`} onClick={() => setPicking(!picking)} title="Select element to edit"><MousePointer2 size={16} /></button><button className="icon-button" onClick={() => setPreviewKey(k => k + 1)} title="Refresh preview"><RefreshCw size={15} /></button></div>}</header>
        {error && <div className="builder-error">{error}<button onClick={() => setError('')}><X size={14} /></button></div>}
        <section className="workspace-content">
          {tab === 'preview' && (html ? <div className={`preview-stage ${device}`}><div className="browser-bar"><div className="browser-dots"><i /><i /><i /></div><div className="browser-address"><span>⌕</span>preview.forma.local/{project.id.slice(0, 8)}</div><button onClick={() => window.open(`/api/projects/${id}/preview?access_token=${encodeURIComponent(getToken() || '')}&version=${viewVersion || project.current_version}`, '_blank')}><ExternalLink size={14} /></button></div><iframe key={`${previewKey}-${viewVersion}`} ref={frameRef} src={`/api/projects/${id}/preview?access_token=${encodeURIComponent(getToken() || '')}&version=${viewVersion || project.current_version}`} title={`${project.name} preview`} sandbox="allow-scripts allow-forms allow-modals allow-same-origin" />{picking && <div className="picker-banner"><MousePointer2 size={14} />Click any element to give targeted feedback<button onClick={() => setPicking(false)}>Cancel</button></div>}{viewVersion && <div className="history-banner"><History size={14} />Viewing version {viewVersion}<button onClick={() => chooseVersion(null)}>Return to current</button></div>}</div> : <PreviewEmpty stage={project.stage_index} onAction={advance} busy={isWorking || Boolean(contractError)} />)}
          {tab === 'documents' && <div className="documents-view"><nav>{project.artifacts.filter(a => a.path.endsWith('.md')).map(a => <button className={docPath === a.path ? 'active' : ''} key={a.path} onClick={() => setDocPath(a.path)}><FileText size={16} /><span>{a.path}<small>{a.stage}</small></span><ArrowRight size={13} /></button>)}{!project.artifacts.some(a => a.path.endsWith('.md')) && <p>Documents will appear as your product team completes each stage.</p>}</nav><article className="markdown-body">{document ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{document.content}</ReactMarkdown> : <div className="empty-state"><FileText size={28} /><h3>Document in progress</h3></div>}</article></div>}
          {tab === 'contract' && <SpecReview project={project} />}
          {tab === 'source' && <SourcePanel project={project} />}
          {tab === 'server' && project.backend_mode === 'fastapi' && <BackendPanel project={project} onChanged={() => void load()} />}
          {tab === 'activity' && <div className="activity-view"><div className="activity-heading"><span className="eyebrow">PROJECT TIMELINE</span><h2>Every step, in the open.</h2><p>A clear record of your product team’s work and releases.</p></div><div className="timeline">{project.events.map(event => <div key={event.id}><span className={event.level}>{event.level === 'success' ? <Check size={13} /> : event.level === 'error' ? <X size={13} /> : <Circle size={9} />}</span><section><strong>{event.message}</strong><small>{new Date(event.created_at).toLocaleString()}</small></section></div>)}</div></div>}
        </section>
        <footer className="approval-bar"><div><span className="stage-icon">{isWorking ? <LoaderCircle className="spin" size={18} /> : <CheckCircle2 size={18} />}</span><div><strong>{isWorking ? currentWorkingLabel : stage.title}</strong><small>{isWorking ? 'You can keep reviewing the current workspace.' : contractError || approvalHint(project)}</small></div></div><button className="button primary" disabled={isWorking || Boolean(contractError) || project.stage === 'deploy'} title={contractError || undefined} onClick={advance}>{project.stage === 'deploy' ? <><Globe2 size={15} />{project.published_version ? 'Published' : 'Ready to publish'}</> : <>{project.stage === 'build' ? (project.phase_index ? `Approve phase ${project.phase_index}` : 'Build phase 1') : stage.action}<ArrowRight size={15} /></>}</button></footer>
      </main>
    </div>
    {showArchitecture && <Modal title={project.backend_mode === 'fastapi' ? 'Move to frontend-only?' : 'Add a FastAPI backend?'} eyebrow="APPLICATION ARCHITECTURE" onClose={() => !busy && setShowArchitecture(false)} className="architecture-modal">
      <p className="modal-intro">Change the foundation without losing your product history. Forma will preserve the current design as it creates the migration.</p>
      <div className="migration-path"><span>{project.backend_mode === 'fastapi' ? <Server size={17} /> : <Code2 size={17} />}{project.backend_mode === 'fastapi' ? 'FastAPI' : 'Frontend only'}</span><ArrowRight size={17} /><span className="target">{project.backend_mode === 'fastapi' ? <Code2 size={17} /> : <Server size={17} />}{project.backend_mode === 'fastapi' ? 'Frontend only' : 'FastAPI'}</span></div>
      <ul className="migration-assurances"><li><Check size={14} />{project.current_version ? `Create version ${project.current_version + 1}; older versions stay unchanged.` : 'Apply the new architecture to your first build.'}</li><li><Check size={14} />Stay on the current phase; this is not an approval.</li><li><Check size={14} />{project.backend_mode === 'fastapi' ? 'Stop only the working FastAPI preview and use browser state in the new version.' : 'Add a dedicated API, Python environment, and shared application state.'}</li></ul>
      {project.published_version && <p className="migration-note">Published version {project.published_version} remains live with its original architecture until you republish or unpublish it.</p>}
      {error && <div className="form-error">{error}</div>}
      <footer className="modal-actions"><button className="button ghost" onClick={() => setShowArchitecture(false)} disabled={busy}>Cancel</button><button className="button primary" onClick={migrateArchitecture} disabled={busy}>{busy ? <span className="spinner" /> : project.backend_mode === 'fastapi' ? 'Switch to frontend only' : 'Add FastAPI'}<ArrowRight size={15} /></button></footer>
    </Modal>}
    {publish && <Modal title={project.published_version ? 'Your app is out in the world.' : 'Ready to make it real?'} eyebrow="PUBLISH YOUR APPLICATION" onClose={() => setPublish(false)} className="publish-modal"><div className="publish-hero"><span><Rocket size={28} /></span><h3>{project.name}</h3><p>{project.published_version ? `Version ${project.published_version} is live and ready to share.` : `Publish version ${project.current_version || '—'} to a public, shareable URL. You can keep improving and republish anytime.`}</p></div>{project.published_version ? <><label>Public application URL<div className="copy-field"><Globe2 size={16} /><input readOnly value={publishUrl} /><button onClick={copy}>{copied ? <Check size={16} /> : <Copy size={16} />}</button></div></label><div className="publish-actions"><a className="button secondary" href={publishUrl} target="_blank">Open live app<ArrowUpRight size={15} /></a>{project.published_version !== project.current_version && <button className="button primary" onClick={doPublish} disabled={busy}>Publish latest v{project.current_version}</button>}</div><button className="unpublish" onClick={async () => { await api(`/projects/${id}/unpublish`, { method: 'POST' }); setProject({ ...project, published_version: null }); setPublish(false) }}>Unpublish application</button></> : <footer className="modal-actions"><button className="button ghost" onClick={() => setPublish(false)}>Not yet</button><button className="button primary" onClick={doPublish} disabled={!project.current_version || busy}>{busy ? <span className="spinner" /> : <><Rocket size={15} />Publish application</>}</button></footer>}</Modal>}
  </div>
}

function PreviewEmpty({ stage, onAction, busy }: { stage: number; onAction: () => void; busy: boolean }) {
  return <div className="preview-empty"><div className="empty-canvas"><span className="empty-logo"><Code2 size={28} /></span><i className="line one" /><i className="line two" /><div><i /><i /><i /></div></div><span className="eyebrow">YOUR APPLICATION TAKES SHAPE HERE</span><h2>{stage < 3 ? 'A strong product starts with clarity.' : 'Your first preview is almost here.'}</h2><p>{stage < 3 ? 'Complete the description, design, and plan. Then watch your idea become a working product.' : 'Approve the current phase to generate a working preview.'}</p><button className="button secondary" onClick={onAction} disabled={busy}>Continue with Forma<ArrowRight size={15} /></button></div>
}
function workingLabel(stage: string) { return stage === 'discovery' ? 'Shaping the product description…' : stage === 'design' ? 'Designing the experience…' : stage === 'plan' ? 'Planning the implementation…' : stage === 'deploy' ? 'Preparing your release…' : 'Building your application…' }
function approvalHint(project: Project) { if (project.stage === 'build') return `Phase ${project.phase_index} of 3 · Review the preview, then continue.`; if (project.stage === 'review') return 'Try the interactions. Send feedback or approve the release.'; if (project.stage === 'deploy') return project.published_version ? 'Your latest approved application is live.' : 'Everything is ready for your public release.'; return 'Review the document and share feedback, or approve to continue.' }
function timeLabel(value: string) { try { return new Date(value.replace(' ', 'T') + 'Z').toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) } catch { return '' } }
function MoreIcon() { return <svg width="18" height="18" viewBox="0 0 18 18" fill="currentColor"><circle cx="3" cy="9" r="1.4" /><circle cx="9" cy="9" r="1.4" /><circle cx="15" cy="9" r="1.4" /></svg> }
