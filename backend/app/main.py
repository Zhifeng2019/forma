from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from .config import settings
from .database import init_databases
from .deployment_registry import deployment_artifacts, get_deployment
from .llm import GenerationError
from .api import cancel_generation_jobs, forward_runtime, router
from .runtime import inject_runtime_bootstrap, runtime_manager
from .frontend_builder import PackageBuildError, ensure_frontend_build, frontend_asset_path

init_databases()


@asynccontextmanager
async def lifespan(_app):
    yield
    await cancel_generation_jobs()
    await runtime_manager.stop_all()


app = FastAPI(title='Forma — AI Product Studio', version='1.3.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(','),
                   allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(router)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'forma'}


def published_app(project_id: str):
    deployment = get_deployment(project_id)
    if not deployment:
        raise HTTPException(404, 'This application is not published')
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
    from fastapi.staticfiles import StaticFiles
    app.mount('/', StaticFiles(directory=frontend_dist, html=True), name='frontend')
