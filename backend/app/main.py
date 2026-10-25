from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from .config import settings
from .database import init_databases, workspace_db
from .api import router

init_databases()
app = FastAPI(title='Forma — AI Product Studio', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(','),
                   allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(router)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'forma'}


def published_app(project_id: str):
    for path in (settings.data_path / 'users').glob('user_*.db'):
        user_id = int(path.stem.split('_')[1])
        with workspace_db(user_id) as db:
            project = db.execute('SELECT published_version FROM projects WHERE id=?', (project_id,)).fetchone()
            if project and project['published_version']:
                artifact = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                                      (project_id, 'index.html', project['published_version'])).fetchone()
                if artifact:
                    return artifact['content']
    raise HTTPException(404, 'This application is not published')


@app.get('/apps/{project_id}', response_class=HTMLResponse)
@app.get('/apps/{project_id}/', response_class=HTMLResponse)
def hosted_app(project_id: str):
    return HTMLResponse(published_app(project_id), headers={'Cache-Control': 'no-cache'})


frontend_dist = Path(__file__).resolve().parent.parent.parent / 'frontend' / 'dist'
if frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount('/', StaticFiles(directory=frontend_dist, html=True), name='frontend')
