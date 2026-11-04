import { FormEvent, useEffect, useState } from 'react'
import { Save, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import type { Provider, StudioPolicy } from '../types'

export function AdminPolicy({ providers }: { providers: Provider[] }) {
  const [policy, setPolicy] = useState<StudioPolicy | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => { void api<StudioPolicy>('/policy').then(setPolicy).catch(e => setError(e.message)) }, [])
  const change = (patch: Partial<StudioPolicy>) => { setPolicy(p => p ? { ...p, ...patch } : p); setSaved(false) }
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setSaved(false)
    try { setPolicy(await api<StudioPolicy>('/admin/policy', { method: 'PUT', body: JSON.stringify(policy) })); setSaved(true) }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  return <section className="admin-panel policy-panel">
    <header><div><h2><ShieldCheck size={16} />Studio policy</h2><p>Control model access, project capacity, and public hosting.</p></div></header>
    {error && <div className="form-error" role="alert">{error}</div>}
    {policy ? <form onSubmit={save}>
      <fieldset disabled={busy}>
        <label className="toggle-row"><span><strong>Allow users to configure and choose models</strong><small>Members can connect private API providers and select their generation engine.</small></span><input type="checkbox" checked={policy.allow_user_llm_config} onChange={e => change({ allow_user_llm_config: e.target.checked })} /><i /></label>
        <label>Global generation engine<select value={policy.global_provider_id ?? ''} onChange={e => change({ global_provider_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Forma Local (offline)</option>
          {providers.filter(p => p.enabled && p.owner_user_id == null).map(p => <option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}
        </select><small>Used by all normal users when model configuration is turned off. Administrators can still choose their own engine.</small></label>
        <div className="policy-limits">
          <label>Projects per user<input type="number" min="1" step="1" required value={policy.max_projects_per_user} onChange={e => change({ max_projects_per_user: Number(e.target.value) })} /><small>Default: 5. Applies to all accounts. Existing projects are kept when lowering the limit.</small></label>
          <label>Hosting period (hours)<input type="number" min="1" max="8760" step="1" required value={policy.hosting_duration_hours} onChange={e => change({ hosting_duration_hours: Number(e.target.value) })} /><small>Default: 1 hour. Maximum: 8,760 hours (365 days). Applies on the next publish or renewal.</small></label>
        </div>
      </fieldset>
      <footer><span role="status">{saved ? 'Studio policy saved.' : 'Each publish starts a new hosting period. Expired apps can be published again.'}</span><button className="button primary" disabled={busy}><Save size={15} />{busy ? 'Saving…' : 'Save policy'}</button></footer>
    </form> : !error && <p className="policy-loading">Loading policy…</p>}
  </section>
}
