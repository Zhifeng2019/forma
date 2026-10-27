import asyncio
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
import httpx
from .database import control_db, workspace_db, rows
from .deps import current_user, admin_user, owned_project
from .schemas import RegisterInput, LoginInput, ProviderInput, PreferenceInput, ProjectInput, MessageInput, StageInput, PublishInput, ArchitectureInput
from .security import hash_password, verify_password, create_token, encrypt_secret, decrypt_secret
from .engine import add_message, add_event, generate_stage, migrate_architecture, revise_document, safe_selector
from .llm import GenerationError
from .backend_engine import BACKEND_PATH, REQUIREMENTS_PATH
from .config import settings
from .runtime import RuntimeLaunchError, inject_runtime_bootstrap, runtime_manager
from .frontend_builder import PackageBuildError, deployment_archive, ensure_frontend_build, frontend_asset_path
from .features import FeatureFlag, feature_enabled
from .spec.review import appspec_review

router = APIRouter(prefix='/api')
_generation_jobs: dict[asyncio.Task, tuple[int, str]] = {}


def schedule_generation(user_id: int, project_id: str, coroutine) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    _generation_jobs[task] = (user_id, project_id)

    def finish(done: asyncio.Task) -> None:
        job = _generation_jobs.pop(done, None)
        if not job or done.cancelled():
            return
        exception = done.exception()
        if exception:
            with workspace_db(job[0]) as db:
                project = db.execute('SELECT status FROM projects WHERE id=?', (job[1],)).fetchone()
                if project:
                    db.execute("UPDATE projects SET status='error',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job[1],))
                    add_event(db, job[1], f'Background generation failed: {exception}', 'error')
                    add_message(db, job[1], 'agent', f'I hit a problem: {exception}', 'error')

    task.add_done_callback(finish)
    return task


async def cancel_generation_jobs() -> None:
    jobs = list(_generation_jobs.items())
    for task, _job in jobs:
        task.cancel()
    if jobs:
        await asyncio.gather(*(task for task, _job in jobs), return_exceptions=True)
    for user_id, project_id in {job for _task, job in jobs}:
        with workspace_db(user_id) as db:
            project = db.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()
            if project and project['status'] == 'working':
                db.execute("UPDATE projects SET status='error',updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
                add_event(db, project_id, 'Generation stopped when the studio shut down. Retry this stage.', 'error')


def auth_payload(user):
    return {'token': create_token(user['id']), 'user': {'id': user['id'], 'email': user['email'], 'name': user['name'], 'role': user['role']}}


@router.post('/auth/register')
def register(body: RegisterInput):
    with control_db() as db:
        if db.execute('SELECT 1 FROM users WHERE email=?', (body.email.lower(),)).fetchone():
            raise HTTPException(409, 'An account with this email already exists')
        cursor = db.execute('INSERT INTO users(email,name,password_hash) VALUES(?,?,?)',
                            (body.email.lower(), body.name.strip(), hash_password(body.password)))
        user_id = cursor.lastrowid
        db.execute('INSERT INTO preferences(user_id) VALUES(?)', (user_id,))
        user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    from .database import workspace_for
    workspace_for(user_id)
    return auth_payload(user)


@router.post('/auth/login')
def login(body: LoginInput):
    with control_db() as db:
        user = db.execute('SELECT * FROM users WHERE email=?', (body.email.lower(),)).fetchone()
    if not user or not verify_password(body.password, user['password_hash']):
        raise HTTPException(401, 'Email or password is incorrect')
    if user['status'] != 'active':
        raise HTTPException(403, 'This account has been disabled')
    return auth_payload(user)


@router.get('/me')
def me(user=Depends(current_user)):
    return user


@router.get('/admin/users')
def list_users(_admin=Depends(admin_user)):
    with control_db() as db:
        users = rows(db.execute('SELECT id,email,name,role,status,created_at FROM users ORDER BY created_at DESC'))
    for user in users:
        with workspace_db(user['id']) as workspace:
            user['project_count'] = workspace.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
    return users


@router.patch('/admin/users/{user_id}')
def update_user(user_id: int, body: dict, admin=Depends(admin_user)):
    allowed = {'active', 'disabled'}
    if body.get('status') not in allowed and body.get('role') not in {'admin', 'user'}:
        raise HTTPException(400, 'No valid changes supplied')
    if user_id == admin['id'] and body.get('status') == 'disabled':
        raise HTTPException(400, 'You cannot disable your own account')
    with control_db() as db:
        if body.get('status') in allowed:
            db.execute('UPDATE users SET status=? WHERE id=?', (body['status'], user_id))
        if body.get('role') in {'admin', 'user'}:
            db.execute('UPDATE users SET role=? WHERE id=?', (body['role'], user_id))
    return {'ok': True}


@router.get('/providers')
def providers(user=Depends(current_user)):
    with control_db() as db:
        if user['role'] == 'admin':
            items = db.execute('SELECT id,name,base_url,model,enabled,created_at,api_key_encrypted FROM providers ORDER BY id')
        else:
            items = db.execute('SELECT id,name,base_url,model,enabled,created_at,api_key_encrypted FROM providers WHERE enabled=1 ORDER BY id')
        result = []
        for item in items:
            row = dict(item)
            row['has_key'] = bool(row.pop('api_key_encrypted'))
            result.append(row)
    return result


@router.post('/providers')
def create_provider(body: ProviderInput, _admin=Depends(admin_user)):
    if not body.base_url.startswith(('https://', 'http://localhost', 'http://127.0.0.1')):
        raise HTTPException(400, 'Provider URL must use HTTPS')
    with control_db() as db:
        cursor = db.execute('INSERT INTO providers(name,base_url,model,api_key_encrypted,enabled) VALUES(?,?,?,?,?)',
                            (body.name, body.base_url.rstrip('/'), body.model, encrypt_secret(body.api_key), int(body.enabled)))
        provider_id = cursor.lastrowid
    return {'id': provider_id, 'name': body.name}


@router.put('/providers/{provider_id}')
def update_provider(provider_id: int, body: ProviderInput, _admin=Depends(admin_user)):
    with control_db() as db:
        old = db.execute('SELECT api_key_encrypted FROM providers WHERE id=?', (provider_id,)).fetchone()
        if not old:
            raise HTTPException(404, 'Provider not found')
        key = encrypt_secret(body.api_key) if body.api_key else old['api_key_encrypted']
        db.execute('UPDATE providers SET name=?,base_url=?,model=?,api_key_encrypted=?,enabled=? WHERE id=?',
                   (body.name, body.base_url.rstrip('/'), body.model, key, int(body.enabled), provider_id))
    return {'ok': True}


@router.delete('/providers/{provider_id}')
def delete_provider(provider_id: int, _admin=Depends(admin_user)):
    with control_db() as db:
        db.execute('UPDATE preferences SET provider_id=NULL WHERE provider_id=?', (provider_id,))
        db.execute('DELETE FROM providers WHERE id=?', (provider_id,))
    return {'ok': True}


@router.post('/providers/{provider_id}/test')
async def test_provider(provider_id: int, _admin=Depends(admin_user)):
    with control_db() as db:
        provider = db.execute('SELECT * FROM providers WHERE id=?', (provider_id,)).fetchone()
    if not provider:
        raise HTTPException(404, 'Provider not found')
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            response = await client.get(provider['base_url'].rstrip('/') + '/models',
                headers={'Authorization': f'Bearer {decrypt_secret(provider["api_key_encrypted"])}'})
        if response.status_code >= 400:
            raise HTTPException(400, f'Provider returned HTTP {response.status_code}')
        return {'ok': True, 'message': 'Connection successful'}
    except httpx.HTTPError as exc:
        raise HTTPException(400, f'Connection failed: {exc}') from exc


@router.get('/preferences')
def get_preferences(user=Depends(current_user)):
    with control_db() as db:
        pref = db.execute('SELECT * FROM preferences WHERE user_id=?', (user['id'],)).fetchone()
    return dict(pref) if pref else {'provider_id': None, 'auto_mode': False, 'theme': 'light'}


@router.put('/preferences')
def update_preferences(body: PreferenceInput, user=Depends(current_user)):
    with control_db() as db:
        if body.provider_id and not db.execute('SELECT 1 FROM providers WHERE id=? AND enabled=1', (body.provider_id,)).fetchone():
            raise HTTPException(400, 'Selected provider is unavailable')
        db.execute('''INSERT INTO preferences(user_id,provider_id,auto_mode,theme) VALUES(?,?,?,?)
                      ON CONFLICT(user_id) DO UPDATE SET provider_id=excluded.provider_id,auto_mode=excluded.auto_mode,theme=excluded.theme,updated_at=CURRENT_TIMESTAMP''',
                   (user['id'], body.provider_id, int(body.auto_mode), body.theme))
    return body.model_dump()


def project_payload(user_id, project_id):
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, 'Project not found')
        result = dict(project)
        result['auto_mode'] = bool(result['auto_mode'])
        result['backend_enabled'] = result['backend_mode'] == 'fastapi'
        result['messages'] = rows(db.execute('SELECT * FROM messages WHERE project_id=? ORDER BY id', (project_id,)))
        result['events'] = rows(db.execute('SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT 30', (project_id,)))
        result['versions'] = rows(db.execute('SELECT id,version,label,note,backend_mode,source_format,created_at FROM versions WHERE project_id=? ORDER BY version DESC', (project_id,)))
        artifacts = db.execute('''SELECT a.* FROM artifacts a JOIN (SELECT path,MAX(version) version FROM artifacts WHERE project_id=? GROUP BY path) latest
                                  ON a.path=latest.path AND a.version=latest.version WHERE a.project_id=? ORDER BY a.path''', (project_id, project_id))
        result['artifacts'] = rows(artifacts)
        spec = db.execute('''SELECT content FROM artifacts WHERE project_id=? AND path='appspec.json'
            ORDER BY version DESC LIMIT 1''', (project_id,)).fetchone()
        result.update(appspec_review(spec['content'] if spec else None))
        result['appspec_enabled'] = feature_enabled(FeatureFlag.APPSPEC_V1)
        result['published_url'] = f'/apps/{project_id}/' if result['published_version'] else None
        return result


@router.get('/projects')
def list_projects(user=Depends(current_user)):
    with workspace_db(user['id']) as db:
        return rows(db.execute('SELECT * FROM projects ORDER BY updated_at DESC'))


@router.post('/projects')
async def create_project(body: ProjectInput, user=Depends(current_user)):
    project_id = uuid.uuid4().hex
    reason = 'Selected when this project was created.' if body.backend_mode != 'auto' else ''
    initial_status = 'working' if body.defer else 'ready'
    with workspace_db(user['id']) as db:
        db.execute('INSERT INTO projects(id,name,brief,auto_mode,backend_mode,backend_reason,source_format,status) VALUES(?,?,?,?,?,?,?,?)',
                   (project_id, body.name.strip(), body.brief.strip(), int(body.auto_mode), body.backend_mode, reason, body.source_format, initial_status))
        add_message(db, project_id, 'user', body.brief.strip(), 'brief')
        add_message(db, project_id, 'agent', 'I’m shaping your idea into a focused product description. I’ll keep the scope clear and choose only the architecture it needs.', 'stage')
        add_event(db, project_id, 'Project created')
    with control_db() as db:
        from .engine import provider_for_user
        provider = provider_for_user(db, user['id'])

    async def run_creation() -> None:
        await generate_stage(user['id'], project_id, provider)
        if body.auto_mode:
            for _ in range(5):
                current = project_payload(user['id'], project_id)
                if current['stage'] not in {'design', 'plan', 'build'} or current['status'] == 'error':
                    break
                await generate_stage(user['id'], project_id, provider)

    if body.defer:
        schedule_generation(user['id'], project_id, run_creation())
    else:
        await run_creation()
    return project_payload(user['id'], project_id)


@router.get('/projects/{project_id}')
def get_project(project_id: str, user=Depends(current_user)):
    return project_payload(user['id'], project_id)


@router.delete('/projects/{project_id}')
async def delete_project(project_id: str, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    await runtime_manager.remove_project(project_id)
    with workspace_db(user['id']) as db:
        for table in ['artifacts', 'versions', 'messages', 'events', 'projects']:
            db.execute(f'DELETE FROM {table} WHERE {"id" if table == "projects" else "project_id"}=?', (project_id,))
    return {'ok': True}


@router.post('/projects/{project_id}/advance')
async def advance_project(project_id: str, body: StageInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['status'] == 'working':
        raise HTTPException(409, 'The agent is already working')
    if project['stage'] == 'deploy':
        return project_payload(user['id'], project_id)
    if feature_enabled(FeatureFlag.APPSPEC_V1) and project['stage'] == 'build' and not project['current_version']:
        with workspace_db(user['id']) as db:
            spec = db.execute('''SELECT content FROM artifacts WHERE project_id=? AND path='appspec.json'
                ORDER BY version DESC LIMIT 1''', (project_id,)).fetchone()
        review = appspec_review(spec['content'] if spec else None, for_compilation=True)
        if review['appspec_valid'] is False:
            raise HTTPException(409, f'AppSpec requires correction before building: {review["appspec_error"]}')
    with control_db() as db:
        from .engine import provider_for_user
        provider = provider_for_user(db, user['id'])
    if body.defer:
        with workspace_db(user['id']) as db:
            db.execute("UPDATE projects SET status='working',updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
        schedule_generation(user['id'], project_id, generate_stage(user['id'], project_id, provider, body.feedback))
    else:
        await generate_stage(user['id'], project_id, provider, body.feedback)
    return project_payload(user['id'], project_id)


@router.post('/projects/{project_id}/messages')
async def send_message(project_id: str, body: MessageInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['status'] == 'working':
        raise HTTPException(409, 'The agent is already working')
    selection = safe_selector(body.selection)
    with workspace_db(user['id']) as db:
        add_message(db, project_id, 'user', body.content + selection, metadata={'selection': body.selection or {}})
    with control_db() as db:
        from .engine import provider_for_user
        provider = provider_for_user(db, user['id'])

    async def run_message() -> None:
        builds_application = project['stage'] in {'build', 'review'} and (
            project['current_version'] > 0 or not feature_enabled(FeatureFlag.APPSPEC_V1)
        )
        if builds_application:
            await generate_stage(user['id'], project_id, provider, body.content + selection, revise=True)
        else:
            await revise_document(user['id'], project_id, provider, body.content)

    if body.defer:
        with workspace_db(user['id']) as db:
            db.execute("UPDATE projects SET status='working',updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
        schedule_generation(user['id'], project_id, run_message())
    else:
        await run_message()
    return project_payload(user['id'], project_id)


@router.post('/projects/{project_id}/architecture')
async def change_architecture(project_id: str, body: ArchitectureInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['status'] == 'working':
        raise HTTPException(409, 'Wait for the current generation to finish before migrating')
    if project['backend_mode'] == body.target_mode:
        raise HTTPException(409, f'This project already uses {body.target_mode} architecture')
    with control_db() as db:
        from .engine import provider_for_user
        provider = provider_for_user(db, user['id'])

    async def run_migration() -> None:
        await migrate_architecture(
            user['id'], project_id, body.target_mode, provider, body.feedback, deferred=body.defer,
        )
        if body.target_mode == 'static' and project_payload(user['id'], project_id)['status'] == 'ready':
            # Only a successful migration replaces the working preview. Published
            # FastAPI versions remain available until explicit republication.
            await runtime_manager.stop_project(project_id, channel='preview')

    try:
        if body.defer:
            with workspace_db(user['id']) as db:
                db.execute("UPDATE projects SET status='working',updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
            schedule_generation(user['id'], project_id, run_migration())
        else:
            await run_migration()
    except GenerationError as exc:
        raise HTTPException(409, str(exc)) from exc
    return project_payload(user['id'], project_id)


def version_backend_mode(user_id: int, project_id: str, version: int) -> str:
    with workspace_db(user_id) as db:
        row = db.execute('SELECT backend_mode FROM versions WHERE project_id=? AND version=?',
                         (project_id, version)).fetchone()
        if row:
            return row['backend_mode']
        project = db.execute('SELECT backend_mode,current_version FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, 'Project not found')
        if project['current_version'] == version:
            return project['backend_mode']
    raise HTTPException(404, 'Version not found')


def version_source_format(user_id: int, project_id: str, version: int) -> str:
    with workspace_db(user_id) as db:
        row = db.execute('SELECT source_format FROM versions WHERE project_id=? AND version=?',
                         (project_id, version)).fetchone()
        if row:
            return row['source_format']
        project = db.execute('SELECT source_format,current_version FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project:
            raise HTTPException(404, 'Project not found')
        if project['current_version'] == version:
            return project['source_format']
    raise HTTPException(404, 'Version not found')


def runtime_artifacts(user_id: int, project_id: str, version: int) -> tuple[str, str, str, dict[str, str]]:
    if version_backend_mode(user_id, project_id, version) != 'fastapi':
        raise HTTPException(409, 'This version is frontend only')
    source_format = version_source_format(user_id, project_id, version)
    with workspace_db(user_id) as db:
        artifacts = db.execute('SELECT path,content FROM artifacts WHERE project_id=? AND version=?',
                               (project_id, version)).fetchall()
    contents = {artifact['path']: artifact['content'] for artifact in artifacts}
    if BACKEND_PATH not in contents or REQUIREMENTS_PATH not in contents:
        raise HTTPException(404, 'This version does not contain a FastAPI backend')
    return contents[BACKEND_PATH], contents[REQUIREMENTS_PATH], source_format, contents


def runtime_response(upstream: httpx.Response) -> Response:
    headers = {'Cache-Control': 'no-store'}
    if upstream.headers.get('content-type'):
        headers['Content-Type'] = upstream.headers['content-type']
    return Response(content=upstream.content, status_code=upstream.status_code, headers=headers)


async def forward_runtime(
    request: Request, user_id: int, project_id: str, version: int, channel: str, path: str,
) -> Response:
    source, requirements, source_format, files = runtime_artifacts(user_id, project_id, version)
    try:
        if int(request.headers.get('content-length', '0')) > 2_000_000:
            raise HTTPException(413, 'Application request body is limited to 2 MB')
    except ValueError:
        pass
    body = await request.body()
    if len(body) > 2_000_000:
        raise HTTPException(413, 'Application request body is limited to 2 MB')
    try:
        upstream = await runtime_manager.request(
            project_id, version, channel, source, requirements, request.method, path,
            request.url.query, body, request.headers.get('content-type', ''),
            source_format=source_format, files=files,
        )
    except RuntimeLaunchError as exc:
        detail = ('The application backend is temporarily unavailable. Please try again shortly.'
                  if channel == 'public' else str(exc))
        raise HTTPException(503, detail) from exc
    return runtime_response(upstream)


@router.get('/projects/{project_id}/runtime')
async def runtime_status(project_id: str, check: bool = False, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['backend_mode'] != 'fastapi':
        return {'enabled': False, 'status': 'frontend-only', 'healthy': False, 'version': 0, 'logs': ''}
    if not project['current_version']:
        return {'enabled': True, 'status': 'stopped', 'healthy': False, 'version': 0, 'logs': '', 'started_at': None}
    return await runtime_manager.status(project_id, project['current_version'], check_health=check)


@router.post('/projects/{project_id}/runtime/restart')
async def restart_runtime(project_id: str, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['backend_mode'] != 'fastapi' or not project['current_version']:
        raise HTTPException(409, 'Build a FastAPI application before restarting its runtime')
    source, requirements, source_format, files = runtime_artifacts(user['id'], project_id, project['current_version'])
    try:
        result = await runtime_manager.restart(
            project_id, project['current_version'], source, requirements, source_format, files,
        )
    except RuntimeLaunchError as exc:
        with workspace_db(user['id']) as db:
            add_event(db, project_id, f'Backend restart failed: {exc}', 'error')
        raise HTTPException(503, str(exc)) from exc
    with workspace_db(user['id']) as db:
        add_event(db, project_id, f'FastAPI version {project["current_version"]} restarted and healthy', 'success')
    return result


@router.api_route('/projects/{project_id}/runtime/{version}/{path:path}',
                  methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
async def preview_runtime(project_id: str, version: int, path: str, request: Request, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    return await forward_runtime(request, user['id'], project_id, version, 'preview', path)


@router.post('/projects/{project_id}/publish')
async def publish_project(project_id: str, body: PublishInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    version = body.version or project['current_version']
    if not version:
        raise HTTPException(409, 'Build at least one version before publishing')
    if version_backend_mode(user['id'], project_id, version) == 'fastapi':
        runtime_artifacts(user['id'], project_id, version)
    with workspace_db(user['id']) as db:
        artifact_path = 'frontend/index.html' if version_source_format(user['id'], project_id, version) == 'multi-file' else 'index.html'
        if not db.execute('SELECT 1 FROM artifacts WHERE project_id=? AND path=? AND version=?', (project_id, artifact_path, version)).fetchone():
            raise HTTPException(404, 'Version not found')
        db.execute('UPDATE projects SET published_version=?,stage=?,stage_index=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (version, 'deploy', 5, project_id))
        add_event(db, project_id, f'Version {version} published', 'success')
        add_message(db, project_id, 'agent', f'Version {version} is live. Your public link is ready to share.', 'deployment')
    await runtime_manager.stop_project(project_id, channel='public', keep_version=version)
    return project_payload(user['id'], project_id)


@router.post('/projects/{project_id}/unpublish')
async def unpublish_project(project_id: str, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    with workspace_db(user['id']) as db:
        db.execute('UPDATE projects SET published_version=NULL WHERE id=?', (project_id,))
        add_event(db, project_id, 'Publication revoked')
    await runtime_manager.stop_project(project_id, channel='public')
    return {'ok': True}


def version_artifacts(user_id: int, project_id: str, version: int) -> dict[str, str]:
    with workspace_db(user_id) as db:
        artifacts = db.execute('SELECT path,content FROM artifacts WHERE project_id=? AND version=?',
                               (project_id, version)).fetchall()
    if not artifacts:
        raise HTTPException(404, 'Version not found')
    return {artifact['path']: artifact['content'] for artifact in artifacts}


@router.get('/projects/{project_id}/package')
async def download_package(project_id: str, access_token: str, version: int | None = None):
    from .security import decode_token
    try:
        user_id = decode_token(access_token)
    except Exception as exc:
        raise HTTPException(401, 'A valid download session is required') from exc
    project = owned_project(user_id, project_id)
    version = version or project['current_version']
    if version_source_format(user_id, project_id, version) != 'multi-file':
        raise HTTPException(409, 'Deployment archives are available for multi-file projects')
    try:
        files = version_artifacts(user_id, project_id, version)
        await ensure_frontend_build(user_id, project_id, version, files)
        content = deployment_archive(
            user_id, project_id, version, files, version_backend_mode(user_id, project_id, version),
        )
    except PackageBuildError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=content, media_type='application/zip', headers={
        'Content-Disposition': f'attachment; filename="forma-{project_id[:8]}-v{version}.zip"',
        'Cache-Control': 'no-store',
    })


@router.get('/projects/{project_id}/assets/{path:path}')
async def preview_asset(project_id: str, path: str, request: Request, version: int | None = None, access_token: str | None = None):
    from .security import decode_token
    token = access_token or request.cookies.get('forma_preview')
    try:
        user_id = decode_token(token or '')
    except Exception as exc:
        raise HTTPException(401, 'A valid preview session is required') from exc
    project = owned_project(user_id, project_id)
    version = version or int(request.cookies.get('forma_preview_version') or project['current_version'])
    if version_source_format(user_id, project_id, version) != 'multi-file':
        raise HTTPException(404, 'This version has no built frontend assets')
    try:
        await ensure_frontend_build(user_id, project_id, version, version_artifacts(user_id, project_id, version))
        return FileResponse(frontend_asset_path(project_id, version, path))
    except PackageBuildError as exc:
        raise HTTPException(404 if 'does not exist' in str(exc) else 503, str(exc)) from exc


@router.get('/projects/{project_id}/versions/{version}')
async def get_version(project_id: str, version: int, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    with workspace_db(user['id']) as db:
        artifact = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?', (project_id, 'index.html', version)).fetchone()
    if not artifact and version_source_format(user['id'], project_id, version) != 'multi-file':
        raise HTTPException(404, 'Version not found')
    if version_source_format(user['id'], project_id, version) == 'multi-file':
        try:
            return {'html': await ensure_frontend_build(
                user['id'], project_id, version, version_artifacts(user['id'], project_id, version),
            )}
        except PackageBuildError as exc:
            raise HTTPException(503, str(exc)) from exc
    return {'html': artifact['content']}


PICKER_SCRIPT = '''<script>
let picking=false,last=null;function path(el){if(el.id)return '#'+CSS.escape(el.id);let a=[];while(el&&el.nodeType===1&&a.length<4){let s=el.localName;if(el.classList.length)s+='.'+Array.from(el.classList).slice(0,2).map(CSS.escape).join('.');a.unshift(s);el=el.parentElement}return a.join(' > ')}
window.addEventListener('message',e=>{if(e.data?.type==='forma-picker'){picking=e.data.enabled;document.body.style.cursor=picking?'crosshair':''}});
document.addEventListener('mouseover',e=>{if(!picking)return;if(last)last.style.outline='';last=e.target;last.style.outline='2px solid #f97316'},true);
document.addEventListener('click',e=>{if(!picking)return;e.preventDefault();e.stopPropagation();parent.postMessage({type:'forma-selection',selection:{selector:path(e.target),text:(e.target.innerText||e.target.value||'').slice(0,160)}},'*');picking=false;document.body.style.cursor='';if(last)last.style.outline=''},true);
</script>'''


@router.get('/projects/{project_id}/preview', response_class=HTMLResponse)
async def preview_project(project_id: str, access_token: str, version: int | None = None):
    from .security import decode_token
    try:
        user_id = decode_token(access_token)
    except Exception as exc:
        raise HTTPException(401, 'A valid preview session is required') from exc
    project = owned_project(user_id, project_id)
    version = version or project['current_version']
    with workspace_db(user_id) as db:
        artifact = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?', (project_id, 'index.html', version)).fetchone()
    source_format = version_source_format(user_id, project_id, version)
    if not artifact and source_format != 'multi-file':
        raise HTTPException(404, 'No application preview is available yet')
    if source_format == 'multi-file':
        try:
            html = await ensure_frontend_build(
                user_id, project_id, version, version_artifacts(user_id, project_id, version),
            )
        except PackageBuildError as exc:
            raise HTTPException(503, str(exc)) from exc
    else:
        html = artifact['content']
    if version_backend_mode(user_id, project_id, version) == 'fastapi':
        html = inject_runtime_bootstrap(html, project_id, version, published=False)
    html = html.replace('</body>', PICKER_SCRIPT + '</body>')
    response = HTMLResponse(html, headers={'Cache-Control': 'no-store', 'Content-Security-Policy': "frame-ancestors 'self' http://localhost:5173"})
    response.set_cookie('forma_preview', access_token, max_age=settings.access_token_days * 86400,
                        path=f'/api/projects/{project_id}', httponly=True, samesite='lax')
    response.set_cookie('forma_preview_version', str(version), max_age=settings.access_token_days * 86400,
                        path=f'/api/projects/{project_id}', httponly=True, samesite='lax')
    return response
