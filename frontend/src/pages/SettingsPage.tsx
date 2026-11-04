import { useEffect, useState } from 'react'
import { Bot, Check, Cpu, Gauge, Info, Plus, Save, Sparkles, Zap } from 'lucide-react'
import { api } from '../api'
import type { Preferences, Provider, User } from '../types'
import { Layout } from '../components/Layout'
import { ProviderModal } from '../components/ProviderModal'

export function SettingsPage({ user, onUser }: { user: User; onUser: (user: User | null) => void }) {
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerId, setProviderId] = useState<number | null>(null)
  const [configurable, setConfigurable] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [auto, setAuto] = useState(false)
  const [theme, setTheme] = useState('light')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Provider | null | 'new'>(null)
  const load = async () => {
    try {
      const [p, pref] = await Promise.all([api<Provider[]>('/providers'), api<Preferences>('/preferences')])
      setProviders(p); setProviderId(pref.provider_id); setConfigurable(pref.can_configure_llm)
      setAuto(Boolean(pref.auto_mode)); setTheme(pref.theme); setLoaded(true)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }
  useEffect(() => { void load() }, [])
  const save = async () => {
    setBusy(true); setError(''); setSaved(false)
    try {
      await api('/preferences', { method: 'PUT', body: JSON.stringify({ ...(configurable ? { provider_id: providerId } : {}), auto_mode: auto, theme }) })
      setSaved(true); setTimeout(() => setSaved(false), 2000)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const remove = async (provider: Provider) => {
    if (!confirm(`Remove ${provider.name}? If selected, your engine will return to Forma Local.`)) return
    try { await api(`/providers/${provider.id}`, { method: 'DELETE' }); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
  }
  const selected = providers.find(p => p.id === providerId)
  const personal = providers.filter(p => p.owner_user_id === user.id && p.can_manage)
  return <Layout user={user} onUser={onUser}>
    <section className="page-heading"><span className="eyebrow">MAKE IT YOURS</span><h1>Configuration</h1><p>Choose how your AI product team works and how your studio feels.</p></section>
    {error && <div className="form-error" role="alert">{error}</div>}
    <div className="settings-grid">
      <section className="settings-card"><header><span><Cpu size={19} /></span><div><h2>Generation engine</h2><p>The model behind your product descriptions, designs, and code.</p></div></header>
        {!loaded ? <p>Loading configuration…</p> : configurable ? <>
          <div className="engine-options">
            <label className={!providerId ? 'selected' : ''}><input type="radio" name="engine" checked={!providerId} onChange={() => setProviderId(null)} /><span className="engine-icon local"><Zap size={19} /></span><div><strong>Forma Local</strong><small>Deterministic, offline, and ready instantly</small></div><span className="engine-badge">FREE</span>{!providerId && <Check size={16} />}</label>
            {providers.filter(p => p.enabled).map(p => <label key={p.id} className={providerId === p.id ? 'selected' : ''}><input type="radio" name="engine" checked={providerId === p.id} onChange={() => setProviderId(p.id)} /><span className="engine-icon"><Bot size={19} /></span><div><strong>{p.name}</strong><small>{p.model} · {p.owner_user_id ? 'Private provider' : 'Shared provider'}</small></div>{providerId === p.id && <Check size={16} />}</label>)}
          </div>
          {user.role === 'user' && <div className="personal-providers"><h3>Your private providers</h3><p>Only your account can use these API credentials.</p>{personal.map(p => <div className="personal-provider" key={p.id}><span>{p.name}{!p.enabled && ' (disabled)'}</span><button className="button ghost compact" onClick={() => setEditing(p)} aria-label={`Edit ${p.name}`}>Edit</button><button className="button ghost compact" onClick={() => void remove(p)} aria-label={`Remove ${p.name}`}>Remove</button></div>)}<button className="button secondary compact" onClick={() => setEditing('new')}><Plus size={14} />Add private provider</button></div>}
          {!providers.length && <div className="settings-note"><Info size={16} /><span>No external providers are configured yet. {user.role === 'admin' ? 'Add one in Admin → Model providers.' : 'Add a private provider or ask your administrator to connect a shared provider.'}</span></div>}
        </> : <div className="managed-engine"><Bot size={22} /><strong>{selected?.name || 'Forma Local'}</strong><span>{selected?.model || 'Offline generation'}</span><div className="settings-note"><Info size={16} /><span>Your administrator manages the generation engine for all members. Model setup and selection are disabled.</span></div></div>}
      </section>
      <section className="settings-card"><header><span><Gauge size={19} /></span><div><h2>Build preferences</h2><p>Set your default collaboration style.</p></div></header><label className="preference-row"><span><strong><Sparkles size={16} />Autopilot by default</strong><small>Start new projects without manual approval gates. You can still intervene at any time.</small></span><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /><i /></label></section>
      <section className="settings-card account-card"><header><span><Sparkles size={19} /></span><div><h2>Your account</h2><p>Your personal workspace identity.</p></div></header><dl><div><dt>Name</dt><dd>{user.name}</dd></div><div><dt>{user.email ? 'Email' : 'Mobile'}</dt><dd>{user.email || user.phone}</dd></div><div><dt>Workspace role</dt><dd><span className="role-badge">{user.role}</span></dd></div></dl></section>
    </div>
    <div className="settings-save"><span role="status">{saved ? <><Check size={15} />Preferences saved</> : 'Changes apply to your next build.'}</span><button className="button primary" disabled={!loaded || busy} onClick={save}><Save size={15} />{busy ? 'Saving…' : 'Save preferences'}</button></div>
    {editing && <ProviderModal personal provider={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void load() }} />}
  </Layout>
}
