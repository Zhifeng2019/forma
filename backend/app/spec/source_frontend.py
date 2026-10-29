"""Deterministic React and single-file frontend synthesis."""

from html import escape
import json

from .contract import EntityContract
from .frontend_theme import APPSPEC_CSS
from .presentation import resolve_presentation
from .types import AppSpec, EntityFieldSpec


def _values(spec: AppSpec, contract: EntityContract, phase: int) -> dict[str, str]:
    fields = [{
        'name': field.name,
        'label': field.name.replace('_', ' ').capitalize(),
        'kind': field.kind,
        'required': field.required,
    } for field in contract.fields]
    title = next((field.name for field in contract.fields if field.kind in {'string', 'text'}), contract.fields[0].name)
    metric = f'items.filter(x => x[{json.dumps(contract.boolean_field)}]).length' if contract.boolean_field else 'items.length'
    presentation = resolve_presentation(spec, contract)
    return {
        '__NAME_JSON__': json.dumps(spec.product.name, ensure_ascii=False),
        '__HEADLINE_JSON__': json.dumps(presentation.headline, ensure_ascii=False),
        '__BRIEF_JSON__': json.dumps(spec.product.brief[:600], ensure_ascii=False),
        '__WORKFLOW_JSON__': json.dumps(spec.product.primary_workflow, ensure_ascii=False),
        '__FIELDS_JSON__': json.dumps(fields, ensure_ascii=False),
        '__TITLE_FIELD_JSON__': json.dumps(title),
        '__BOOLEAN_FIELD_JSON__': json.dumps(contract.boolean_field),
        '__METRIC__': metric,
        '__EDIT__': str(phase >= 2).lower(),
        '__COLLECTION_JSON__': json.dumps(contract.collection),
        '__API_PATH_JSON__': json.dumps(contract.collection_path.removeprefix('/api')),
        '__STORAGE_KEY_JSON__': json.dumps(f'forma-appspec:{spec.product.name}:{contract.collection}'),
        '__ENTITY_LABEL_JSON__': json.dumps(presentation.entity_label, ensure_ascii=False),
        '__ENTITY_PLURAL_JSON__': json.dumps(presentation.entity_plural_label, ensure_ascii=False),
        '__COLLECTION_HEADING_JSON__': json.dumps(presentation.collection_heading, ensure_ascii=False),
        '__CREATE_LABEL_JSON__': json.dumps(presentation.create_label, ensure_ascii=False),
        '__DELETE_LABEL_JSON__': json.dumps(presentation.delete_label, ensure_ascii=False),
        '__EMPTY_TITLE_JSON__': json.dumps(presentation.empty_title, ensure_ascii=False),
        '__EMPTY_MESSAGE_JSON__': json.dumps(presentation.empty_message, ensure_ascii=False),
        '__CREATED_MESSAGE_JSON__': json.dumps(presentation.created_message, ensure_ascii=False),
        '__DELETED_MESSAGE_JSON__': json.dumps(presentation.deleted_message, ensure_ascii=False),
    }


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def _api_javascript(backend_mode: str, exports: bool) -> str:
    prefix = 'export ' if exports else ''
    if backend_mode == 'fastapi':
        body = '''const API = __API_PATH_JSON__
__EXPORT__const listItems = async () => (await Forma.api(API))[__COLLECTION_JSON__]
__EXPORT__const createItem = values => Forma.api(API, { method: 'POST', body: JSON.stringify(values) })
__EXPORT__const updateItem = (id, values) => Forma.api(`${API}/${id}`, { method: 'PATCH', body: JSON.stringify(values) })
__EXPORT__const deleteItem = id => Forma.api(`${API}/${id}`, { method: 'DELETE' })
'''
    else:
        body = '''const STORAGE_KEY = __STORAGE_KEY_JSON__
const read = () => JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
const write = items => localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
__EXPORT__const listItems = async () => read()
__EXPORT__const createItem = async values => { const items = read(); const item = { id: Date.now(), ...values }; write([item, ...items]); return item }
__EXPORT__const updateItem = async (id, values) => { const items = read(); write(items.map(x => x.id === id ? { ...x, ...values } : x)); return { ...read().find(x => x.id === id) } }
__EXPORT__const deleteItem = async id => { write(read().filter(x => x.id !== id)) }
'''
    return body.replace('__EXPORT__', prefix)


_REACT_APP = '''import { useCallback, useEffect, useState } from 'react'
import Workspace from './components/Workspace.jsx'
import { createItem, deleteItem, listItems, updateItem } from './api.js'

export default function App() {
  const [items, setItems] = useState([]), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false)
  const [error, setError] = useState(''), [notice, setNotice] = useState(''), [online, setOnline] = useState(false)
  const refresh = useCallback(async () => {
    setLoading(true)
    try { setItems(await listItems()); setOnline(true); setError('') }
    catch (reason) { setOnline(false); setError(reason.message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { refresh() }, [refresh])
  const act = async (action, message) => {
    setBusy(true); setError(''); setNotice('')
    try { await action(); await refresh(); setNotice(message); return true }
    catch (reason) { setError(reason.message); return false }
    finally { setBusy(false) }
  }
  const status = loading ? 'Connecting…' : online ? 'Connected' : 'Offline'
  return <main className="app"><nav aria-label="Application"><div className="brand"><span className="brand-mark" aria-hidden="true">✦</span><span>{__NAME_JSON__}</span></div><span className={`status ${loading ? '' : online ? 'online' : 'offline'}`}><i className="status-dot" aria-hidden="true" />{status}</span></nav><header className="hero"><div className="hero-copy"><p className="eyebrow">{__COLLECTION_HEADING_JSON__}</p><h1>{__HEADLINE_JSON__}</h1><p className="hero-workflow">{__WORKFLOW_JSON__}</p></div><aside className="metric"><span className="metric-label">Overview</span><strong>{__METRIC__}</strong><small>{items.length} {__ENTITY_PLURAL_JSON__}</small></aside></header>{error && <div className="alert error" role="alert">{error}</div>}{notice && <div className="alert success" role="status">{notice}</div>}<Workspace items={items} loading={loading} busy={busy} canEdit={__EDIT__} onRefresh={refresh} onAdd={values => act(() => createItem(values), __CREATED_MESSAGE_JSON__)} onUpdate={(id, values) => act(() => updateItem(id, values), 'Changes saved.')} onDelete={id => act(() => deleteItem(id), __DELETED_MESSAGE_JSON__)}/></main>
}
'''

_REACT_WORKSPACE = '''const FIELDS = __FIELDS_JSON__
const BOOLEAN_FIELD = __BOOLEAN_FIELD_JSON__
const TITLE_FIELD = __TITLE_FIELD_JSON__
const inputType = kind => ({ integer: 'number', number: 'number', date: 'date', datetime: 'datetime-local' })[kind] || 'text'

export default function Workspace({ items, loading, busy, canEdit, onRefresh, onAdd, onUpdate, onDelete }) {
  const submit = async event => {
    event.preventDefault()
    const form = event.currentTarget, values = {}
    FIELDS.forEach(field => {
      const input = form.elements[field.name]
      if (!field.required && input.value === '' && field.kind !== 'boolean') values[field.name] = null
      else values[field.name] = field.kind === 'boolean' ? input.checked : ['integer', 'number'].includes(field.kind) ? Number(input.value) : input.value
    })
    if (await onAdd(values)) form.reset()
  }
  return <section className="workspace"><article className="panel"><header className="panel-header"><div><p className="eyebrow">Workspace</p><h2>{__COLLECTION_HEADING_JSON__}</h2></div><span className="count-badge">{items.length} {__ENTITY_PLURAL_JSON__}</span></header><form className="record-form" onSubmit={submit}><div className="form-grid">{FIELDS.map(field => <label className={field.kind === 'text' ? 'field field-wide' : 'field'} key={field.name}><span className="field-label"><span>{field.label}</span><span className="field-note">{field.required ? 'Required' : 'Optional'}</span></span>{field.kind === 'boolean' ? <input name={field.name} type="checkbox" disabled={!canEdit || busy} /> : field.kind === 'text' ? <textarea name={field.name} required={field.required} disabled={!canEdit || busy} /> : <input name={field.name} type={inputType(field.kind)} required={field.required} disabled={!canEdit || busy} />}</label>)}</div><div className="form-actions"><small>{canEdit ? 'Complete the required fields to continue.' : 'Editing is currently unavailable.'}</small><button className="primary" disabled={!canEdit || busy}>{busy ? 'Working…' : __CREATE_LABEL_JSON__}</button></div></form><div className="items">{loading ? <div className="empty-state loading-state" role="status">Loading {__ENTITY_PLURAL_JSON__}…</div> : items.length === 0 ? <div className="empty-state"><strong>{__EMPTY_TITLE_JSON__}</strong><p>{__EMPTY_MESSAGE_JSON__}</p></div> : items.map(item => <div className="item" key={item.id}><div className="item-content"><strong className="item-title">{item[TITLE_FIELD] || `${__ENTITY_LABEL_JSON__} ${item.id}`}</strong><div className="item-fields">{FIELDS.map(field => <small className="item-field" key={field.name}><b>{field.label}</b><span>{String(item[field.name] ?? '—')}</span></small>)}</div></div><div className="item-actions">{canEdit && BOOLEAN_FIELD && <button className="icon-button" type="button" disabled={busy} onClick={() => onUpdate(item.id, { [BOOLEAN_FIELD]: !item[BOOLEAN_FIELD] })} aria-label="Toggle status">✓</button>}{canEdit && <button type="button" className="icon-button delete" disabled={busy} onClick={() => onDelete(item.id)} aria-label={__DELETE_LABEL_JSON__}>×</button>}</div></div>)}</div></article><aside className="panel context-panel"><p className="eyebrow">About this workspace</p><h2>{__NAME_JSON__}</h2><p>{__BRIEF_JSON__}</p><button className="secondary" disabled={busy} onClick={onRefresh}>Refresh data</button><small className="context-note">{canEdit ? 'Changes are saved to this workspace.' : 'Editing is currently unavailable.'}</small></aside></section>
}
'''

_INDEX = '''<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__TITLE__</title></head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>'''
_MAIN = "import React from 'react'\nimport { createRoot } from 'react-dom/client'\nimport App from './App.jsx'\nimport './styles.css'\n\ncreateRoot(document.getElementById('root')).render(<App />)\n"


def multi_file_frontend(spec: AppSpec, contract: EntityContract, phase: int) -> dict[str, str]:
    values = _values(spec, contract, phase)
    return {
        'frontend/index.html': _INDEX.replace('__TITLE__', escape(spec.product.name)) + '\n',
        'frontend/src/main.jsx': _MAIN,
        'frontend/src/App.jsx': _fill(_REACT_APP, values),
        'frontend/src/api.js': _fill(_api_javascript(spec.architecture.backend_mode, True), values),
        'frontend/src/components/Workspace.jsx': _fill(_REACT_WORKSPACE, values),
        'frontend/src/styles.css': APPSPEC_CSS.strip() + '\n',
    }


def _html_field(field: EntityFieldSpec, can_edit: bool) -> str:
    label = escape(field.name.replace('_', ' ').capitalize())
    required = ' required' if field.required and field.kind != 'boolean' else ''
    disabled = '' if can_edit else ' disabled'
    if field.kind == 'boolean':
        control = f'<input name="{field.name}" type="checkbox"{disabled}>'
    elif field.kind == 'text':
        control = f'<textarea name="{field.name}"{required}{disabled}></textarea>'
    else:
        input_type = {'integer': 'number', 'number': 'number', 'date': 'date', 'datetime': 'datetime-local'}.get(field.kind, 'text')
        control = f'<input name="{field.name}" type="{input_type}"{required}{disabled}>'
    classes = 'field field-wide' if field.kind == 'text' else 'field'
    note = 'Required' if field.required else 'Optional'
    return f'<label class="{classes}"><span class="field-label"><span>{label}</span><span class="field-note">{note}</span></span>{control}</label>'


_SINGLE_HTML = '''<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__HTML_TITLE__</title><style>__CSS__</style></head><body><main class="app"><nav aria-label="Application"><div class="brand"><span class="brand-mark" aria-hidden="true">✦</span><span>__HTML_NAME__</span></div><span id="connection" class="status"><i class="status-dot" aria-hidden="true"></i><span id="status-text">Connecting…</span></span></nav><header class="hero"><div class="hero-copy"><p class="eyebrow">__HTML_COLLECTION_HEADING__</p><h1>__HTML_HEADLINE__</h1><p class="hero-workflow">__HTML_WORKFLOW__</p></div><aside class="metric"><span class="metric-label">Overview</span><strong id="count">0</strong><small id="metric-label">0 __HTML_ENTITY_PLURAL__</small></aside></header><div id="error" class="alert error" role="alert" hidden></div><div id="notice" class="alert success" role="status" hidden></div><section class="workspace"><article class="panel"><header class="panel-header"><div><p class="eyebrow">Workspace</p><h2>__HTML_COLLECTION_HEADING__</h2></div><span id="count-badge" class="count-badge">0 __HTML_ENTITY_PLURAL__</span></header><form class="record-form" id="create-form"><div class="form-grid">__FORM_FIELDS__</div><div class="form-actions"><small>__HTML_PHASE_MESSAGE__</small><button class="primary" id="create-button" __DISABLED__>__HTML_CREATE_LABEL__</button></div></form><div class="items" id="items"></div></article><aside class="panel context-panel"><p class="eyebrow">About this workspace</p><h2>__HTML_NAME__</h2><p>__HTML_BRIEF__</p><button class="secondary" id="refresh">Refresh data</button><small class="context-note">__HTML_CONTEXT_MESSAGE__</small></aside></section></main><script>
const FIELDS = __FIELDS_JSON__
const BOOLEAN_FIELD = __BOOLEAN_FIELD_JSON__
const TITLE_FIELD = __TITLE_FIELD_JSON__
const CAN_EDIT = __EDIT__
const ENTITY_LABEL = __ENTITY_LABEL_JSON__
const ENTITY_PLURAL = __ENTITY_PLURAL_JSON__
const CREATE_LABEL = __CREATE_LABEL_JSON__
const DELETE_LABEL = __DELETE_LABEL_JSON__
const EMPTY_TITLE = __EMPTY_TITLE_JSON__
const EMPTY_MESSAGE = __EMPTY_MESSAGE_JSON__
const CREATED_MESSAGE = __CREATED_MESSAGE_JSON__
const DELETED_MESSAGE = __DELETED_MESSAGE_JSON__
__API_HELPERS__
let items = [], loading = true, busy = false, online = false, error = '', notice = ''
const valuesFrom = form => { const values = {}; FIELDS.forEach(field => { const input = form.elements[field.name]; if (!field.required && input.value === '' && field.kind !== 'boolean') values[field.name] = null; else values[field.name] = field.kind === 'boolean' ? input.checked : ['integer', 'number'].includes(field.kind) ? Number(input.value) : input.value }); return values }
const state = (title, message, loadingState = false) => { const node = document.createElement('div'); node.className = loadingState ? 'empty-state loading-state' : 'empty-state'; node.setAttribute('role', 'status'); const heading = document.createElement('strong'); heading.textContent = title; const text = document.createElement('p'); text.textContent = message; node.append(heading, text); return node }
const render = () => {
  const root = document.getElementById('items'), errorNode = document.getElementById('error'), noticeNode = document.getElementById('notice')
  errorNode.hidden = !error; errorNode.textContent = error
  noticeNode.hidden = !notice; noticeNode.textContent = notice
  document.getElementById('count').textContent = items.length
  document.getElementById('metric-label').textContent = `${items.length} ${ENTITY_PLURAL}`
  document.getElementById('count-badge').textContent = `${items.length} ${ENTITY_PLURAL}`
  document.getElementById('connection').className = `status ${loading ? '' : online ? 'online' : 'offline'}`
  document.getElementById('status-text').textContent = loading ? 'Connecting…' : online ? 'Connected' : 'Offline'
  const createButton = document.getElementById('create-button'); createButton.disabled = !CAN_EDIT || busy; createButton.textContent = busy ? 'Working…' : CREATE_LABEL
  document.getElementById('refresh').disabled = busy
  FIELDS.forEach(field => { document.getElementById('create-form').elements[field.name].disabled = !CAN_EDIT || busy })
  root.replaceChildren()
  if (loading) { root.append(state('Loading…', `Loading ${ENTITY_PLURAL}.`, true)); return }
  if (!items.length) { root.append(state(EMPTY_TITLE, EMPTY_MESSAGE)); return }
  items.forEach(item => {
    const row = document.createElement('div'); row.className = 'item'
    const content = document.createElement('div'); content.className = 'item-content'
    const title = document.createElement('strong'); title.className = 'item-title'; title.textContent = item[TITLE_FIELD] || `${ENTITY_LABEL} ${item.id}`; content.append(title)
    const fields = document.createElement('div'); fields.className = 'item-fields'
    FIELDS.forEach(field => { const text = document.createElement('small'); text.className = 'item-field'; const label = document.createElement('b'); label.textContent = field.label; text.append(label, document.createTextNode(String(item[field.name] ?? '—'))); fields.append(text) })
    content.append(fields); row.append(content)
    const actions = document.createElement('div'); actions.className = 'item-actions'
    if (CAN_EDIT && BOOLEAN_FIELD) { const toggle = document.createElement('button'); toggle.className = 'icon-button'; toggle.textContent = '✓'; toggle.disabled = busy; toggle.setAttribute('aria-label', 'Toggle status'); toggle.onclick = () => run(() => updateItem(item.id, { [BOOLEAN_FIELD]: !item[BOOLEAN_FIELD] }), 'Changes saved.'); actions.append(toggle) }
    if (CAN_EDIT) { const remove = document.createElement('button'); remove.className = 'icon-button delete'; remove.textContent = '×'; remove.disabled = busy; remove.setAttribute('aria-label', DELETE_LABEL); remove.onclick = () => run(() => deleteItem(item.id), DELETED_MESSAGE); actions.append(remove) }
    row.append(actions); root.append(row)
  })
}
const refresh = async () => { loading = true; error = ''; notice = ''; render(); try { items = await listItems(); online = true } catch (reason) { online = false; error = reason.message } finally { loading = false; render() } }
const run = async (action, message) => { busy = true; error = ''; notice = ''; render(); try { await action(); await refresh(); notice = message; return true } catch (reason) { error = reason.message; return false } finally { busy = false; render() } }
document.getElementById('create-form').addEventListener('submit', async event => { event.preventDefault(); if (!CAN_EDIT || busy) return; const form = event.currentTarget; if (await run(() => createItem(valuesFrom(form)), CREATED_MESSAGE)) form.reset() })
document.getElementById('refresh').addEventListener('click', refresh)
render(); refresh()
</script></body></html>'''


def single_file_frontend(spec: AppSpec, contract: EntityContract, phase: int) -> dict[str, str]:
    values = _values(spec, contract, phase)
    presentation = resolve_presentation(spec, contract)
    html = _fill(_SINGLE_HTML, values)
    replacements = {
        '__HTML_TITLE__': escape(spec.product.name),
        '__HTML_NAME__': escape(spec.product.name),
        '__HTML_HEADLINE__': escape(presentation.headline),
        '__HTML_WORKFLOW__': escape(spec.product.primary_workflow),
        '__HTML_BRIEF__': escape(spec.product.brief[:600]),
        '__HTML_COLLECTION_HEADING__': escape(presentation.collection_heading),
        '__HTML_ENTITY_PLURAL__': escape(presentation.entity_plural_label),
        '__HTML_CREATE_LABEL__': escape(presentation.create_label),
        '__HTML_PHASE_MESSAGE__': 'Complete the required fields to continue.' if phase >= 2 else 'Editing is currently unavailable.',
        '__HTML_CONTEXT_MESSAGE__': 'Changes are saved to this workspace.' if phase >= 2 else 'Editing is currently unavailable.',
        '__CSS__': APPSPEC_CSS,
        '__FORM_FIELDS__': ''.join(_html_field(field, phase >= 2) for field in contract.fields),
        '__DISABLED__': '' if phase >= 2 else 'disabled',
        '__API_HELPERS__': _fill(_api_javascript(spec.architecture.backend_mode, False), values),
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    return {'index.html': html}


def frontend_sources(spec: AppSpec, contract: EntityContract, phase: int) -> dict[str, str]:
    if spec.architecture.source_format == 'multi-file':
        return multi_file_frontend(spec, contract, phase)
    return single_file_frontend(spec, contract, phase)
