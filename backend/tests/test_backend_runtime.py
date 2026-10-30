import subprocess
import time
import pytest

from fastapi.testclient import TestClient
from app.backend_engine import (
    default_requirements, local_backend_html, local_backend_source,
    recommend_backend, runtime_requirements, validate_application,
)
from app.config import ROOT as BACKEND_ROOT
from app.config import Settings, settings
from app.llm import GenerationError
from app.main import app


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def register(client, email):
    response = client.post('/api/auth/register', json={
        'email': email, 'name': 'Backend Maker', 'password': 'password123',
    })
    assert response.status_code == 200, response.text
    return response.json()['token']


def test_architecture_recommendation_and_source_policy():
    assert recommend_backend('A personal breathing exercise timer')[0] is False
    required, reason = recommend_backend('A shared team workspace with a database and authenticated accounts')
    assert required is True
    assert 'server-side API or database' in reason
    html, source, requirements = validate_application(
        local_backend_html('Policy Check', 'A shared API-backed workspace', 2),
        local_backend_source('Policy Check'),
    )
    assert 'Forma.api(' in html
    assert 'app = FastAPI(' in source
    assert requirements == default_requirements()
    assert 'fastapi==' in requirements
    with pytest.raises(GenerationError, match='unsupported package'):
        validate_application(html, 'import os\nfrom fastapi import FastAPI\napp = FastAPI()\n@app.get("/api/health")\ndef health():\n return {"status":"ok"}')
    with pytest.raises(GenerationError, match='Forma.api'):
        validate_application('<!doctype html><html></html>', source)


def test_legacy_requirements_gain_email_support_once():
    legacy = 'fastapi==0.139.0\n'
    enriched = runtime_requirements(legacy)
    assert enriched.count('email-validator==') == 1
    assert runtime_requirements(enriched) == enriched


def test_relative_data_directory_is_absolute_for_subprocesses():
    assert Settings(data_dir='data').data_path == BACKEND_ROOT.parent / 'data'
    assert Settings(data_dir=str(BACKEND_ROOT / 'data')).data_path == BACKEND_ROOT.parent / 'data'


def test_fastapi_preview_crud_publish_and_cleanup():
    with TestClient(app) as client:
        token = register(client, 'backend@example.com')
        response = client.post('/api/projects', headers=auth(token), json={
            'source_format': 'single-file',
            'name': 'Shared Priorities',
            'brief': 'A shared team workspace with a database for priorities and live progress.',
            'backend_mode': 'auto', 'auto_mode': False,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        project_id = project['id']
        assert project['backend_mode'] == 'fastapi'
        assert project['backend_enabled'] is True

        for expected in ('plan', 'build', 'build'):
            response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={'feedback': ''})
            assert response.status_code == 200, response.text
            project = response.json()
            assert project['stage'] == expected
        assert project['current_version'] == 1
        paths = {artifact['path'] for artifact in project['artifacts']}
        assert {'index.html', 'backend/main.py', 'backend/requirements.txt'} <= paths

        preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}')
        assert preview.status_code == 200
        assert 'window.Forma=Object.freeze' in preview.text
        assert f'/api/projects/{project_id}/runtime/1' in preview.text
        assert 'forma-picker' in preview.text
        status = client.get(f'/api/projects/{project_id}/runtime', headers=auth(token)).json()
        assert status['status'] == 'stopped'
        assert client.get(f'/apps/{project_id}/api/health').status_code == 404

        private_api = f'/api/projects/{project_id}/runtime/1'
        assert client.get(f'{private_api}/health').status_code == 401
        response = client.get(f'{private_api}/health', headers=auth(token))
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'ok'
        assert response.json()['service'] == 'Shared Priorities'
        environment = settings.data_path / 'projects' / project_id / '.venv'
        assert not list(environment.glob('lib/python*/site-packages/_forma_verified_studio.pth'))
        verified = subprocess.run(
            [str(environment / 'bin' / 'python'), '-c',
             'import fastapi,uvicorn,pydantic,email_validator,pathlib,sysconfig;'
             'site=pathlib.Path(sysconfig.get_path("purelib")).resolve();'
             'assert all(pathlib.Path(module.__file__).resolve().is_relative_to(site) '
             'for module in (fastapi,uvicorn,pydantic,email_validator)); print(site)'],
            capture_output=True, text=True, timeout=30,
        )
        assert verified.returncode == 0, verified.stderr
        assert str(environment) in verified.stdout

        response = client.post(f'{private_api}/items', headers=auth(token), json={'title': 'Verify the release'})
        assert response.status_code == 201, response.text
        item = response.json()
        response = client.patch(f'{private_api}/items/{item["id"]}', headers=auth(token), json={'completed': True})
        assert response.status_code == 200
        assert response.json()['completed'] == 1

        response = client.post(f'/api/projects/{project_id}/runtime/restart', headers=auth(token))
        assert response.status_code == 200, response.text
        assert response.json()['healthy'] is True
        items = client.get(f'{private_api}/items', headers=auth(token)).json()['items']
        assert any(row['title'] == 'Verify the release' and row['completed'] == 1 for row in items)

        other_token = register(client, 'not-the-owner@example.com')
        assert client.get(f'{private_api}/items', headers=auth(other_token)).status_code == 404
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        public_html = client.get(f'/apps/{project_id}/')
        assert public_html.status_code == 200
        assert f'/apps/{project_id}/api' in public_html.text
        assert 'privatePreview=false' in public_html.text
        health = client.get(f'/apps/{project_id}/api/health')
        assert health.status_code == 200, health.text
        public_items = client.get(f'/apps/{project_id}/api/items')
        assert public_items.status_code == 200
        assert any(row['title'] == 'Verify the release' for row in public_items.json()['items'])
        response = client.post(f'/apps/{project_id}/api/items', json={'title': 'Created through the public API'})
        assert response.status_code == 201, response.text

        assert client.post(f'/api/projects/{project_id}/unpublish', headers=auth(token)).status_code == 200
        assert client.get(f'/apps/{project_id}/api/health').status_code == 404
        assert client.get(f'/apps/{project_id}/').status_code == 404
        assert client.get(f'{private_api}/items', headers=auth(token)).status_code == 200

        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200
        assert not (settings.data_path / 'projects' / project_id).exists()


def test_architecture_migration_preserves_history_and_published_version():
    with TestClient(app) as client:
        token = register(client, 'migration@example.com')
        response = client.post('/api/projects', headers=auth(token), json={
            'source_format': 'single-file',
            'name': 'Migration Workspace', 'brief': 'A personal planning workspace that may later need shared data.',
            'backend_mode': 'static', 'auto_mode': False,
        })
        project = response.json()
        project_id = project['id']
        for _ in range(3):
            response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
            project = response.json()
        assert project['current_version'] == 1 and project['backend_mode'] == 'static'
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200
        assert client.get(f'/apps/{project_id}/api/health').status_code == 404
        assert 'privatePreview=false' not in client.get(f'/apps/{project_id}/').text

        response = client.post(f'/api/projects/{project_id}/architecture', headers=auth(token), json={
            'target_mode': 'fastapi', 'feedback': 'Add shared priorities without changing the phase.',
        })
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['backend_mode'] == 'fastapi'
        assert project['current_version'] == 2 and project['published_version'] == 1
        assert project['stage'] == 'deploy' and project['phase_index'] == 1
        assert project['versions'][0]['backend_mode'] == 'fastapi'
        assert project['versions'][0]['label'] == 'FastAPI migration'
        assert client.get(f'/apps/{project_id}/api/health').status_code == 404
        assert 'privatePreview=false' not in client.get(f'/apps/{project_id}/').text
        preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}&version=2')
        assert 'window.Forma=Object.freeze' in preview.text
        response = client.get(f'/api/projects/{project_id}/runtime/2/health', headers=auth(token))
        assert response.status_code == 200, response.text

        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200
        assert client.get(f'/apps/{project_id}/api/health').status_code == 200
        response = client.post(f'/api/projects/{project_id}/architecture', headers=auth(token), json={
            'target_mode': 'static', 'feedback': 'Return to a portable browser-only release.',
        })
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['backend_mode'] == 'static'
        assert project['current_version'] == 3 and project['published_version'] == 2
        assert project['versions'][0]['backend_mode'] == 'static'
        assert client.get(f'/apps/{project_id}/api/health').status_code == 200
        assert 'privatePreview=false' in client.get(f'/apps/{project_id}/').text
        old_fastapi_preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}&version=2')
        assert 'window.Forma=Object.freeze' in old_fastapi_preview.text
        static_preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}&version=3')
        assert 'window.Forma=Object.freeze' not in static_preview.text
        assert client.get(f'/api/projects/{project_id}/runtime/3/health', headers=auth(token)).status_code == 409

        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200
        assert client.get(f'/apps/{project_id}/api/health').status_code == 404
        assert 'privatePreview=false' not in client.get(f'/apps/{project_id}/').text
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200


def test_deferred_architecture_migration_returns_working_then_updates():
    with TestClient(app) as client:
        token = register(client, 'deferred-migration@example.com')
        response = client.post('/api/projects', headers=auth(token), json={
            'source_format': 'single-file',
            'name': 'Deferred Migration', 'brief': 'A personal workspace ready for a later shared API.',
            'backend_mode': 'static', 'auto_mode': False,
        })
        project = response.json()
        project_id = project['id']
        for _ in range(3):
            response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
            project = response.json()
        assert project['current_version'] == 1

        response = client.post(f'/api/projects/{project_id}/architecture', headers=auth(token), json={
            'target_mode': 'fastapi', 'feedback': '', 'defer': True,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        assert project['status'] == 'working'
        assert project['current_version'] == 1 and project['backend_mode'] == 'static'
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            project = client.get(f'/api/projects/{project_id}', headers=auth(token)).json()
            if project['status'] != 'working':
                break
            time.sleep(0.05)
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['backend_mode'] == 'fastapi'
        assert project['current_version'] == 2 and project['phase_index'] == 1
        assert project['stage'] == 'build'
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200
