"""Validation and deterministic local generation for multi-file application packages."""

import ast
from html import escape
import json
from pathlib import Path, PurePosixPath
import re

from .backend_engine import (
    ALLOWED_IMPORTS, BLOCKED_CALLS, GenerationError, default_requirements,
    has_forma_api, reviewed_requirements,
)

FRONTEND_DEPENDENCIES = ('react', 'react-dom', 'lucide-react', 'vite', '@vitejs/plugin-react')
REQUIRED_FRONTEND = {
    'frontend/index.html', 'frontend/src/main.jsx', 'frontend/src/App.jsx',
    'frontend/src/api.js', 'frontend/src/components/Workspace.jsx', 'frontend/src/styles.css',
}
REQUIRED_BACKEND = {
    'backend/main.py', 'backend/app/__init__.py', 'backend/app/api.py',
    'backend/app/models.py', 'backend/app/database.py',
}
ALLOWED_BACKEND = REQUIRED_BACKEND | {'backend/requirements.txt', 'backend/app/services.py', 'backend/app/storage.py'}
ALLOWED_JS_PACKAGES = {'react', 'react-dom', 'lucide-react'}


def frontend_dependencies() -> dict[str, str]:
    lock_path = Path(__file__).parents[2] / 'frontend' / 'package-lock.json'
    lock = json.loads(lock_path.read_text())
    packages = lock['packages']
    result = {}
    for package in FRONTEND_DEPENDENCIES:
        key = f'node_modules/{package}'
        if key not in packages or 'version' not in packages[key]:
            raise GenerationError(f'The reviewed frontend lockfile is missing {package}.')
        result[package] = packages[key]['version']
    return result


def frontend_package_json() -> str:
    return json.dumps({
        'name': 'forma-generated-application', 'private': True, 'version': '1.0.0', 'type': 'module',
        'scripts': {'dev': 'vite', 'build': 'vite build', 'preview': 'vite preview'},
        'dependencies': frontend_dependencies(),
    }, indent=2) + '\n'


def frontend_vite_config() -> str:
    return "import { defineConfig } from 'vite'\nimport react from '@vitejs/plugin-react'\n\nexport default defineConfig({ plugins: [react()], base: './', build: { outDir: 'dist', emptyOutDir: true } })\n"


def package_prompt(name: str, brief: str, phase: int, feedback: str, backend_mode: str, current_files: dict[str, str]) -> str:
    current = '\n'.join(f'--- {path} ---\n{content}' for path, content in sorted(current_files.items())) or 'None'
    backend_requirement = ('Include the complete FastAPI package and a working /api/health route. Prefer Forma.api in frontend/src/api.js; same-origin fetch calls to /api/... are also supported by the runtime bridge.'
                           if backend_mode == 'fastapi' else 'Do not include a backend. frontend/src/api.js must implement browser-local persistence and must not use Forma.api.')
    return f'''Product: {name}
Brief: {brief}
Implementation phase: {phase}/3
Feedback: {feedback}
Current package files:
{current}

Return one JSON object with this shape:
{{"files":{{"frontend/index.html":"...","frontend/src/main.jsx":"...","frontend/src/App.jsx":"...","frontend/src/api.js":"...","frontend/src/components/Workspace.jsx":"...","frontend/src/styles.css":"...","backend/main.py":"...","backend/app/__init__.py":"...","backend/app/api.py":"...","backend/app/models.py":"...","backend/app/database.py":"..."}},"python_dependencies":["fastapi","uvicorn","pydantic","email-validator"]}}

Build a polished, responsive, accessible React application with a real primary workflow. Keep every file concise and preserve working contracts.
Required frontend files: frontend/index.html, frontend/src/main.jsx, frontend/src/App.jsx, frontend/src/api.js, frontend/src/components/Workspace.jsx, frontend/src/styles.css. You may add up to four components under frontend/src/components/.
{backend_requirement}
- index.html must contain id="root" and a module script for /src/main.jsx.
- JavaScript packages are limited to react, react-dom, and lucide-react. Use native fetch only through the API adapter, never for studio APIs.
- main.py must expose `app` through `from app.api import app`. app/api.py defines FastAPI and routes; models.py contains Pydantic models; database.py owns sqlite3 app.db persistence.
- Reviewed Python dependencies allowed in python_dependencies: fastapi, uvicorn, pydantic, email-validator, httpx, PyJWT, cryptography, pydantic-settings, python-multipart, SQLAlchemy. Include only packages actually used.
- The studio generates backend/requirements.txt from python_dependencies. Do not include requirements.txt in files.
- Do not import os, sys, subprocess, socket, shutil, pathlib, requests, urllib, ctypes, or importlib. Do not read host files or environment variables.
- The studio supplies package.json and vite.config.js with reviewed pinned npm versions. Do not change dependency versions.'''


def validate_source_package(
    files: dict[str, str], backend_mode: str, python_dependencies: list[str] | None = None,
) -> dict[str, str]:
    if not isinstance(files, dict):
        raise GenerationError('The model must return a files object for the project package.')
    if len(files) > 24:
        raise GenerationError('The project package is limited to 24 source files.')
    normalized = {}
    for path, content in files.items():
        pure = PurePosixPath(path)
        if pure.is_absolute() or '..' in pure.parts:
            raise GenerationError(f'Invalid source path: {path}')
        if not isinstance(content, str):
            raise GenerationError(f'Source file {path} must be text.')
        if not content.strip() and not path.endswith('.py'):
            raise GenerationError(f'Source file {path} must not be empty.')
        if len(content) > 140_000:
            raise GenerationError(f'Source file {path} is too large.')
        normalized[str(pure)] = content.strip() + '\n'
    missing = REQUIRED_FRONTEND - normalized.keys()
    if missing:
        raise GenerationError(f'The frontend package is missing: {", ".join(sorted(missing))}')
    for path in normalized:
        if path.startswith('backend/') and path not in ALLOWED_BACKEND:
            raise GenerationError(f'Unsupported backend source path: {path}')
        if path.startswith('frontend/') and path not in REQUIRED_FRONTEND | {'frontend/package.json', 'frontend/vite.config.js'}:
            if not re.fullmatch(r'frontend/src/components/[A-Za-z0-9_-]+\.jsx', path):
                raise GenerationError(f'Unsupported frontend source path: {path}')
    if backend_mode == 'fastapi':
        missing_backend = REQUIRED_BACKEND - normalized.keys()
        if missing_backend:
            raise GenerationError(f'The backend package is missing: {", ".join(sorted(missing_backend))}')
    elif any(path.startswith('backend/') for path in normalized):
        raise GenerationError('A frontend-only package must not contain a backend folder.')
    normalized['frontend/package.json'] = frontend_package_json()
    normalized['frontend/vite.config.js'] = frontend_vite_config()
    if backend_mode == 'fastapi':
        normalized['backend/requirements.txt'] = reviewed_requirements(python_dependencies)
    index = normalized['frontend/index.html']
    if 'id="root"' not in index or not re.search(r'<script[^>]+type="module"[^>]+src=["\'](?:\./)?/src/main\.jsx["\']', index):
        raise GenerationError('frontend/index.html must contain id="root" and load /src/main.jsx as a module.')
    javascript = '\n'.join(content for path, content in normalized.items()
                           if path.startswith('frontend/src/') and path.endswith(('.js', '.jsx')))
    for match in re.finditer(r'(?:from\s+|import\s*\(?\s*|require\s*\(\s*)["\']([^"\']+)["\']', javascript):
        package = match.group(1)
        if package.startswith('.'):
            if package.startswith('../..'):
                raise GenerationError(f'JavaScript import leaves its source folder: {package}')
        elif package.split('/')[0] not in ALLOWED_JS_PACKAGES and not package.startswith('react-dom/'):
            raise GenerationError(f'Unsupported JavaScript dependency: {package}')
    if backend_mode == 'fastapi' and not has_forma_api(javascript):
        raise GenerationError('The FastAPI frontend must call its API through Forma.api.')
    if backend_mode == 'static' and has_forma_api(javascript):
        raise GenerationError('The frontend-only package must not call Forma.api.')
    if backend_mode == 'fastapi':
        combined = ''
        for path, source in normalized.items():
            if path.endswith('.py'):
                _validate_python(source, path)
                combined += '\n' + source
        if not re.search(r'(?m)^app\s*=\s*FastAPI\s*\(', combined):
            raise GenerationError('The backend package must define app = FastAPI(...) in app/api.py.')
        if not re.search(r'["\']/api/health["\']', combined):
            raise GenerationError('The backend package is missing /api/health.')
        if 'from app.api import app' not in normalized['backend/main.py']:
            raise GenerationError('backend/main.py must expose app through `from app.api import app`.')
    return normalized


def _validate_python(source: str, path: str) -> None:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        raise GenerationError(f'{path} has a Python syntax error on line {exc.lineno}.') from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _validate_import(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 1:
                continue
            if node.level > 1:
                raise GenerationError(f'{path} imports outside the backend package.')
            _validate_import(node.module or '')
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            raise GenerationError(f'{path} uses a blocked operation: {node.func.id}.')
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__'):
            raise GenerationError(f'{path} uses unsupported introspection.')
    compile(source, path, 'exec')


def _validate_import(module: str) -> None:
    root = module.split('.')[0]
    if root not in ALLOWED_IMPORTS | {'app'}:
        raise GenerationError(f'The backend imports an unsupported package: {root}.')


def local_source_package(name: str, brief: str, phase: int, backend_mode: str) -> dict[str, str]:
    files = {
        'frontend/index.html': '<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(name) + '</title></head><body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body></html>',
        'frontend/src/main.jsx': "import React from 'react'\nimport { createRoot } from 'react-dom/client'\nimport App from './App.jsx'\nimport './styles.css'\n\ncreateRoot(document.getElementById('root')).render(<App />)\n",
        'frontend/src/App.jsx': LOCAL_APP_JSX.replace('__NAME_JSON__', json.dumps(name)).replace('__BRIEF_JSON__', json.dumps(brief[:180])).replace('__EDIT__', str(phase >= 2).lower()),
        'frontend/src/api.js': LOCAL_API_JS if backend_mode == 'fastapi' else LOCAL_STATIC_API_JS,
        'frontend/src/components/Workspace.jsx': LOCAL_WORKSPACE_JSX,
        'frontend/src/styles.css': LOCAL_PACKAGE_CSS,
        'frontend/package.json': frontend_package_json(),
        'frontend/vite.config.js': frontend_vite_config(),
    }
    if backend_mode == 'fastapi':
        files.update({
            'backend/main.py': 'from app.api import app\n',
            'backend/app/__init__.py': '"""Generated application backend."""\n',
            'backend/app/api.py': LOCAL_PACKAGE_API.replace('__NAME_JSON__', json.dumps(name)),
            'backend/app/models.py': LOCAL_PACKAGE_MODELS,
            'backend/app/database.py': LOCAL_PACKAGE_DATABASE,
            'backend/requirements.txt': default_requirements(),
        })
    return validate_source_package(files, backend_mode)


LOCAL_APP_JSX = '''import { useCallback, useEffect, useState } from 'react'
import Workspace from './components/Workspace.jsx'
import { createItem, deleteItem, listItems, updateItem } from './api.js'

export default function App() {
  const [items, setItems] = useState([]), [error, setError] = useState(''), [online, setOnline] = useState(false)
  const refresh = useCallback(async () => { try { const data = await listItems(); setItems(data); setOnline(true); setError('') } catch (reason) { setOnline(false); setError(reason.message) } }, [])
  useEffect(() => { refresh() }, [refresh])
  const act = async action => { try { await action(); await refresh() } catch (reason) { setError(reason.message) } }
  return <main className="app"><nav><div className="brand"><span>✦</span>{__NAME_JSON__}</div><span className={online ? 'status online' : 'status'}><i />{online ? 'Application connected' : 'Connecting…'}</span></nav><section className="hero"><div><small>A FOCUSED PRODUCT WORKSPACE</small><h1>Move good work<br/>forward, together.</h1><p>{__BRIEF_JSON__}</p></div><aside><small>LIVE APPLICATION DATA</small><strong>{items.filter(x => x.completed).length} / {items.length}</strong><span>priorities completed</span></aside></section>{error && <div className="error">{error}</div>}<Workspace items={items} canEdit={__EDIT__} onRefresh={refresh} onAdd={title => act(() => createItem(title))} onToggle={item => act(() => updateItem(item))} onDelete={item => act(() => deleteItem(item))}/></main>
}
'''
LOCAL_API_JS = '''export const listItems = async () => (await Forma.api('/items')).items
export const createItem = title => Forma.api('/items', { method: 'POST', body: JSON.stringify({ title }) })
export const updateItem = item => Forma.api(`/items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ completed: !item.completed }) })
export const deleteItem = item => Forma.api(`/items/${item.id}`, { method: 'DELETE' })
'''
LOCAL_STATIC_API_JS = '''const read = () => JSON.parse(localStorage.getItem('forma-package-items') || '[{"id":1,"title":"Shape the first useful workflow","completed":false},{"id":2,"title":"Celebrate a small release","completed":true}]')
const write = items => localStorage.setItem('forma-package-items', JSON.stringify(items))
export const listItems = async () => read()
export const createItem = async title => { const items = read(); const item = { id: Date.now(), title, completed: false }; write([item, ...items]); return item }
export const updateItem = async item => { const items = read(); write(items.map(x => x.id === item.id ? { ...x, completed: !x.completed } : x)) }
export const deleteItem = async item => { write(read().filter(x => x.id !== item.id)) }
'''
LOCAL_WORKSPACE_JSX = '''export default function Workspace({ items, canEdit, onRefresh, onAdd, onToggle, onDelete }) {
  const submit = event => { event.preventDefault(); const input = event.currentTarget.elements.title; if (input.value.trim()) { onAdd(input.value.trim()); input.value = '' } }
  return <section className="workspace"><article className="panel"><header><h2>Team priorities</h2><span>{items.length} items</span></header><form onSubmit={submit}><input name="title" aria-label="New item title" placeholder="What needs to happen next?" disabled={!canEdit} required /><button disabled={!canEdit}>Add priority</button></form><div className="items">{items.map(item => <div className={item.completed ? 'item done' : 'item'} key={item.id}><button className="toggle" disabled={!canEdit} onClick={() => onToggle(item)} aria-label="Toggle completion">✓</button><span>{item.title}</span>{canEdit && <button className="delete" onClick={() => onDelete(item)} aria-label="Delete item">×</button>}</div>)}</div></article><aside className="panel note"><h2>Built as a package</h2><p>React components, a data adapter, and versioned source are built together into a deployable frontend.</p><button onClick={onRefresh}>Refresh data</button><small>{canEdit ? 'Create, complete, and remove priorities.' : 'Phase 1 establishes the complete package and data view. Approve to enable editing.'}</small></aside></section>
}
'''
LOCAL_PACKAGE_CSS = ''':root{font-family:Inter,system-ui,sans-serif;color:#1c2823;background:#f5f6f1}*{box-sizing:border-box}body{margin:0}.app{max-width:1120px;margin:auto;padding:28px}nav,.brand,.status,.workspace article header,.item,form{display:flex;align-items:center}nav{justify-content:space-between;margin-bottom:65px}.brand{gap:10px;font-size:20px;font-weight:800}.brand span{background:#1c2823;color:#d9f99d;padding:7px;border-radius:8px}.status{gap:7px;font-size:11px;color:#718078}.status i{width:7px;height:7px;border-radius:50%;background:#d69c3f}.status.online i{background:#36a46c}.hero{display:grid;grid-template-columns:1.3fr .7fr;gap:35px;margin-bottom:38px}.hero small{font-size:10px;font-weight:800;letter-spacing:1.5px;color:#256b4b}.hero h1{font-size:clamp(40px,6vw,66px);line-height:1.03;letter-spacing:-3px;margin:14px 0}.hero p{color:#718078;max-width:560px;line-height:1.7}.hero aside{background:#d9f99d;border-radius:20px;padding:25px}.hero aside strong{display:block;font-size:36px;margin:18px 0 5px}.workspace{display:grid;grid-template-columns:1fr 290px;gap:18px}.panel{background:white;border:1px solid #e2e7df;border-radius:18px;padding:23px}.workspace article header{justify-content:space-between}.workspace h2{font-size:18px}form{gap:9px;margin:20px 0}input{flex:1;min-width:0;padding:11px;border:1px solid #dbe2d8;border-radius:9px}button{cursor:pointer;border:0;border-radius:9px;padding:10px 13px;background:#1c2823;color:white;font:inherit}button:disabled{opacity:.45}.item{gap:12px;padding:14px 0;border-top:1px solid #e8ece4}.item span{flex:1}.item.done span{text-decoration:line-through;color:#829080}.toggle{border:1px solid #bdc9bb;border-radius:50%;width:22px;height:22px;padding:0;background:white;color:#256b4b}.delete{background:transparent;color:#9aa69a;font-size:18px;padding:4px}.note p,.note small{color:#718078;line-height:1.65}.note button{margin:12px 0;background:white;color:#1c2823;border:1px solid #dbe2d8}.error{background:#ffe9df;padding:12px;border-radius:10px;margin-bottom:15px}@media(max-width:740px){.hero,.workspace{grid-template-columns:1fr}.hero h1{letter-spacing:-2px}.app{padding:20px}form{flex-wrap:wrap}input{flex-basis:100%}}'''
LOCAL_PACKAGE_MODELS = '''from pydantic import BaseModel, Field

class ItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)

class CompletionInput(BaseModel):
    completed: bool
'''
LOCAL_PACKAGE_DATABASE = '''from contextlib import contextmanager
import sqlite3

DATABASE = "app.db"

@contextmanager
def database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()

def initialize():
    with database() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        if connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            connection.executemany("INSERT INTO items(title,completed) VALUES(?,?)", [("Shape the first useful workflow",0),("Celebrate a small release",1)])
'''
LOCAL_PACKAGE_API = '''from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from .database import database, initialize
from .models import CompletionInput, ItemInput

@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield

app = FastAPI(title=__NAME_JSON__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": __NAME_JSON__}

@app.get("/api/items")
def list_items():
    with database() as connection:
        rows = connection.execute("SELECT id,title,completed,created_at FROM items ORDER BY completed,id DESC").fetchall()
    return {"items": [dict(row) for row in rows]}

@app.post("/api/items", status_code=201)
def create_item(body: ItemInput):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Give this item a clear title")
    with database() as connection:
        cursor = connection.execute("INSERT INTO items(title) VALUES(?)", (title,))
        row = connection.execute("SELECT id,title,completed,created_at FROM items WHERE id=?", (cursor.lastrowid,)).fetchone()
    return dict(row)

@app.patch("/api/items/{item_id}")
def complete_item(item_id: int, body: CompletionInput):
    with database() as connection:
        cursor = connection.execute("UPDATE items SET completed=? WHERE id=?", (int(body.completed), item_id))
        if not cursor.rowcount:
            raise HTTPException(404, "Item not found")
        row = connection.execute("SELECT id,title,completed,created_at FROM items WHERE id=?", (item_id,)).fetchone()
    return dict(row)

@app.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: int):
    with database() as connection:
        cursor = connection.execute("DELETE FROM items WHERE id=?", (item_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Item not found")
'''
