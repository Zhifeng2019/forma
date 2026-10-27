from contextlib import contextmanager
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import deployment_registry
from app.backend_engine import runtime_requirements
from app.config import settings
from app.deployment_registry import deployment_artifacts, get_deployment
from app.engine import assemble_source_package
from app.llm import GenerationError
from app.main import app
from app.runtime import inject_runtime_bootstrap
from app.security import create_token
from app.source_packages import validate_source_package
from app.spec.schema import AppSpecError, parse_appspec
from fixtures.loader import FixturePack

TEST_DATA = Path(os.environ['DATA_DIR'])


@contextmanager
def activated(workspace):
    previous = settings.data_dir
    settings.data_dir = str(workspace.data_dir)
    try:
        yield
    finally:
        settings.data_dir = previous


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def provider_document(pack, key):
    return json.loads(pack.read_resource(pack.manifest.providers[key]))


def test_single_file_history_preview_and_public_release():
    workspace = FixturePack().workspace(TEST_DATA / 'compatibility-history')
    result = workspace.materialize_project('static-history')
    token = create_token(result.user_id)
    with activated(workspace), TestClient(app) as client:
        public = client.get(f'/apps/{result.project_id}/')
        current = client.get(f'/api/projects/{result.project_id}/preview?access_token={token}')
        historical = client.get(f'/api/projects/{result.project_id}/preview?access_token={token}&version=1')
        assert public.status_code == 200 and 'Fixture version 1' in public.text
        assert current.status_code == 200 and 'Fixture version 2' in current.text
        assert historical.status_code == 200 and 'Fixture version 1' in historical.text
        project = client.get(f'/api/projects/{result.project_id}', headers=auth(token)).json()
        assert project['current_version'] == 2 and project['published_version'] == 1


def test_registry_lookup_reads_only_registered_fixture_workspace(monkeypatch):
    pack = FixturePack()
    first = pack.workspace(TEST_DATA / 'registry-owner').materialize_project(
        'static-single-current-published', user_id=910011,
    )
    second = pack.workspace(TEST_DATA / 'registry-other').materialize_project(
        'static-single-current-published', user_id=910012,
    )
    assert first.project_id == second.project_id
    calls = []
    original = deployment_registry.workspace_db

    def tracked_workspace(user_id):
        calls.append(user_id)
        if user_id != first.user_id:
            raise AssertionError('Registry lookup read an unregistered workspace')
        return original(user_id)

    monkeypatch.setattr(deployment_registry, 'workspace_db', tracked_workspace)
    with activated(pack.workspace(TEST_DATA / 'registry-owner')):
        deployment = get_deployment(first.project_id)
        artifacts = deployment_artifacts(deployment)
    assert deployment['user_id'] == first.user_id
    assert 'Static fixture' in artifacts['html']
    assert calls == [first.user_id]


def test_multi_file_packages_build_and_fastapi_runs_from_fixture():
    workspace = FixturePack().workspace(TEST_DATA / 'compatibility-multi')
    static = workspace.materialize_project('static-multi-current-published')
    fastapi = workspace.materialize_project('fastapi-multi-current-published')
    with activated(workspace), TestClient(app) as client:
        static_page = client.get(f'/apps/{static.project_id}/')
        fastapi_page = client.get(f'/apps/{fastapi.project_id}/')
        assert static_page.status_code == 200, static_page.text
        assert fastapi_page.status_code == 200, fastapi_page.text
        assert 'id="root"' in static_page.text and 'id="root"' in fastapi_page.text
        assert f'/apps/{fastapi.project_id}/api' in fastapi_page.text
        health = client.get(f'/apps/{fastapi.project_id}/api/health')
        assert health.status_code == 200, health.text
        created = client.post(f'/apps/{fastapi.project_id}/api/items', json={'title': 'Fixture CRUD'})
        assert created.status_code == 201, created.text
        items = client.get(f'/apps/{fastapi.project_id}/api/items')
        assert items.status_code == 200
        assert [item['title'] for item in items.json()['items']] == ['Fixture CRUD']


def test_single_file_fastapi_runs_health_and_crud_from_fixture():
    workspace = FixturePack().workspace(TEST_DATA / 'compatibility-single-fastapi')
    result = workspace.materialize_project('fastapi-single-current-published')
    with activated(workspace), TestClient(app) as client:
        page = client.get(f'/apps/{result.project_id}/')
        assert page.status_code == 200 and 'FastAPI fixture' in page.text
        health = client.get(f'/apps/{result.project_id}/api/health')
        assert health.status_code == 200, health.text
        created = client.post(f'/apps/{result.project_id}/api/items', json={'title': 'Single-file CRUD'})
        assert created.status_code == 201, created.text
        items = client.get(f'/apps/{result.project_id}/api/items')
        assert [item['title'] for item in items.json()['items']] == ['Single-file CRUD']


def test_fixture_migration_preserves_release_phase_and_history():
    workspace = FixturePack().workspace(TEST_DATA / 'compatibility-migration')
    result = workspace.materialize_project('static-history')
    token = create_token(result.user_id)
    with activated(workspace), TestClient(app) as client:
        before = client.get(f'/api/projects/{result.project_id}', headers=auth(token)).json()
        migrated = client.post(f'/api/projects/{result.project_id}/architecture', headers=auth(token), json={
            'target_mode': 'fastapi', 'defer': False,
        })
        assert migrated.status_code == 200, migrated.text
        current = migrated.json()
        assert current['current_version'] == 3 and current['backend_mode'] == 'fastapi'
        assert current['published_version'] == 1
        assert (current['stage'], current['phase_index']) == (before['stage'], before['phase_index'])
        assert client.get(f'/apps/{result.project_id}/api/health').status_code == 404
        assert 'Fixture version 1' in client.get(f'/apps/{result.project_id}/').text

        returned = client.post(f'/api/projects/{result.project_id}/architecture', headers=auth(token), json={
            'target_mode': 'static', 'defer': False,
        })
        assert returned.status_code == 200, returned.text
        current = returned.json()
        assert current['current_version'] == 4 and current['backend_mode'] == 'static'
        assert current['published_version'] == 1
        history = {version['version']: version['backend_mode'] for version in current['versions']}
        assert history == {1: 'static', 2: 'static', 3: 'fastapi', 4: 'static'}
        assert 'Fixture version 1' in client.get(f'/apps/{result.project_id}/').text


def test_provider_fixtures_exercise_expected_contract_boundaries():
    pack = FixturePack()
    with pytest.raises(GenerationError):
        validate_source_package(provider_document(pack, 'invalid-package-structure')['files'], 'multi-file')
    with pytest.raises(AppSpecError):
        parse_appspec(provider_document(pack, 'invalid-appspec-contract'))

    requirements = provider_document(pack, 'missing-requirements')['files']['requirements.txt']
    enriched = runtime_requirements(requirements)
    assert enriched.count('email-validator==') == 1
    assert runtime_requirements(enriched) == enriched

    files = pack.package_files('fastapi-multi')
    files['backend/app/__init__.py'] = provider_document(pack, 'empty-python-init')['files']['backend/app/__init__.py']
    assert validate_source_package(files, 'fastapi')['backend/app/__init__.py'] == '\n'

    native = provider_document(pack, 'native-fetch-adapter')['files']['index.html']
    project_id = 'f' * 32
    injected = inject_runtime_bootstrap(native, project_id, 1, published=False)
    assert 'nativeFetch' in injected and f'/api/projects/{project_id}/runtime/1' in injected
    assert "fetch('/api/health')" in injected

    previous = pack.package_files('static-multi')
    partial = provider_document(pack, 'partial-package-overlay')['files']
    merged = assemble_source_package(previous, partial)
    validated = validate_source_package(merged, 'static')
    assert 'frontend/src/App.jsx' in validated
    assert 'Updated workspace' in validated['frontend/src/components/Workspace.jsx']
    assert 'index.html' in provider_document(pack, 'legacy-package')['files']
