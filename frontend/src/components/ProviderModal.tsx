import { FormEvent, useState } from 'react'
import { KeyRound } from 'lucide-react'
import { api } from '../api'
import type { Provider } from '../types'
import { Modal } from './Modal'

export function ProviderModal({ provider, onClose, onSaved, personal = false }: { provider: Provider | null; onClose: () => void; onSaved: () => void; personal?: boolean }) {
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
      <label className="toggle-row"><span><strong>Enable provider</strong><small>{personal ? 'Make available in your account' : 'Make available to workspace members'}</small></span><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /><i /></label>
      {error && <div className="form-error">{error}</div>}
      <footer className="modal-actions"><button type="button" className="button ghost" onClick={onClose}>Cancel</button><button className="button primary">{provider ? 'Save changes' : 'Connect provider'}</button></footer>
    </form>
  </Modal>
}
