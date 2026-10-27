import io
import json
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.backend_engine import GenerationError, has_forma_api, reviewed_requirements
from app.main import app
from app.engine import complete_package
from app.source_packages import local_source_package, validate_source_package
from fixtures.loader import FixturePack

PACK = FixturePack()


def test_relative_component_imports_resolve_with_or_without_extensions():
    files = local_source_package('Import Check', 'Validate component imports', 1, 'fastapi')
    files['frontend/src/components/Auth.jsx'] = 'export default function Auth() { return null }\n'
    files['frontend/src/components/Workspace.jsx'] = "import Auth from './Auth'\n" + files['frontend/src/components/Workspace.jsx']
    validated = validate_source_package(files, 'fastapi')
    assert 'frontend/src/components/Auth.jsx' in validated


def test_missing_component_import_is_rejected_before_vite():
    files = local_source_package('Import Check', 'Reject missing components', 1, 'fastapi')
    files['frontend/src/components/Workspace.jsx'] = "import Auth from './Auth.jsx'\n" + files['frontend/src/components/Workspace.jsx']
    with pytest.raises(GenerationError, match='imports missing source file: ./Auth.jsx'):
        validate_source_package(files, 'fastapi')


def test_relative_import_cannot_leave_frontend_source():
    files = local_source_package('Import Check', 'Reject source traversal', 1, 'fastapi')
    files['frontend/src/components/Workspace.jsx'] = "import Bad from '../../backend/app/api.py'\n" + files['frontend/src/components/Workspace.jsx']
    with pytest.raises(GenerationError, match='outside the frontend source folder'):
        validate_source_package(files, 'fastapi')


@pytest.mark.asyncio
async def test_missing_component_gets_one_semantic_repair(monkeypatch):
    calls = []

    async def fake_complete(_provider, _system, prompt):
        calls.append(prompt)
        files = local_source_package('Repair Check', 'A shared repair workspace', 1, 'fastapi')
        if len(calls) == 1:
            files['frontend/src/components/Workspace.jsx'] = (
                "import Auth from './Auth.jsx'\n" + files['frontend/src/components/Workspace.jsx']
            )
        return {'files': files}

    monkeypatch.setattr('app.engine.complete', fake_complete)
    files = await complete_package({}, 'Repair Check', 'A shared repair workspace', 1, '', 'fastapi', {})
    assert len(calls) == 2
    assert 'imports missing source file' in calls[1]
    assert 'frontend/src/App.jsx' in files


@pytest.mark.asyncio
async def test_partial_update_preserves_previous_components(monkeypatch):
    previous = local_source_package('Overlay Check', 'Preserve complete source', 1, 'fastapi')
    previous['frontend/src/components/Auth.jsx'] = 'export default function Auth() { return null }\n'
    previous['frontend/src/components/Market.jsx'] = 'export default function Market() { return null }\n'
    previous['frontend/src/components/Workspace.jsx'] = (
        "import Auth from './Auth.jsx'\nimport Market from './Market.jsx'\n"
        + previous['frontend/src/components/Workspace.jsx']
    )
    calls = []

    async def fake_complete(_provider, _system, prompt):
        calls.append(prompt)
        partial = json.loads(PACK.read_resource(PACK.manifest.providers['partial-package-overlay']))['files']
        partial['frontend/src/components/Workspace.jsx'] += '// Phase 2\n'
        return {'files': partial}

    monkeypatch.setattr('app.engine.complete', fake_complete)
    files = await complete_package({}, 'Overlay Check', 'Preserve complete source', 2, '', 'fastapi', previous)
    assert len(calls) == 1
    assert 'frontend/src/components/Auth.jsx' in files
    assert 'frontend/src/components/Market.jsx' in files
    assert files['frontend/src/components/Workspace.jsx'].endswith('// Phase 2\n')


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_reviewed_dependency_expansion_and_package_validation():
    assert has_forma_api("window.Forma?.api?.('/items')")
    assert has_forma_api("window.Forma['api']('/items')")
    assert has_forma_api("fetch('/api/items')")
    assert not has_forma_api("axios.get('/api/items')")
    requirements = reviewed_requirements(['httpx', 'SQLAlchemy', 'python-multipart'])
    assert 'httpx==' in requirements and 'SQLAlchemy==' in requirements and 'python-multipart==' in requirements
    with pytest.raises(GenerationError, match='Unsupported Python dependency'):
        reviewed_requirements(['requests'])
    files = local_source_package('Dependency Check', 'A shared dependency-aware workspace', 1, 'fastapi')
    files['backend/app/models.py'] = 'import httpx\n' + files['backend/app/models.py']
    from app.source_packages import validate_source_package
    validated = validate_source_package(files, 'fastapi', ['httpx'])
    assert 'httpx==' in validated['backend/requirements.txt']
    del validated['backend/requirements.txt']
    validated = validate_source_package(validated, 'fastapi', ['httpx'])
    assert 'fastapi==' in validated['backend/requirements.txt']
    validated['backend/app/__init__.py'] = ''
    assert validate_source_package(validated, 'fastapi', ['httpx'])['backend/app/__init__.py'] == '\n'
    with pytest.raises(GenerationError, match='Unsupported JavaScript dependency'):
        invalid = dict(files)
        invalid['frontend/src/App.jsx'] = "import axios from 'axios'\n" + invalid['frontend/src/App.jsx']
        validate_source_package(invalid, 'fastapi')


@pytest.mark.asyncio
async def test_invalid_model_package_gets_one_semantic_repair(monkeypatch):
    calls = []

    async def fake_complete(_provider, _system, prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return json.loads(PACK.read_resource(PACK.manifest.providers['invalid-package-structure']))
        return {'files': local_source_package('Repair Check', 'A shared repair workspace', 1, 'fastapi')}

    monkeypatch.setattr('app.engine.complete', fake_complete)
    files = await complete_package({}, 'Repair Check', 'A shared repair workspace', 1, '', 'fastapi', {})
    assert len(calls) == 2
    assert 'frontend/src/App.jsx' in files and 'backend/app/api.py' in files


def test_multi_file_package_preview_publish_and_download():
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': 'package@example.com', 'name': 'Package Maker', 'password': 'password123',
        })
        token = response.json()['token']
        response = client.post('/api/projects', headers=auth(token), json={
            'name': 'Package Workspace', 'brief': 'A shared team workspace with priorities and live progress.',
            'backend_mode': 'fastapi', 'source_format': 'multi-file', 'auto_mode': False,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        project_id = project['id']
        assert project['source_format'] == 'multi-file'
        for _ in range(3):
            response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
            assert response.status_code == 200, response.text
            project = response.json()
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['current_version'] == 1
        paths = {artifact['path'] for artifact in project['artifacts']}
        assert 'frontend/src/App.jsx' in paths and 'backend/app/api.py' in paths
        assert project['versions'][0]['source_format'] == 'multi-file'

        preview = client.get(f'/api/projects/{project_id}/preview?access_token={token}')
        assert preview.status_code == 200, preview.text
        assert './assets/' in preview.text and 'window.Forma=Object.freeze' in preview.text
        assert 'forma-picker' in preview.text
        asset_match = re.search(r'(?:src|href)="(\./)?assets/([^"?]+)"', preview.text)
        assert asset_match
        asset_name = asset_match.group(2)
        asset = client.get(f'/api/projects/{project_id}/assets/{asset_name}')
        assert asset.status_code == 200, asset.text
        assert len(asset.content) > 100
        health = client.get(f'/api/projects/{project_id}/runtime/1/health', headers=auth(token))
        assert health.status_code == 200, health.text

        archive = client.get(f'/api/projects/{project_id}/package?access_token={token}')
        assert archive.status_code == 200, archive.text
        with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
            names = set(package.namelist())
        assert 'frontend/index.html' in names
        assert 'frontend/dist/index.html' in names
        assert 'backend/main.py' in names and 'backend/app/api.py' in names
        assert not any('node_modules' in name for name in names)
        assert not any('npm-cache' in name or '/tmp/' in name for name in names)

        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        public = client.get(f'/apps/{project_id}/')
        assert public.status_code == 200 and './assets/' in public.text
        assert 'privatePreview=false' in public.text
        public_asset = client.get(f'/apps/{project_id}/assets/{asset_name}')
        assert public_asset.status_code == 200
        assert client.get(f'/apps/{project_id}/api/health').status_code == 200
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200
