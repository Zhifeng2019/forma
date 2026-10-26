"""Generation, validation, and deterministic local code for optional app backends."""

import ast
from importlib.metadata import version as package_version
import json
import re
from html import escape

from .llm import GenerationError

BACKEND_PATH = 'backend/main.py'
REQUIREMENTS_PATH = 'backend/requirements.txt'
ALLOWED_IMPORTS = {
    'abc', 'asyncio', 'base64', 'bisect', 'collections', 'contextlib', 'csv',
    'dataclasses', 'datetime', 'decimal', 'email_validator', 'enum', 'fastapi', 'functools', 'hashlib',
    'heapq', 'hmac', 'httpx', 'io', 'itertools', 'json', 'jwt', 'math', 'multipart',
    'pydantic', 'pydantic_settings', 'random', 're', 'secrets', 'sqlalchemy',
    'sqlite3', 'statistics', 'string', 'textwrap', 'time', 'typing', 'uuid',
    'cryptography',
}
BLOCKED_CALLS = {
    '__import__', 'breakpoint', 'compile', 'eval', 'exec', 'getattr', 'globals',
    'input', 'locals', 'open', 'setattr', 'vars',
}
BACKEND_SIGNALS = (
    (r'\b(back[- ]?end|server|database|sql|api)\b', 'a server-side API or database'),
    (r'\b(shared|collaborat\w*|multi[- ]user|team workspace)\b', 'shared or collaborative data'),
    (r'\b(log[ -]?in|sign[ -]?in|authentication|user accounts?|role[- ]based)\b', 'accounts or authenticated access'),
    (r'\b(sync\w*|real[- ]?time|across devices|centrali[sz]ed)\b', 'synchronized data'),
    (r'\b(payments?|checkout| bookings?|registration|inventory)\b', 'reliable server-side transactions'),
    (r'\b(uploads?|file storage|webhooks?)\b', 'server-managed files or integrations'),
)


def default_requirements() -> str:
    """Use the studio's verified versions, never model-selected package versions."""
    return '\n'.join(
        f'{package}=={package_version(package)}'
        for package in ('fastapi', 'uvicorn', 'pydantic', 'email-validator')
    ) + '\n'


REVIEWED_PACKAGES = {
    'fastapi': 'fastapi', 'uvicorn': 'uvicorn', 'pydantic': 'pydantic',
    'email-validator': 'email-validator', 'httpx': 'httpx', 'pyjwt': 'PyJWT',
    'cryptography': 'cryptography', 'pydantic-settings': 'pydantic-settings',
    'python-multipart': 'python-multipart', 'sqlalchemy': 'SQLAlchemy',
}


def reviewed_requirements(requested: list[str] | str | None = None) -> str:
    """Return pinned base and explicitly reviewed optional dependencies."""
    if isinstance(requested, str):
        requested = requested.splitlines()
    if requested is None:
        requested = []
    if not isinstance(requested, list) or any(not isinstance(item, str) for item in requested):
        raise GenerationError('python_dependencies must be a list of reviewed package names.')
    packages = ['fastapi', 'uvicorn', 'pydantic', 'email-validator']
    for item in requested:
        name = re.sub(r'[-_.]+', '-', item.split('==', 1)[0].strip()).lower()
        if name not in REVIEWED_PACKAGES:
            raise GenerationError(f'Unsupported Python dependency: {item}. Reviewed packages: {", ".join(REVIEWED_PACKAGES)}.')
        package = REVIEWED_PACKAGES[name]
        if package not in packages:
            packages.append(package)
    return '\n'.join(f'{package}=={package_version(package)}' for package in packages) + '\n'


def runtime_requirements(requirements: str) -> str:
    """Add required runtime support packages missing from older artifacts."""
    lines = [line.strip() for line in requirements.splitlines() if line.strip()]
    present = {re.sub(r'[-_.]+', '-', line.split('==', 1)[0]).lower() for line in lines}
    for line in default_requirements().splitlines():
        package = re.sub(r'[-_.]+', '-', line.split('==', 1)[0]).lower()
        if package not in present:
            lines.append(line)
            present.add(package)
    return '\n'.join(lines) + '\n'


def recommend_backend(brief: str) -> tuple[bool, str]:
    for pattern, reason in BACKEND_SIGNALS:
        if re.search(pattern, brief, re.IGNORECASE):
            return True, f'The brief calls for {reason}, so Forma selected a dedicated FastAPI service.'
    return False, 'The core experience can run in the browser, so Forma selected a frontend-only architecture.'


def application_prompt(
    name: str,
    brief: str,
    phase: int,
    feedback: str,
    current_html: str,
    current_python: str,
) -> str:
    return f'''Product: {name}
Brief: {brief}
Implementation phase: {phase}/3
Feedback: {feedback}
Current HTML to improve: {current_html or 'None'}
Current FastAPI source to improve: {current_python or 'None'}

Build the complete frontend AND its dedicated FastAPI backend together. Return one JSON object:
{{"html":"<!doctype html>...","python":"from fastapi import FastAPI...","requirements":["fastapi","uvicorn","pydantic","email-validator"]}}

Requirements:
- HTML is a complete, polished, responsive, accessible single-file application with inline CSS and JavaScript. No external frontend dependencies.
- The backend is ONE complete Python module named main.py. Define `app = FastAPI(...)` and a GET `/api/health` endpoint returning {{"status":"ok"}}.
- Implement the product's real server-side workflow beneath `/api`, with validation, useful errors, and sensible initial data. Use Python's standard-library sqlite3 with database filename `app.db` when persistence is needed; do not use browser localStorage for server-owned data.
- The runtime injects `window.Forma.api(path, options)` before application scripts. EVERY backend request MUST use `Forma.api('/resource', options)`, without an `/api` prefix. Example: `const items = await Forma.api('/items');` and `await Forma.api('/items', {{method:'POST', body:JSON.stringify({{title}})}})`. Do not call fetch directly for the application API.
- Base packages: fastapi, pydantic, uvicorn, and email-validator. Reviewed optional packages: httpx, PyJWT, cryptography, pydantic-settings, python-multipart, SQLAlchemy. Include optional packages in requirements only when used. Do not import os, sys, subprocess, socket, shutil, pathlib, requests, urllib, ctypes, or importlib. Do not read host files or environment variables.
- Keep the backend focused and below 500 lines. Preserve working API contracts when refining an existing version.
- Phase 1 must already have a working preview and health endpoint. Phase 2 completes the primary server-backed workflow. Phase 3 improves reliability and release polish.'''


def has_forma_api(script: str) -> bool:
    """Accept Forma.api or a native fetch handled by the runtime bridge."""
    return bool(re.search(r'(?:window\.)?Forma(?:\?\.|\.)api(?:\?\.)?\s*\(', script)
                or re.search(r'Forma\[["\']api["\']\]\s*\(', script)
                or re.search(r'\bfetch\s*\(', script))


def validate_application(
    html: str, python_source: str, python_dependencies: list[str] | str | None = None,
) -> tuple[str, str, str]:
    if not isinstance(html, str) or not isinstance(python_source, str):
        raise GenerationError('The model must return HTML and Python source as strings.')
    html = html.strip()
    python_source = python_source.strip() + '\n'
    if not html.lower().startswith('<!doctype html') or '<html' not in html.lower() or '</html>' not in html.lower():
        raise GenerationError('The generated frontend was not a complete HTML document.')
    if len(html) > 250_000 or len(python_source) > 80_000:
        raise GenerationError('The generated application is too large. Split this phase into a smaller change.')
    if not has_forma_api(html):
        raise GenerationError('The generated frontend is not connected through Forma.api. Retry this phase.')
    try:
        tree = ast.parse(python_source, filename='main.py')
    except SyntaxError as exc:
        raise GenerationError(f'The generated FastAPI source has a syntax error on line {exc.lineno}.') from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _validate_import(alias.name)
        elif isinstance(node, ast.ImportFrom):
            _validate_import(node.module or '')
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            raise GenerationError(f'The generated backend uses a blocked operation: {node.func.id}.')
        elif isinstance(node, ast.Attribute) and node.attr.startswith('__'):
            raise GenerationError('The generated backend uses unsupported introspection.')
    if not re.search(r'(?m)^app\s*=\s*FastAPI\s*\(', python_source):
        raise GenerationError('The generated backend must define `app = FastAPI(...)` at module level.')
    if not re.search(r'["\']/api/health["\']', python_source):
        raise GenerationError('The generated backend is missing its /api/health endpoint.')
    compile(python_source, 'main.py', 'exec')
    return html, python_source, reviewed_requirements(python_dependencies)


def _validate_import(module: str) -> None:
    root = module.split('.')[0]
    if root not in ALLOWED_IMPORTS:
        raise GenerationError(f'The generated backend imports an unsupported package: {root}.')


def local_backend_source(name: str) -> str:
    return LOCAL_BACKEND.replace('__APP_NAME_JSON__', json.dumps(name))


def local_backend_html(name: str, brief: str, phase: int) -> str:
    return (LOCAL_FRONTEND
            .replace('__APP_NAME__', escape(name))
            .replace('__APP_BRIEF__', escape(brief[:240]))
            .replace('__CAN_EDIT__', 'true' if phase >= 2 else 'false'))


LOCAL_BACKEND = '''from contextlib import asynccontextmanager, contextmanager
import sqlite3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

APP_NAME = __APP_NAME_JSON__
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
        connection.execute("""CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        if connection.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            connection.executemany(
                "INSERT INTO items(title, completed) VALUES(?, ?)",
                [("Shape the first useful workflow", 0),
                 ("Invite feedback from a teammate", 0),
                 ("Celebrate a small release", 1)],
            )


@asynccontextmanager
async def lifespan(_app):
    initialize()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class ItemInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class CompletionInput(BaseModel):
    completed: bool


@app.get("/api/health")
def health():
    return {"status": "ok", "service": APP_NAME}


@app.get("/api/items")
def list_items():
    with database() as connection:
        rows = connection.execute(
            "SELECT id, title, completed, created_at FROM items ORDER BY completed, id DESC"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/items", status_code=201)
def create_item(body: ItemInput):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Give this item a clear title")
    with database() as connection:
        cursor = connection.execute("INSERT INTO items(title) VALUES(?)", (title,))
        row = connection.execute(
            "SELECT id, title, completed, created_at FROM items WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


@app.patch("/api/items/{item_id}")
def complete_item(item_id: int, body: CompletionInput):
    with database() as connection:
        cursor = connection.execute(
            "UPDATE items SET completed=? WHERE id=?", (int(body.completed), item_id)
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Item not found")
        row = connection.execute(
            "SELECT id, title, completed, created_at FROM items WHERE id=?", (item_id,)
        ).fetchone()
    return dict(row)


@app.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: int):
    with database() as connection:
        cursor = connection.execute("DELETE FROM items WHERE id=?", (item_id,))
        if not cursor.rowcount:
            raise HTTPException(404, "Item not found")
'''


LOCAL_FRONTEND = '''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__APP_NAME__</title><style>
:root{--ink:#1c2823;--muted:#718078;--paper:#f5f6f1;--card:#fff;--line:#e2e7df;--green:#256b4b;--lime:#d9f99d}*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,sans-serif;color:var(--ink);background:var(--paper)}button,input{font:inherit}button{cursor:pointer}button:focus-visible,input:focus-visible{outline:3px solid #256b4b44;outline-offset:2px}.app{max-width:1120px;margin:auto;padding:24px 34px 60px}nav{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:70px}.brand{display:flex;align-items:center;gap:11px;font-size:19px;font-weight:800}.logo{width:33px;height:33px;border-radius:10px;background:var(--ink);color:var(--lime);display:grid;place-items:center}.connection{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--muted);background:white;border:1px solid var(--line);padding:7px 11px;border-radius:20px}.connection i{width:7px;height:7px;border-radius:50%;background:#d69c3f}.connection.online i{background:#36a46c}.connection.offline i{background:#c65c4a}.hero{display:grid;grid-template-columns:1.25fr .75fr;gap:45px;align-items:end;margin-bottom:42px}.eyebrow{color:var(--green);font-size:10px;font-weight:800;letter-spacing:1.7px}.hero h1{font-size:clamp(40px,5.5vw,65px);line-height:1.04;letter-spacing:-3px;margin:15px 0 20px}.hero p{color:var(--muted);max-width:570px;font-size:16px}.server-card{background:var(--lime);border-radius:20px;padding:25px}.server-card small{font-size:10px;font-weight:800;letter-spacing:1px}.server-card strong{display:block;font-size:30px;margin:22px 0 4px}.server-card span{font-size:12px}.workspace{display:grid;grid-template-columns:1fr 290px;gap:18px}.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px}.section-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.section-head h2{font-size:19px;margin:0}.count{color:var(--muted);font-size:11px}.create-form{display:flex;gap:9px;margin:22px 0}.create-form input{min-width:0;flex:1;border:1px solid var(--line);border-radius:10px;padding:11px 12px;background:#fbfcf9}.primary{border:0;border-radius:10px;padding:11px 16px;background:var(--ink);color:white;font-weight:700}.secondary{border:1px solid var(--line);border-radius:9px;padding:8px 11px;background:white;color:var(--ink)}.items{display:grid;gap:0}.item{display:flex;align-items:center;gap:12px;padding:15px 0;border-top:1px solid var(--line)}.toggle{width:21px;height:21px;border:1px solid #b9c5b9;border-radius:50%;background:white;flex:none;color:transparent}.toggle.done{background:var(--green);border-color:var(--green);color:white}.item-title{flex:1;font-weight:600}.item.done .item-title{text-decoration:line-through;color:var(--muted)}.delete{border:0;background:transparent;color:#9aa299;padding:6px}.note{color:var(--muted);font-size:12px;line-height:1.7}.phase-note{margin-top:25px;padding:14px;background:#f0f4e9;border-radius:11px;color:#5b6e54;font-size:12px}.error{display:none;background:#fff0eb;color:#9c432b;padding:12px 14px;border-radius:10px;margin:15px 0;font-size:12px}.error.visible{display:block}.empty{text-align:center;padding:35px 10px;color:var(--muted)}button:disabled{opacity:.5;cursor:not-allowed}@media(max-width:760px){.app{padding:20px}.hero,.workspace{grid-template-columns:1fr}.hero{gap:24px}nav{margin-bottom:45px}.hero h1{letter-spacing:-2px}.create-form{flex-wrap:wrap}.create-form input{flex-basis:100%}}
</style></head><body><main class="app"><nav><div class="brand"><span class="logo">✦</span>__APP_NAME__</div><span class="connection" id="connection"><i></i><span>Connecting to FastAPI…</span></span></nav>
<section class="hero"><div><span class="eyebrow">A SHARED SPACE FOR FOCUSED WORK</span><h1>Move good work<br>forward, together.</h1><p>__APP_BRIEF__</p></div><aside class="server-card"><small>LIVE APPLICATION DATA</small><strong id="progress">—</strong><span>completed through your dedicated FastAPI service</span></aside></section>
<div class="error" id="error" role="alert"></div><section class="workspace"><article class="card"><div class="section-head"><h2>Team priorities</h2><span class="count" id="count">Loading…</span></div><form class="create-form" id="create-form"><input id="item-title" maxlength="160" placeholder="What needs to happen next?" aria-label="New item title" required><button class="primary" id="add-item">Add priority</button></form><div class="items" id="items"></div></article><aside class="card"><h2>Built to connect</h2><p class="note">This application talks to its own FastAPI process. Your data lives in the application's own SQLite workspace instead of this browser.</p><button class="secondary" id="refresh">Refresh from server</button><div class="phase-note" id="phase-note"></div></aside></section></main>
<script>
const canEdit=__CAN_EDIT__,itemsRoot=document.getElementById('items'),errorBox=document.getElementById('error');
const form=document.getElementById('create-form'),titleInput=document.getElementById('item-title');
if(!canEdit){titleInput.disabled=true;document.getElementById('add-item').disabled=true;document.getElementById('phase-note').textContent='Phase 1 establishes the live API and shared data view. Approve this phase to add creating, completing, and removing items.'}else{document.getElementById('phase-note').textContent='Create, complete, and remove priorities. Changes persist in the application database across preview and release.'}
function showError(message){errorBox.textContent=message;errorBox.classList.add('visible')}
function connection(online){const el=document.getElementById('connection');el.className='connection '+(online?'online':'offline');el.querySelector('span').textContent=online?'FastAPI connected':'Backend unavailable'}
function render(items){itemsRoot.replaceChildren();document.getElementById('count').textContent=items.length+' '+(items.length===1?'priority':'priorities');document.getElementById('progress').textContent=items.filter(x=>x.completed).length+' / '+items.length;if(!items.length){const empty=document.createElement('div');empty.className='empty';empty.textContent='A clear workspace. Add your first priority.';itemsRoot.append(empty)}items.forEach(item=>{const row=document.createElement('div');row.className='item'+(item.completed?' done':'');row.innerHTML='<button class="toggle" aria-label="Toggle completion">✓</button><span class="item-title"></span><button class="delete" aria-label="Delete item">×</button>';row.querySelector('.item-title').textContent=item.title;row.querySelector('.toggle').classList.toggle('done',!!item.completed);row.querySelector('.toggle').disabled=!canEdit;row.querySelector('.delete').hidden=!canEdit;row.querySelector('.toggle').onclick=async()=>{await Forma.api('/items/'+item.id,{method:'PATCH',body:JSON.stringify({completed:!item.completed})});await load()};row.querySelector('.delete').onclick=async()=>{await Forma.api('/items/'+item.id,{method:'DELETE'});await load()};itemsRoot.append(row)})}
async function load(){errorBox.classList.remove('visible');try{const data=await Forma.api('/items');render(data.items);connection(true)}catch(error){connection(false);showError('The application backend could not be reached. '+(error.message||'Please retry.'))}}
form.onsubmit=async event=>{event.preventDefault();const title=titleInput.value.trim();if(!title)return;try{await Forma.api('/items',{method:'POST',body:JSON.stringify({title})});titleInput.value='';await load()}catch(error){showError(error.message)}};
document.getElementById('refresh').onclick=load;load();
</script></body></html>'''
