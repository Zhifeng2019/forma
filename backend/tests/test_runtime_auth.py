"""Real dependency imports and authenticated requests through generated-app hosts."""

import asyncio
import importlib.metadata
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.app_origins import published_url
from app.backend_engine import reviewed_requirements
from app.database import workspace_db
from app.main import app
from app.runtime import RuntimeManager


@pytest.mark.parametrize('problem', [None, 'version', 'external-module'])
def test_dependency_probe_uses_pyjwt_import_name_and_checks_its_installation(tmp_path, problem):
    version = '0.0.0' if problem == 'version' else importlib.metadata.version('PyJWT')
    requirements = tmp_path / 'requirements.txt'
    requirements.write_text(f'PyJWT=={version}\n')
    if problem == 'external-module':
        (tmp_path / 'jwt.py').write_text('# This module is outside the virtual environment.\n')
    manager = RuntimeManager()
    matches, detail = asyncio.run(manager._dependencies_match(
        Path(sys.executable), requirements,
        manager._clean_environment(tmp_path, Path(sys.prefix)), tmp_path,
    ))
    assert matches is (problem is None), detail
    if problem == 'version':
        assert 'requires 0.0.0' in detail
    elif problem == 'external-module':
        assert 'not installed inside the application virtual environment' in detail


AUTH_SOURCE = '''
import jwt
from fastapi import FastAPI, Header, HTTPException

app = FastAPI()
SECRET = "generated-test-app-secret-at-least-32-bytes"

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/auth/login")
def login(body: dict):
    if body != {"email": "admin@example.com", "password": "test-password"}:
        raise HTTPException(401)
    return {"access_token": jwt.encode({"sub": "admin", "role": "admin"}, SECRET, algorithm="HS256")}

@app.get("/api/admin/settings")
def settings(authorization: str = Header(default="")):
    try:
        kind, token = authorization.split(" ", 1)
        if kind.lower() != "bearer":
            raise ValueError()
        user = jwt.decode(token, SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(401)
    return {"role": user["role"]}
'''


def test_app_login_authenticates_private_and_public_requests_without_studio_credentials():
    with TestClient(app) as client:
        account = client.post('/api/auth/register', json={
            'email': f'auth-{uuid.uuid4().hex}@example.com', 'name': 'Owner', 'password': 'password123',
        }).json()
        studio_headers = {'Authorization': f'Bearer {account["token"]}'}
        project = client.post('/api/projects', headers=studio_headers, json={
            'name': 'Authenticated app', 'brief': 'Test application login.', 'backend_mode': 'static',
            'source_format': 'single-file', 'auto_mode': False,
        }).json()
        project_id = project['id']
        with workspace_db(account['user']['id']) as db:
            db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                       (project_id, 1, 'Login', 'fastapi', 'single-file'))
            for path, content in {
                'index.html': '<html><body>Login test</body></html>',
                'backend/main.py': AUTH_SOURCE,
                'backend/requirements.txt': reviewed_requirements(['PyJWT']),
            }.items():
                db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (project_id, 'build', path, content, 1))
            db.execute("UPDATE projects SET current_version=1,backend_mode='fastapi',stage='review' WHERE id=?",
                       (project_id,))
        preview = client.post(f'/api/projects/{project_id}/preview-session', headers=studio_headers)
        assert preview.status_code == 200, preview.text
        published = client.post(f'/api/projects/{project_id}/publish', headers=studio_headers, json={})
        assert published.status_code == 200, published.text
        for base in (preview.json()['url'], published_url(project_id)):
            endpoint = base + 'api/admin/settings'
            assert client.get(endpoint).status_code == 401
            response = client.post(base + 'api/auth/login', json={
                'email': 'admin@example.com', 'password': 'test-password',
            })
            assert response.status_code == 200, response.text
            app_headers = {'Authorization': f'Bearer {response.json()["access_token"]}'}
            authenticated = client.get(endpoint, headers=app_headers)
            assert authenticated.status_code == 200, authenticated.text
            assert authenticated.json() == {'role': 'admin'}
            assert client.get(endpoint, headers=studio_headers).status_code == 401
            assert client.get(endpoint, headers={'Authorization': 'Bearer invalid'}).status_code == 401
        assert client.get('/api/me', headers=app_headers).status_code == 401
