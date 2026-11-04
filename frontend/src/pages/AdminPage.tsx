import { useEffect, useState } from 'react'
import { Bot, CheckCircle2, Edit3, KeyRound, Plus, Server, ShieldCheck, Trash2, UserRound, UsersRound, XCircle, Zap } from 'lucide-react'
import { api } from '../api'
import type { Provider, User } from '../types'
import { Layout } from '../components/Layout'
import { ProviderModal } from '../components/ProviderModal'
import { AdminPolicy } from '../components/AdminPolicy'
import { UserManagement } from '../components/UserManagement'

export function AdminPage({ user, onUser }: { user: User; onUser: (user: User | null) => void }) {
  const [tab, setTab] = useState<'providers' | 'users'>('providers')
  const [providers, setProviders] = useState<Provider[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [editing, setEditing] = useState<Provider | null | 'new'>(null)
  const [notice, setNotice] = useState('')
  const load = () => { void Promise.all([api<Provider[]>('/providers'), api<User[]>('/admin/users')]).then(([p, u]) => { setProviders(p); setUsers(u) }).catch(e => setNotice(e.message)) }
  useEffect(load, [])
  const remove = async (id: number) => { if (!confirm('Remove this provider? Users will return to the local engine.')) return; try { await api(`/providers/${id}`, { method: 'DELETE' }); load() } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) } }
  const test = async (id: number) => { setNotice('Testing connection…'); try { const result = await api<{ message: string }>(`/providers/${id}/test`, { method: 'POST' }); setNotice(result.message) } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) } }
  return <Layout user={user} onUser={onUser}><section className="page-heading admin-heading"><div><span className="eyebrow">STUDIO OPERATIONS</span><h1>Administration</h1><p>Manage your workspace, members, and AI infrastructure.</p></div><span className="admin-badge"><ShieldCheck size={15} />Administrator</span></section>
    <div className="admin-stats"><div><span><Bot size={18} /></span><section><strong>{providers.length}</strong><small>Model providers</small></section></div><div><span><UsersRound size={18} /></span><section><strong>{users.length}</strong><small>Workspace members</small></section></div><div><span><Zap size={18} /></span><section><strong>{users.reduce((n, u) => n + (u.project_count || 0), 0)}</strong><small>Applications created</small></section></div></div>
    <AdminPolicy providers={providers} />
    <div className="admin-tabs"><button className={tab === 'providers' ? 'active' : ''} onClick={() => setTab('providers')}><Server size={16} />Model providers</button><button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}><UsersRound size={16} />User management{users.some(u => u.status === 'pending') && <span className="pending-count">{users.filter(u => u.status === 'pending').length}</span>}</button></div>
    {notice && <div className="admin-notice"><CheckCircle2 size={15} />{notice}<button onClick={() => setNotice('')}>×</button></div>}
    {tab === 'providers' ? <section className="admin-panel"><header><div><h2>AI providers</h2><p>Connect any OpenAI-compatible API. Credentials are encrypted at rest.</p></div><button className="button primary compact" onClick={() => setEditing('new')}><Plus size={15} />Add provider</button></header>{providers.length ? <div className="provider-list">{providers.map(p => <article key={p.id}><span className="provider-logo"><Bot size={20} /></span><div className="provider-main"><strong>{p.name}<span className={p.enabled ? 'enabled' : 'disabled'}>{p.enabled ? 'Enabled' : 'Disabled'}</span></strong><code>{p.model}</code><small>{p.base_url}</small></div><span className="key-status"><KeyRound size={13} />{p.has_key ? 'Key configured' : 'No API key'}</span><div className="row-actions"><button className="button ghost compact" onClick={() => test(p.id)}>Test</button><button className="icon-button" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}><Edit3 size={16} /></button><button className="icon-button danger" aria-label={`Remove ${p.name}`} onClick={() => remove(p.id)}><Trash2 size={16} /></button></div></article>)}</div> : <div className="empty-state compact"><Server size={27} /><h3>Connect your first model</h3><p>Use Forma Local offline, or add an external provider for open-ended AI generation.</p><button className="button secondary" onClick={() => setEditing('new')}><Plus size={15} />Add provider</button></div>}</section> : <UserManagement users={users} currentUser={user} onChanged={load} />}
    {editing && <ProviderModal provider={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
  </Layout>
}
