import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from .config import log_configuration, settings
from .database import init_databases
from .jobs.recovery import recover_all_workspaces, recovery_loop
from .deployment_registry import deployment_artifacts, get_deployment
from .llm import GenerationError
from .api import cancel_generation_jobs, forward_runtime, router
from .api import preview_asset, preview_owner, preview_project
from .app_origins import ApplicationOriginMiddleware
from .runtime import inject_runtime_bootstrap, runtime_manager
from .frontend_builder import PackageBuildError, ensure_frontend_build, frontend_asset_path
from .studio_static import StudioStaticFiles
from .hosting import hosting_expiry_loop
from .policy import hosting_expired

init_databases()


@asynccontextmanager
async def lifespan(_app):
    log_configuration()
    recover_all_workspaces(startup=True)
    recovery = asyncio.create_task(recovery_loop())
    hosting = asyncio.create_task(hosting_expiry_loop())
    yield
    recovery.cancel()
    hosting.cancel()
    await asyncio.gather(recovery, hosting, return_exceptions=True)
    await cancel_generation_jobs()
    await runtime_manager.stop_all()


app = FastAPI(title='Forma — AI Product Studio', version='1.3.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip().rstrip('/') for origin in settings.cors_origins.split(',')],
                   allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.add_middleware(ApplicationOriginMiddleware)
app.include_router(router)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'forma'}


@app.get('/preview/{project_id}/{version}/{token}/', response_class=HTMLResponse)
async def isolated_preview(project_id: str, version: int, token: str):
    grant = preview_owner(project_id, version, token)
    return await preview_project(int(grant['sub']), project_id, version, grant['parent_origin'],
                                 f'/preview/{project_id}/{version}/{token}/api')


@app.get('/preview/{project_id}/{version}/{token}/assets/{path:path}')
async def isolated_preview_asset(project_id: str, version: int, token: str, path: str):
    grant = preview_owner(project_id, version, token)
    return await preview_asset(int(grant['sub']), project_id, version, path)


@app.api_route('/preview/{project_id}/{version}/{token}/api/{path:path}',
               methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
async def isolated_preview_runtime(project_id: str, version: int, token: str, path: str, request: Request):
    grant = preview_owner(project_id, version, token)
    return await forward_runtime(request, int(grant['sub']), project_id, version, 'preview', path)


def published_app(project_id: str):
    deployment = get_deployment(project_id)
    if not deployment:
        raise HTTPException(404, 'This application is not published')
    if hosting_expired(deployment['hosting_expires_at']):
        raise HTTPException(410, 'Hosting has expired. The owner can publish this application again.')
    try:
        artifacts = deployment_artifacts(deployment)
    except GenerationError as exc:
        raise HTTPException(404, 'The published application source is unavailable') from exc
    return {**deployment, **artifacts}


@app.get('/apps/{project_id}', response_class=HTMLResponse)
@app.get('/apps/{project_id}/', response_class=HTMLResponse)
async def hosted_app(project_id: str, request: Request):
    published = published_app(project_id)
    if published['source_format'] == 'multi-file' and request.url.path == f'/apps/{project_id}':
        return RedirectResponse(f'/apps/{project_id}/')
    html = published['html']
    if published['source_format'] == 'multi-file':
        try:
            html = await ensure_frontend_build(
                published['user_id'], project_id, published['version'], published['files'],
            )
        except PackageBuildError as exc:
            raise HTTPException(503, str(exc)) from exc
    if published['backend_mode'] == 'fastapi':
        html = inject_runtime_bootstrap(html, project_id, published['version'], published=True)
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})


@app.api_route('/apps/{project_id}/api/{path:path}',
               methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
async def hosted_runtime(project_id: str, path: str, request: Request):
    published = published_app(project_id)
    if published['backend_mode'] != 'fastapi':
        raise HTTPException(404, 'This published application has no backend')
    return await forward_runtime(
        request, published['user_id'], project_id, published['version'], 'public', path,
    )


@app.get('/apps/{project_id}/assets/{path:path}')
async def hosted_asset(project_id: str, path: str):
    published = published_app(project_id)
    if published['source_format'] != 'multi-file':
        raise HTTPException(404, 'This published application has no built assets')
    try:
        await ensure_frontend_build(published['user_id'], project_id, published['version'], published['files'])
        return FileResponse(frontend_asset_path(project_id, published['version'], path))
    except PackageBuildError as exc:
        raise HTTPException(404 if 'does not exist' in str(exc) else 503, str(exc)) from exc


frontend_dist = Path(__file__).resolve().parent.parent.parent / 'frontend' / 'dist'
if frontend_dist.exists():
    app.mount('/', StudioStaticFiles(directory=frontend_dist), name='frontend')
