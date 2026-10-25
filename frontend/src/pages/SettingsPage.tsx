import { useEffect, useState } from 'react'
import { Bot, Check, ChevronRight, Cpu, Gauge, Info, Moon, Save, Sparkles, Sun, Zap } from 'lucide-react'
import { api } from '../api'
import type { Provider, User } from '../types'
import { Layout } from '../components/Layout'

export function SettingsPage({ user, onUser }: { user: User; onUser: (user: User | null) => void }) {
  const [providers, setProviders] = useState<Provider[]>([])
  const [providerId, setProviderId] = useState<number | null>(null)
  const [auto, setAuto] = useState(false)
  const [theme, setTheme] = useState('light')
  const [saved, setSaved] = useState(false)
  useEffect(() => { Promise.all([api<Provider[]>('/providers'), api<{ provider_id: number | null; auto_mode: boolean; theme: string }>('/preferences')]).then(([p, pref]) => { setProviders(p); setProviderId(pref.provider_id); setAuto(pref.auto_mode); setTheme(pref.theme) }) }, [])
  const save = async () => { await api('/preferences', { method: 'PUT', body: JSON.stringify({ provider_id: providerId, auto_mode: auto, theme }) }); setSaved(true); setTimeout(() => setSaved(false), 2000) }
  return <Layout user={user} onUser={onUser}><section className="page-heading"><span className="eyebrow">MAKE IT YOURS</span><h1>Configuration</h1><p>Choose how your AI product team works and how your studio feels.</p></section>
    <div className="settings-grid"><section className="settings-card"><header><span><Cpu size={19} /></span><div><h2>Generation engine</h2><p>The model behind your product descriptions, designs, and code.</p></div></header><div className="engine-options"><label className={!providerId ? 'selected' : ''}><input type="radio" checked={!providerId} onChange={() => setProviderId(null)} /><span className="engine-icon local"><Zap size={19} /></span><div><strong>Forma Local</strong><small>Deterministic, offline, and ready instantly</small></div><span className="engine-badge">FREE</span>{!providerId && <Check size={16} />}</label>{providers.map(p => <label key={p.id} className={providerId === p.id ? 'selected' : ''}><input type="radio" checked={providerId === p.id} onChange={() => setProviderId(p.id)} /><span className="engine-icon"><Bot size={19} /></span><div><strong>{p.name}</strong><small>{p.model} · {p.base_url.replace('https://', '')}</small></div>{providerId === p.id && <Check size={16} />}</label>)}</div>{!providers.length && <div className="settings-note"><Info size={16} /><span>No external providers are configured yet. {user.role === 'admin' ? 'Add one in Admin → Model providers.' : 'Ask your administrator to connect a model provider.'}</span></div>}</section>
      <section className="settings-card"><header><span><Gauge size={19} /></span><div><h2>Build preferences</h2><p>Set your default collaboration style.</p></div></header><label className="preference-row"><span><strong><Sparkles size={16} />Autopilot by default</strong><small>Start new projects without manual approval gates. You can still intervene at any time.</small></span><input type="checkbox" checked={auto} onChange={e => setAuto(e.target.checked)} /><i /></label></section>
      <section className="settings-card account-card"><header><span><Sparkles size={19} /></span><div><h2>Your account</h2><p>Your personal workspace identity.</p></div></header><dl><div><dt>Name</dt><dd>{user.name}</dd></div><div><dt>Email</dt><dd>{user.email}</dd></div><div><dt>Workspace role</dt><dd><span className="role-badge">{user.role}</span></dd></div></dl></section>
    </div><div className="settings-save"><span>{saved ? <><Check size={15} />Preferences saved</> : 'Changes apply to your next build.'}</span><button className="button primary" onClick={save}><Save size={15} />Save preferences</button></div>
  </Layout>
}
