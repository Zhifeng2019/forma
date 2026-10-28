import { FormEvent, useEffect, useState } from 'react'
import { Bot, CheckCircle2, Edit3, KeyRound, Plus, Server, ShieldCheck, Trash2, UserRound, UsersRound, XCircle, Zap } from 'lucide-react'
import { api } from '../api'
import type { Provider, User } from '../types'
import { Layout } from '../components/Layout'
import { Modal } from '../components/Modal'

export function AdminPage({ user, onUser }: { user: User; onUser: (user: User | null) => void }) {
  const [tab, setTab] = useState<'providers' | 'users'>('providers')
  const [providers, setProviders] = useState<Provider[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [editing, setEditing] = useState<Provider | null | 'new'>(null)
  const [notice, setNotice] = useState('')
  const load = () => { void api<Provider[]>('/providers').then(setProviders); void api<User[]>('/admin/users').then(setUsers) }
  useEffect(load, [])
  const remove = async (id: number) => { if (!confirm('Remove this provider? Users will return to the local engine.')) return; await api(`/providers/${id}`, { method: 'DELETE' }); load() }
  const test = async (id: number) => { setNotice('Testing connection…'); try { const result = await api<{ message: string }>(`/providers/${id}/test`, { method: 'POST' }); setNotice(result.message) } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) } }
  return <Layout user={user} onUser={onUser}><section className="page-heading admin-heading"><div><span className="eyebrow">STUDIO OPERATIONS</span><h1>Administration</h1><p>Manage your workspace, members, and AI infrastructure.</p></div><span className="admin-badge"><ShieldCheck size={15} />Administrator</span></section>
    <div className="admin-stats"><div><span><Bot size={18} /></span><section><strong>{providers.length}</strong><small>Model providers</small></section></div><div><span><UsersRound size={18} /></span><section><strong>{users.length}</strong><small>Workspace members</small></section></div><div><span><Zap size={18} /></span><section><strong>{users.reduce((n, u) => n + (u.project_count || 0), 0)}</strong><small>Applications created</small></section></div></div>
    <div className="admin-tabs"><button className={tab === 'providers' ? 'active' : ''} onClick={() => setTab('providers')}><Server size={16} />Model providers</button><button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}><UsersRound size={16} />User management</button></div>
    {notice && <div className="admin-notice"><CheckCircle2 size={15} />{notice}<button onClick={() => setNotice('')}>×</button></div>}
    {tab === 'providers' ? <section className="admin-panel"><header><div><h2>AI providers</h2><p>Connect any OpenAI-compatible API. Credentials are encrypted at rest.</p></div><button className="button primary compact" onClick={() => setEditing('new')}><Plus size={15} />Add provider</button></header>{providers.length ? <div className="provider-list">{providers.map(p => <article key={p.id}><span className="provider-logo"><Bot size={20} /></span><div className="provider-main"><strong>{p.name}<span className={p.enabled ? 'enabled' : 'disabled'}>{p.enabled ? 'Enabled' : 'Disabled'}</span></strong><code>{p.model}</code><small>{p.base_url}</small></div><span className="key-status"><KeyRound size={13} />{p.has_key ? 'Key configured' : 'No API key'}</span><div className="row-actions"><button className="button ghost compact" onClick={() => test(p.id)}>Test</button><button className="icon-button" onClick={() => setEditing(p)}><Edit3 size={16} /></button><button className="icon-button danger" onClick={() => remove(p.id)}><Trash2 size={16} /></button></div></article>)}</div> : <div className="empty-state compact"><Server size={27} /><h3>Connect your first model</h3><p>Use Forma Local offline, or add an external provider for open-ended AI generation.</p><button className="button secondary" onClick={() => setEditing('new')}><Plus size={15} />Add provider</button></div>}</section> : <section className="admin-panel"><header><div><h2>Workspace members</h2><p>Control access and roles. Each member has an isolated project database.</p></div></header><div className="users-table"><div className="table-head"><span>Member</span><span>Role</span><span>Projects</span><span>Status</span><span>Actions</span></div>{users.map(u => <div className="table-row" key={u.id}><span className="member-cell"><i>{u.name[0].toUpperCase()}</i><span><strong>{u.name}</strong><small>{u.email}</small></span></span><span><button className="role-select" onClick={async () => { if (u.id === user.id) return; await api(`/admin/users/${u.id}`, { method: 'PATCH', body: JSON.stringify({ role: u.role === 'admin' ? 'user' : 'admin' }) }); load() }}>{u.role}</button></span><span>{u.project_count}</span><span className={`user-status ${u.status}`}>{u.status === 'active' ? <CheckCircle2 size={13} /> : <XCircle size={13} />}{u.status}</span><span><button className="button ghost compact" disabled={u.id === user.id} onClick={async () => { await api(`/admin/users/${u.id}`, { method: 'PATCH', body: JSON.stringify({ status: u.status === 'active' ? 'disabled' : 'active' }) }); load() }}>{u.status === 'active' ? 'Disable' : 'Enable'}</button></span></div>)}</div></section>}
    {editing && <ProviderModal provider={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
  </Layout>
}

function ProviderModal({ provider, onClose, onSaved }: { provider: Provider | null; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(provider?.name || '')
  const [url, setUrl] = useState(provider?.base_url || 'https://api.openai.com/v1')
  const [model, setModel] = useState(provider?.model || 'gpt-4o-mini')
  const [key, setKey] = useState('')
  const [enabled, setEnabled] = useState(provider ? Boolean(provider.enabled) : true)
  const [inputPrice, setInputPrice] = useState(provider?.input_price_per_million?.toString() ?? '')
  const [outputPrice, setOutputPrice] = useState(provider?.output_price_per_million?.toString() ?? '')
  const [currency, setCurrency] = useState(provider?.currency || 'USD')
  const [error, setError] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api(provider ? `/providers/${provider.id}` : '/providers', {
        method: provider ? 'PUT' : 'POST',
        body: JSON.stringify({
          name, base_url: url, model, api_key: key, enabled,
          input_price_per_million: inputPrice.trim() ? Number(inputPrice) : null,
          output_price_per_million: outputPrice.trim() ? Number(outputPrice) : null,
          currency,
        }),
      })
      onSaved()
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }
  const presets = [{ name: 'OpenAI', url: 'https://api.openai.com/v1', model: 'gpt-4o-mini' }, { name: 'Moonshot AI', url: 'https://api.moonshot.ai/v1', model: 'kimi-k2-0905-preview' }, { name: 'DeepSeek', url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' }]
  return <Modal title={provider ? 'Edit provider' : 'Connect a model provider'} eyebrow="AI INFRASTRUCTURE" onClose={onClose}>
    <form onSubmit={submit} className="provider-form">
      {!provider && <div className="provider-presets">{presets.map(p => <button type="button" key={p.name} onClick={() => { setName(p.name); setUrl(p.url); setModel(p.model) }}>{p.name}</button>)}</div>}
      <label>Provider name<input value={name} onChange={e => setName(e.target.value)} required placeholder="My AI provider" /></label>
      <label>Base URL<input value={url} onChange={e => setUrl(e.target.value)} required /><small>OpenAI-compatible endpoint, without /chat/completions</small></label>
      <label>Model<input value={model} onChange={e => setModel(e.target.value)} required /></label>
      <label>Input price per 1M tokens<input type="number" min="0" step="any" value={inputPrice} onChange={e => setInputPrice(e.target.value)} placeholder="Optional" /></label>
      <label>Output price per 1M tokens<input type="number" min="0" step="any" value={outputPrice} onChange={e => setOutputPrice(e.target.value)} placeholder="Optional" /></label>
      <label>Currency<input value={currency} onChange={e => setCurrency(e.target.value.toUpperCase())} minLength={3} maxLength={3} pattern="[A-Za-z]{3}" required /><small>Optional prices. Blank means unknown; zero explicitly means free.</small></label>
      <label>API key<div className="input-with-icon"><KeyRound size={16} /><input type="password" value={key} onChange={e => setKey(e.target.value)} placeholder={provider?.has_key ? 'Leave blank to keep existing key' : 'sk-…'} required={!provider?.has_key} /></div><small>Encrypted before storage. Never shown again.</small></label>
      <label className="toggle-row"><span><strong>Enable provider</strong><small>Make available to workspace members</small></span><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /><i /></label>
      {error && <div className="form-error">{error}</div>}
      <footer className="modal-actions"><button type="button" className="button ghost" onClick={onClose}>Cancel</button><button className="button primary">{provider ? 'Save changes' : 'Connect provider'}</button></footer>
    </form>
  </Modal>
}
