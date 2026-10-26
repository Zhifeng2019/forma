import io
import json
import uuid
import zipfile

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_multi_file_appspec_preview_and_deployment_package(monkeypatch):
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': f'appspec-package-{uuid.uuid4().hex}@example.com',
            'name': 'AppSpec Package Tester', 'password': 'password123',
        })
        assert response.status_code == 200, response.text
        token = response.json()['token']
        headers = {'Authorization': f'Bearer {token}'}
        response = client.post('/api/projects', headers=headers, json={
            'name': 'AppSpec Package',
            'brief': 'A portable browser workspace with deterministic provenance.',
            'backend_mode': 'static', 'source_format': 'multi-file', 'auto_mode': False,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        project_id = project['id']
        for _ in range(3):
            response = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={})
            assert response.status_code == 200, response.text
            project = response.json()
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['current_version'] == 1
        paths = {artifact['path'] for artifact in project['artifacts']}
        assert {'appspec.json', 'build-manifest.json', 'frontend/src/App.jsx'} <= paths

        preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}')
        assert preview.status_code == 200, preview.text
        assert './assets/' in preview.text
        archive = client.get(f'/api/projects/{project_id}/package?access_token={token}')
        assert archive.status_code == 200, archive.text
        with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
            names = set(package.namelist())
            spec = json.loads(package.read('appspec.json'))
            manifest = json.loads(package.read('build-manifest.json'))
        assert 'frontend/dist/index.html' in names
        assert not any('node_modules' in name for name in names)
        assert spec['spec']['architecture']['source_format'] == 'multi-file'
        assert spec['spec']['architecture']['backend_mode'] == 'static'
        assert spec['spec_hash'] == manifest['spec_hash']
        assert client.delete(f'/api/projects/{project_id}', headers=headers).status_code == 200


def test_multi_file_appspec_fastapi_runtime_crud_and_restart(monkeypatch):
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': f'appspec-runtime-{uuid.uuid4().hex}@example.com',
            'name': 'AppSpec Runtime Tester', 'password': 'password123',
        })
        assert response.status_code == 200, response.text
        token = response.json()['token']
        headers = {'Authorization': f'Bearer {token}'}
        response = client.post('/api/projects', headers=headers, json={
            'name': 'AppSpec Runtime',
            'brief': 'A shared item workspace with persistent server state.',
            'backend_mode': 'fastapi', 'source_format': 'multi-file', 'auto_mode': False,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        project_id = project['id']
        for _ in range(3):
            response = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={})
            assert response.status_code == 200, response.text
            project = response.json()
        assert project['status'] == 'ready', project['messages'][-1]['content']
        preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}')
        assert preview.status_code == 200 and './assets/' in preview.text

        private_api = f'/api/projects/{project_id}/runtime/1'
        assert client.get(f'{private_api}/health', headers=headers).status_code == 200
        response = client.post(f'{private_api}/items', headers=headers, json={
            'title': 'Verify generated runtime', 'completed': False,
        })
        assert response.status_code == 201, response.text
        item = response.json()
        response = client.patch(f'{private_api}/items/{item["id"]}', headers=headers, json={'completed': True})
        assert response.status_code == 200 and response.json()['completed'] is True
        response = client.post(f'/api/projects/{project_id}/runtime/restart', headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['healthy'] is True
        items = client.get(f'{private_api}/items', headers=headers).json()['items']
        restored = next(row for row in items if row['id'] == item['id'])
        assert restored['title'] == 'Verify generated runtime' and restored['completed'] is True
        assert client.delete(f'{private_api}/items/{item["id"]}', headers=headers).status_code == 204
        assert client.delete(f'/api/projects/{project_id}', headers=headers).status_code == 200
