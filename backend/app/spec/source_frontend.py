"""Deterministic React and single-file frontend synthesis."""

from html import escape
import json

from ..source_packages import LOCAL_PACKAGE_CSS
from .contract import EntityContract
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
    return {
        '__NAME_JSON__': json.dumps(spec.product.name, ensure_ascii=False),
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
  const [items, setItems] = useState([]), [error, setError] = useState(''), [online, setOnline] = useState(false)
  const refresh = useCallback(async () => { try { setItems(await listItems()); setOnline(true); setError('') } catch (reason) { setOnline(false); setError(reason.message) } }, [])
  useEffect(() => { refresh() }, [refresh])
  const act = async action => { try { await action(); await refresh() } catch (reason) { setError(reason.message) } }
  return <main className="app"><nav><div className="brand"><span>✦</span>{__NAME_JSON__}</div><span className={online ? 'status online' : 'status'}><i />{online ? 'Application connected' : 'Local workspace'}</span></nav><section className="hero"><div><small>A FOCUSED PRODUCT WORKSPACE</small><h1>{__NAME_JSON__}</h1><p>{__WORKFLOW_JSON__}</p></div><aside><small>LIVE APPLICATION DATA</small><strong>{__METRIC__}</strong><span>{items.length} records in the current view</span></aside></section>{error && <div className="error">{error}</div>}<Workspace items={items} canEdit={__EDIT__} onRefresh={refresh} onAdd={values => act(() => createItem(values))} onUpdate={(id, values) => act(() => updateItem(id, values))} onDelete={id => act(() => deleteItem(id))}/></main>
}
'''

_REACT_WORKSPACE = '''const FIELDS = __FIELDS_JSON__
const BOOLEAN_FIELD = __BOOLEAN_FIELD_JSON__
const TITLE_FIELD = __TITLE_FIELD_JSON__
const inputType = kind => ({ integer: 'number', number: 'number', date: 'date', datetime: 'datetime-local' })[kind] || 'text'

export default function Workspace({ items, canEdit, onRefresh, onAdd, onUpdate, onDelete }) {
  const submit = event => {
    event.preventDefault()
    const values = {}
    FIELDS.forEach(field => {
      const input = event.currentTarget.elements[field.name]
      values[field.name] = field.kind === 'boolean' ? input.checked : ['integer', 'number'].includes(field.kind) ? Number(input.value) : input.value
      if (!field.required && values[field.name] === '') values[field.name] = null
    })
    onAdd(values)
    event.currentTarget.reset()
  }
  return <section className="workspace"><article className="panel"><header><h2>Primary workflow</h2><span>{items.length} records</span></header><form onSubmit={submit}>{FIELDS.map(field => <label key={field.name}>{field.label}{field.kind === 'boolean' ? <input name={field.name} type="checkbox" disabled={!canEdit} /> : field.kind === 'text' ? <textarea name={field.name} required={field.required} disabled={!canEdit} /> : <input name={field.name} type={inputType(field.kind)} required={field.required} disabled={!canEdit} />}</label>)}<button disabled={!canEdit}>Create record</button></form><div className="items">{items.map(item => <div className="item" key={item.id}><div><strong>{item[TITLE_FIELD] || `Record ${item.id}`}</strong>{FIELDS.map(field => <small key={field.name}>{field.label}: {String(item[field.name] ?? '—')}</small>)}</div>{canEdit && BOOLEAN_FIELD && <button type="button" onClick={() => onUpdate(item.id, { [BOOLEAN_FIELD]: !item[BOOLEAN_FIELD] })}>Toggle</button>}{canEdit && <button type="button" className="delete" onClick={() => onDelete(item.id)} aria-label="Delete record">×</button>}</div>)}</div></article><aside className="panel note"><h2>Built from AppSpec</h2><p>{__BRIEF_JSON__}</p><button onClick={onRefresh}>Refresh data</button><small>{canEdit ? 'Create and manage records against the declared contract.' : 'Phase 1 establishes the working data view. Approve to enable editing.'}</small></aside></section>
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
        'frontend/src/styles.css': LOCAL_PACKAGE_CSS + '\nlabel{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#718078}textarea{min-height:70px;padding:10px;border:1px solid #dbe2d8;border-radius:9px}label input,label textarea{width:100%}.item>div{flex:1}.item strong,.item small{display:block}.item small{color:#718078;margin-top:3px}\n',
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
    return f'<label>{label}{control}</label>'


_SINGLE_HTML = '''<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>__HTML_TITLE__</title><style>__CSS__</style></head><body><main class="app"><nav><div class="brand"><span>✦</span>__HTML_NAME__</div><span class="status online"><i />AppSpec application</span></nav><section class="hero"><div><small>A FOCUSED PRODUCT WORKSPACE</small><h1>__HTML_NAME__</h1><p>__HTML_WORKFLOW__</p></div><aside><small>LIVE APPLICATION DATA</small><strong id="count">0</strong><span>records in the current view</span></aside></section><section class="workspace"><article class="panel"><header><h2>Primary workflow</h2><span id="status">Loading…</span></header><form id="create-form">__FORM_FIELDS__<button id="create-button" __DISABLED__>Create record</button></form><div class="items" id="items"></div></article><aside class="panel note"><h2>Built from AppSpec</h2><p>__HTML_BRIEF__</p><button id="refresh">Refresh data</button><small>__PHASE_MESSAGE__</small></aside></section></main><script>
const FIELDS = __FIELDS_JSON__
const BOOLEAN_FIELD = __BOOLEAN_FIELD_JSON__
const TITLE_FIELD = __TITLE_FIELD_JSON__
const CAN_EDIT = __EDIT__
__API_HELPERS__
let items = []
const valuesFrom = form => { const values = {}; FIELDS.forEach(field => { const input = form.elements[field.name]; values[field.name] = field.kind === 'boolean' ? input.checked : ['integer', 'number'].includes(field.kind) ? Number(input.value) : input.value; if (!field.required && values[field.name] === '') values[field.name] = null }); return values }
const render = () => {
  const root = document.getElementById('items')
  root.replaceChildren()
  document.getElementById('count').textContent = items.length
  items.forEach(item => {
    const row = document.createElement('div'); row.className = 'item'
    const content = document.createElement('div')
    const title = document.createElement('strong'); title.textContent = item[TITLE_FIELD] || `Record ${item.id}`; content.append(title)
    FIELDS.forEach(field => { const text = document.createElement('small'); text.textContent = `${field.label}: ${item[field.name] ?? '—'}`; content.append(text) })
    row.append(content)
    if (CAN_EDIT && BOOLEAN_FIELD) { const toggle = document.createElement('button'); toggle.textContent = 'Toggle'; toggle.onclick = async () => { await updateItem(item.id, { [BOOLEAN_FIELD]: !item[BOOLEAN_FIELD] }); await refresh() }; row.append(toggle) }
    if (CAN_EDIT) { const remove = document.createElement('button'); remove.className = 'delete'; remove.textContent = '×'; remove.setAttribute('aria-label', 'Delete record'); remove.onclick = async () => { await deleteItem(item.id); await refresh() }; row.append(remove) }
    root.append(row)
  })
}
const refresh = async () => { try { items = await listItems(); document.getElementById('status').textContent = 'Connected'; render() } catch (error) { document.getElementById('status').textContent = error.message } }
document.getElementById('create-form').addEventListener('submit', async event => { event.preventDefault(); if (!CAN_EDIT) return; await createItem(valuesFrom(event.currentTarget)); event.currentTarget.reset(); await refresh() })
document.getElementById('refresh').addEventListener('click', refresh)
refresh()
</script></body></html>'''


def single_file_frontend(spec: AppSpec, contract: EntityContract, phase: int) -> dict[str, str]:
    values = _values(spec, contract, phase)
    html = _fill(_SINGLE_HTML, values)
    replacements = {
        '__HTML_TITLE__': escape(spec.product.name),
        '__HTML_NAME__': escape(spec.product.name),
        '__HTML_WORKFLOW__': escape(spec.product.primary_workflow),
        '__HTML_BRIEF__': escape(spec.product.brief[:600]),
        '__CSS__': LOCAL_PACKAGE_CSS,
        '__FORM_FIELDS__': ''.join(_html_field(field, phase >= 2) for field in contract.fields),
        '__DISABLED__': '' if phase >= 2 else 'disabled',
        '__PHASE_MESSAGE__': 'Create and manage records against the declared contract.' if phase >= 2 else 'Approve to enable editing.',
        '__API_HELPERS__': _fill(_api_javascript(spec.architecture.backend_mode, False), values),
    }
    for key, value in replacements.items():
        html = html.replace(key, value)
    return {'index.html': html}


def frontend_sources(spec: AppSpec, contract: EntityContract, phase: int) -> dict[str, str]:
    if spec.architecture.source_format == 'multi-file':
        return multi_file_frontend(spec, contract, phase)
    return single_file_frontend(spec, contract, phase)
