import asyncio
import json
from pathlib import PurePosixPath
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
import httpx
from .database import control_db, workspace_db, rows
from .deps import current_user, admin_user, owned_project
from .schemas import RegisterInput, LoginInput, ProviderInput, PreferenceInput, ProjectInput, MessageInput, StageInput, PublishInput, VerificationInput, ArchitectureInput
from .verification.runner import verify_package
from .verification.review import latest_model_review
from .security import hash_password, verify_password, create_token, encrypt_secret, decrypt_secret
from .security import create_preview_token, decode_preview_token
from .app_origins import application_origin, preview_url, published_url, studio_origins
from .generation_context import read_version_context
from .engine import add_message, add_event, generate_stage, migrate_architecture, revise_document, safe_selector
from .llm import GenerationError
from .backend_engine import BACKEND_PATH, REQUIREMENTS_PATH
from .config import settings
from .runtime import RuntimeLaunchError, inject_runtime_bootstrap, runtime_manager
from .frontend_builder import (
    PackageBuildError, deployment_archive, ensure_frontend_build, frontend_asset_path,
    safe_path, version_directory,
)
from .features import FeatureFlag, feature_enabled
from .jobs.events import follow_frames, high_watermark, replay_events, replay_frames
from .jobs.leases import request_cancellation
from .jobs.models import JobCancelledError
from .jobs.service import active_job, get_job
from .jobs.usage_report import project_usage
from .spec.capabilities import assess_capabilities
from .spec.review import appspec_review
from .spec.schema import parse_appspec
from .deployment_registry import delete_deployment, upsert_deployment

router = APIRouter(prefix='/api')
_generation_jobs: dict[asyncio.Task, tuple[int, str]] = {}
_project_locks: dict[str, asyncio.Lock] = {}
# Projects whose autopilot is still running, mapped to whether the owner asked it to pause.
_autopilot: dict[str, bool] = {}


def project_lock(project_id: str) -> asyncio.Lock:
    """Serialize generation per project so user feedback never interleaves with an autopilot step."""
    return _project_locks.setdefault(project_id, asyncio.Lock())


async def _locked(project_id: str, coroutine) -> None:
    async with project_lock(project_id):
        await coroutine


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


_verification_jobs: dict[asyncio.Task, tuple[int, str, int]] = {}


def schedule_verification(user_id: int, project_id: str, version: int, coroutine) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    _verification_jobs[task] = (user_id, project_id, version)

    def finish(done: asyncio.Task) -> None:
        job = _verification_jobs.pop(done, None)
        if not job or done.cancelled():
            return
        exception = done.exception()
        if exception:
            with workspace_db(job[0]) as db:
                project = db.execute('SELECT status FROM projects WHERE id=?', (job[1],)).fetchone()
                if project:
                    db.execute("UPDATE projects SET status='error',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job[1],))
                    add_event(db, job[1], f'Background verification failed: {exception}', 'error')
                    add_message(db, job[1], 'agent', f'I hit a problem during verification: {exception}', 'error')

    task.add_done_callback(finish)
    return task


def verification_running(user_id: int, project_id: str, version: int) -> bool:
    return any(
        job_user == user_id and job_project == project_id and job_version == version and not task.done()
        for task, (job_user, job_project, job_version) in _verification_jobs.items()
    )


async def cancel_generation_jobs() -> None:
    jobs = list(_generation_jobs.items()) + list(_verification_jobs.items())
    for task, _job in jobs:
        task.cancel()
    if jobs:
        await asyncio.gather(*(task for task, _job in jobs), return_exceptions=True)
    for user_id, project_id in {job[:2] for _task, job in jobs}:
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
            items = db.execute('SELECT id,name,base_url,model,enabled,input_price_per_million,output_price_per_million,currency,created_at,api_key_encrypted FROM providers ORDER BY id')
        else:
            items = db.execute('SELECT id,name,base_url,model,enabled,input_price_per_million,output_price_per_million,currency,created_at,api_key_encrypted FROM providers WHERE enabled=1 ORDER BY id')
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
        cursor = db.execute('''INSERT INTO providers(
            name,base_url,model,api_key_encrypted,enabled,input_price_per_million,output_price_per_million,currency)
            VALUES(?,?,?,?,?,?,?,?)''', (
            body.name, body.base_url.rstrip('/'), body.model, encrypt_secret(body.api_key), int(body.enabled),
            body.input_price_per_million, body.output_price_per_million, body.currency.upper(),
        ))
        provider_id = cursor.lastrowid
    return {'id': provider_id, 'name': body.name}


@router.put('/providers/{provider_id}')
def update_provider(provider_id: int, body: ProviderInput, _admin=Depends(admin_user)):
    with control_db() as db:
        old = db.execute('SELECT api_key_encrypted FROM providers WHERE id=?', (provider_id,)).fetchone()
        if not old:
            raise HTTPException(404, 'Provider not found')
        key = encrypt_secret(body.api_key) if body.api_key else old['api_key_encrypted']
        db.execute('''UPDATE providers SET name=?,base_url=?,model=?,api_key_encrypted=?,enabled=?,
            input_price_per_million=?,output_price_per_million=?,currency=? WHERE id=?''', (
            body.name, body.base_url.rstrip('/'), body.model, key, int(body.enabled),
            body.input_price_per_million, body.output_price_per_million, body.currency.upper(), provider_id,
        ))
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


def verification_payload(user_id: int, project_id: str, version: int) -> dict:
    with workspace_db(user_id) as db:
        row = db.execute("SELECT content FROM artifacts WHERE project_id=? AND path='acceptance/report.json' AND version=?",
                         (project_id, version)).fetchone()
    report = json.loads(row['content']) if row else None
    if report:
        review = latest_model_review(user_id, project_id, version)
        if review and all(review.get(key) == report.get(key) for key in (
            'job_id', 'attempt_id', 'spec_hash', 'source_hash',
        )):
            report['review'] = review
    return {
        'verification': report,
        'verification_running': verification_running(user_id, project_id, version),
    }


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
        # Historical contracts belong to their version, never to a later LLM-generated revision.
        spec = db.execute('''SELECT content FROM artifacts WHERE project_id=? AND path='appspec.json'
            AND version=?''', (project_id, result['current_version'])).fetchone()
        review = appspec_review(spec['content'] if spec else None)
        result.update(review)
        result['capability'] = (
            assess_capabilities(parse_appspec(review['appspec']['spec']))
            if review['appspec_valid'] is True and review['appspec']['spec'].get('entities') else None
        )
        result['durable_jobs_enabled'] = feature_enabled(FeatureFlag.DURABLE_JOBS_V1)
        result['acceptance_gate_enabled'] = feature_enabled(FeatureFlag.ACCEPTANCE_GATE_V1)
        result['verification_available'] = has_acceptance_contract(db, project_id, result['current_version'])
        result.update(verification_payload(user_id, project_id, result['current_version']))
        result['active_job'] = active_job(db, project_id)
        result['published_url'] = published_url(project_id) if result['published_version'] else None
        return result


def has_acceptance_contract(db, project_id: str, version: int) -> bool:
    """Retain verification for old contracts without imposing them on new LLM builds.

    Either artifact opts the version in, so an incomplete historical contract still
    fails verification instead of silently bypassing its release gate.
    """
    return db.execute('''SELECT 1 FROM artifacts WHERE project_id=? AND version=?
        AND path IN ('appspec.json', 'acceptance/manifest.json') LIMIT 1''',
        (project_id, version)).fetchone() is not None


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
        if body.auto_mode:
            _autopilot[project_id] = False
        try:
            async with project_lock(project_id):
                await generate_stage(user['id'], project_id, provider)
            if body.auto_mode:
                for _ in range(5):
                    async with project_lock(project_id):
                        current = project_payload(user['id'], project_id)
                        if current['stage'] not in {'design', 'plan', 'build'} or current['status'] == 'error':
                            break
                        if _autopilot.get(project_id):
                            # Feedback applies to what the owner reviewed; they resume by approving.
                            with workspace_db(user['id']) as db:
                                db.execute('UPDATE projects SET auto_mode=0 WHERE id=?', (project_id,))
                                add_message(db, project_id, 'agent', 'Autopilot paused so your feedback is applied '
                                            'to the current step. Approve it when you are ready to continue.', 'chat')
                            break
                        # Claim the step before yielding so feedback cannot slip in and land after it.
                        with workspace_db(user['id']) as db:
                            db.execute("UPDATE projects SET status='working',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                       (project_id,))
                        await generate_stage(user['id'], project_id, provider)
        finally:
            _autopilot.pop(project_id, None)

    if body.defer:
        schedule_generation(user['id'], project_id, run_creation())
    else:
        await run_creation()
    return project_payload(user['id'], project_id)


@router.get('/projects/{project_id}')
def get_project(project_id: str, user=Depends(current_user)):
    return project_payload(user['id'], project_id)


@router.get('/projects/{project_id}/events')
def project_events(
    project_id: str, request: Request, after: int | None = None,
    limit: int = Query(200, ge=1, le=500), follow: bool = False,
    heartbeat_seconds: float = Query(15, gt=0, le=60), user=Depends(current_user),
):
    owned_project(user['id'], project_id)
    raw_cursor = request.headers.get('last-event-id')
    try:
        cursor = int(raw_cursor) if raw_cursor is not None else (after or 0)
    except ValueError as exc:
        raise HTTPException(422, 'Event cursor must be a non-negative integer') from exc
    if cursor < 0:
        raise HTTPException(422, 'Event cursor must be a non-negative integer')
    requested_cursor = cursor
    with workspace_db(user['id']) as db:
        high = high_watermark(db, project_id)
        if cursor > high:
            raise HTTPException(409, {'error': 'cursor_expired', 'high_watermark': high})
        events = replay_events(db, project_id, cursor, limit)
    cursor = events[-1]['id'] if events else cursor
    frames = (follow_frames(user['id'], project_id, requested_cursor, limit, heartbeat_seconds)
              if follow else replay_frames(events, project_id, cursor))
    return StreamingResponse(
        frames,
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive', 'X-Event-Cursor': str(cursor),
        },
    )


@router.get('/projects/{project_id}/usage')
def usage_report(project_id: str, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    return project_usage(user['id'], project_id)


@router.get('/projects/{project_id}/verification')
def get_verification(project_id: str, version: int | None = None, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    payload = verification_payload(user['id'], project_id, version or project['current_version'])
    return {'report': payload['verification'], 'running': payload['verification_running']}


@router.get('/projects/{project_id}/verification/diagnostics')
def get_verification_diagnostic(
    project_id: str, path: str, version: int | None = None, user=Depends(current_user),
):
    project = owned_project(user['id'], project_id)
    pure = PurePosixPath(path)
    if pure.is_absolute() or '..' in pure.parts or not path.startswith('acceptance/diagnostics/'):
        raise HTTPException(404, 'Verification diagnostic not found')
    selected_version = version or project['current_version']
    with workspace_db(user['id']) as db:
        row = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                         (project_id, path, selected_version)).fetchone()
    if not row:
        raise HTTPException(404, 'Verification diagnostic not found')
    return Response(content=row['content'], media_type='text/plain; charset=utf-8')


@router.get('/projects/{project_id}/verification/evidence')
def get_verification_evidence(
    project_id: str, path: str, version: int | None = None, user=Depends(current_user),
):
    project = owned_project(user['id'], project_id)
    pure = PurePosixPath(path)
    if pure.is_absolute() or '..' in pure.parts or not path.startswith('acceptance/evidence/'):
        raise HTTPException(404, 'Verification evidence not found')
    selected_version = version or project['current_version']
    try:
        target = safe_path(version_directory(project_id, selected_version), path)
    except PackageBuildError as exc:
        raise HTTPException(404, 'Verification evidence not found') from exc
    if not target.is_file():
        raise HTTPException(404, 'Verification evidence not found')
    return FileResponse(target)


@router.post('/projects/{project_id}/verify')
async def verify_project(project_id: str, body: VerificationInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if not feature_enabled(FeatureFlag.ACCEPTANCE_GATE_V1):
        raise HTTPException(409, 'Acceptance verification is not enabled on this studio')
    if project['status'] == 'working':
        raise HTTPException(409, 'Wait for generation to finish before verifying')
    version = body.version or project['current_version']
    if not version:
        raise HTTPException(409, 'Build an application before verifying')
    with workspace_db(user['id']) as db:
        if not has_acceptance_contract(db, project_id, version):
            raise HTTPException(409, 'This version has no stored acceptance contract. '
                                'Contract verification is available only for historical AppSpec versions.')
    selected = set(body.selected_check_ids) if body.selected_check_ids is not None else None
    try:
        if body.defer:
            schedule_verification(user['id'], project_id, version, verify_package(
                user['id'], project_id, version, force=True,
                include_optional=body.include_optional, selected_check_ids=selected,
                include_review=body.include_review,
            ))
        else:
            await verify_package(
                user['id'], project_id, version, force=True,
                include_optional=body.include_optional, selected_check_ids=selected,
                include_review=body.include_review,
            )
    except GenerationError as exc:
        raise HTTPException(409, str(exc)) from exc
    return project_payload(user['id'], project_id)


@router.post('/projects/{project_id}/jobs/{job_id}/cancel')
def cancel_project_job(project_id: str, job_id: str, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    with workspace_db(user['id']) as db:
        job = get_job(db, job_id)
        if not job or job['project_id'] != project_id:
            raise HTTPException(404, 'Generation job not found')
        changed = request_cancellation(db, job_id)
        current = get_job(db, job_id)
    return {
        'job_id': job_id,
        'status': current['status'],
        'current_attempt': current['current_attempt'],
        'changed': changed,
    }


@router.delete('/projects/{project_id}')
async def delete_project(project_id: str, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    await runtime_manager.remove_project(project_id)
    with workspace_db(user['id']) as db:
        for table in ['artifacts', 'versions', 'messages', 'events', 'projects']:
            db.execute(f'DELETE FROM {table} WHERE {"id" if table == "projects" else "project_id"}=?', (project_id,))
    delete_deployment(project_id)
    return {'ok': True}


@router.post('/projects/{project_id}/advance')
async def advance_project(project_id: str, body: StageInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['status'] == 'working':
        raise HTTPException(409, 'The agent is already working')
    if project_id in _autopilot:
        raise HTTPException(409, 'Autopilot is still building. Send feedback to pause it, or wait for it to finish.')
    if project['stage'] == 'deploy':
        return project_payload(user['id'], project_id)
    with control_db() as db:
        from .engine import provider_for_user
        provider = provider_for_user(db, user['id'])
    if body.defer:
        with workspace_db(user['id']) as db:
            db.execute("UPDATE projects SET status='working',updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
        schedule_generation(user['id'], project_id,
                            _locked(project_id, generate_stage(user['id'], project_id, provider, body.feedback)))
    else:
        await _locked(project_id, generate_stage(user['id'], project_id, provider, body.feedback))
    return project_payload(user['id'], project_id)


@router.post('/projects/{project_id}/messages')
async def send_message(project_id: str, body: MessageInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['status'] == 'working':
        raise HTTPException(409, 'The agent is already working')
    selection = safe_selector(body.selection)
    if project_id in _autopilot:
        _autopilot[project_id] = True
    with workspace_db(user['id']) as db:
        add_message(db, project_id, 'user', body.content + selection, metadata={'selection': body.selection or {}})
    with control_db() as db:
        from .engine import provider_for_user
        provider = provider_for_user(db, user['id'])

    async def run_message() -> None:
        async with project_lock(project_id):
            # An autopilot step may have finished while this waited; act on the stage the owner now sees.
            current = owned_project(user['id'], project_id)
            builds_application = current['stage'] in {'build', 'review'} and current['current_version'] > 0
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
    if project_id in _autopilot:
        raise HTTPException(409, 'Wait for autopilot to finish before migrating')
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
            authorization=request.headers.get('authorization', ''),
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
async def restart_runtime(project_id: str, version: int | None = None, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    if project['backend_mode'] != 'fastapi' or not project['current_version']:
        raise HTTPException(409, 'Build a FastAPI application before restarting its runtime')
    selected_version = version or project['current_version']
    source, requirements, source_format, files = runtime_artifacts(user['id'], project_id, selected_version)
    try:
        result = await runtime_manager.restart(
            project_id, selected_version, source, requirements, source_format, files,
        )
    except RuntimeLaunchError as exc:
        with workspace_db(user['id']) as db:
            add_event(db, project_id, f'Backend restart failed for version {selected_version}: {exc}', 'error')
        raise HTTPException(503, f'FastAPI version {selected_version} restart failed: {exc}') from exc
    with workspace_db(user['id']) as db:
        add_event(db, project_id, f'FastAPI version {selected_version} restarted and healthy', 'success')
    return result


@router.post('/projects/{project_id}/publish')
async def publish_project(project_id: str, body: PublishInput, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    version = body.version or project['current_version']
    if not version:
        raise HTTPException(409, 'Build at least one version before publishing')
    with workspace_db(user['id']) as db:
        requires_verification = (feature_enabled(FeatureFlag.ACCEPTANCE_GATE_V1)
                                 and has_acceptance_contract(db, project_id, version))
    if requires_verification and project['published_version'] != version:
        try:
            report = await verify_package(user['id'], project_id, version, force=True)
        except JobCancelledError as exc:
            raise HTTPException(409, 'Verification was cancelled. The existing release is unchanged.') from exc
        except GenerationError as exc:
            raise HTTPException(409, f'Verification could not be completed: {exc}') from exc
        if not report['can_publish']:
            failures = report['summary']['required_failures']
            raise HTTPException(409, f'Verification failed: {", ".join(failures) or "required checks"}')
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
    upsert_deployment(user['id'], project_id)
    return project_payload(user['id'], project_id)


@router.post('/projects/{project_id}/unpublish')
async def unpublish_project(project_id: str, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    with workspace_db(user['id']) as db:
        db.execute('UPDATE projects SET published_version=NULL WHERE id=?', (project_id,))
        add_event(db, project_id, 'Publication revoked')
    await runtime_manager.stop_project(project_id, channel='public')
    delete_deployment(project_id)
    return {'ok': True}


def version_artifacts(user_id: int, project_id: str, version: int) -> dict[str, str]:
    with workspace_db(user_id) as db:
        artifacts = db.execute('SELECT path,content FROM artifacts WHERE project_id=? AND version=?',
                               (project_id, version)).fetchall()
    if not artifacts:
        raise HTTPException(404, 'Version not found')
    return {artifact['path']: artifact['content'] for artifact in artifacts}


@router.get('/projects/{project_id}/package')
async def download_package(project_id: str, version: int | None = None, user=Depends(current_user)):
    user_id = user['id']
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


async def preview_asset(user_id: int, project_id: str, version: int, path: str):
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


@router.get('/projects/{project_id}/versions/{version}/context')
def get_generation_context(project_id: str, version: int, user=Depends(current_user)):
    owned_project(user['id'], project_id)
    with workspace_db(user['id']) as db:
        row = db.execute('SELECT generation_context FROM versions WHERE project_id=? AND version=?',
                         (project_id, version)).fetchone()
    if row is None:
        raise HTTPException(404, 'Version not found')
    try:
        context = read_version_context(row['generation_context'])
    except GenerationError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {'version': version, 'recorded': context is not None, 'context': context}


PICKER_SCRIPT = '''<script>(function(){
const studioOrigin=__STUDIO_ORIGIN__;
let picking=false,last=null;function path(el){if(el.id)return '#'+CSS.escape(el.id);let a=[];while(el&&el.nodeType===1&&a.length<4){let s=el.localName;if(el.classList.length)s+='.'+Array.from(el.classList).slice(0,2).map(CSS.escape).join('.');a.unshift(s);el=el.parentElement}return a.join(' > ')}
window.addEventListener('message',e=>{if(e.source===parent&&e.origin===studioOrigin&&e.data?.type==='forma-picker'){picking=e.data.enabled===true;document.body.style.cursor=picking?'crosshair':''}});
document.addEventListener('mouseover',e=>{if(!picking)return;if(last)last.style.outline='';last=e.target;last.style.outline='2px solid #f97316'},true);
document.addEventListener('click',e=>{if(!picking)return;e.preventDefault();e.stopPropagation();parent.postMessage({type:'forma-selection',selection:{selector:path(e.target),text:(e.target.innerText||e.target.value||'').slice(0,160)}},studioOrigin);picking=false;document.body.style.cursor='';if(last)last.style.outline=''},true);
})();</script>'''


@router.post('/projects/{project_id}/preview-session')
def preview_session(project_id: str, request: Request, response: Response, version: int | None = None, user=Depends(current_user)):
    project = owned_project(user['id'], project_id)
    selected = version if version is not None else project['current_version']
    files = version_artifacts(user['id'], project_id, selected)
    if not {'index.html', 'frontend/index.html'} & files.keys():
        raise HTTPException(404, 'No application preview is available yet')
    parent_origin = request.headers.get('origin', settings.studio_base_url).rstrip('/')
    if parent_origin not in studio_origins():
        raise HTTPException(403, 'Preview sessions must be opened from the studio')
    token, expires = create_preview_token(user['id'], project_id, selected, parent_origin)
    response.headers['Cache-Control'] = 'no-store'
    return {'url': preview_url(project_id, selected, token),
            'origin': application_origin(project_id, selected), 'expires_at': expires,
            'project_id': project_id, 'version': selected}


def preview_owner(project_id: str, version: int, token: str) -> dict:
    try:
        grant = decode_preview_token(token, project_id, version)
        user_id = int(grant['sub'])
    except Exception as exc:
        raise HTTPException(401, 'A valid preview session is required') from exc
    with control_db() as db:
        user = db.execute('SELECT status FROM users WHERE id=?', (user_id,)).fetchone()
    if not user or user['status'] != 'active':
        raise HTTPException(401, 'This account is not active')
    owned_project(user_id, project_id)
    version_source_format(user_id, project_id, version)
    return grant


async def preview_project(user_id: int, project_id: str, version: int, parent_origin: str, api_prefix: str):
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
        html = inject_runtime_bootstrap(html, project_id, version, published=False, api_prefix=api_prefix)
    picker = PICKER_SCRIPT.replace('__STUDIO_ORIGIN__', json.dumps(parent_origin).replace('<', '\\u003c'))
    html = html.replace('</body>', picker + '</body>') if '</body>' in html else html + picker
    return HTMLResponse(html, headers={'Cache-Control': 'no-store'})
