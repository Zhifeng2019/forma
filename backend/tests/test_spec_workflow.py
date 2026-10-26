import asyncio
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import engine
from app.config import settings
from app.database import workspace_db, workspace_for
from app.frontend_builder import _digest
from app.llm import GenerationError
from app.main import app
from app.source_packages import local_source_package
from app.spec.schema import SPEC_ARTIFACT_PATHS


def make_project(user_id: int, source_format: str, backend_mode: str) -> str:
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,stage,backend_mode,source_format)
            VALUES(?,?,?,?,?,?)''', (
            project_id, 'AppSpec Workflow', 'A focused workspace with provenance.',
            'build', backend_mode, source_format,
        ))
    return project_id


def artifacts(user_id: int, project_id: str, version: int) -> dict[str, str]:
    with workspace_db(user_id) as db:
        return {row['path']: row['content'] for row in db.execute(
            'SELECT path,content FROM artifacts WHERE project_id=? AND version=?', (project_id, version),
        )}


async def no_frontend_build(*_args):
    return ''


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
@pytest.mark.parametrize('backend_mode', ['static', 'fastapi'])
def test_generation_dual_writes_only_when_enabled(monkeypatch, enabled, source_format, backend_mode):
    user_id = 920100
    project_id = make_project(user_id, source_format, backend_mode)
    monkeypatch.setattr(settings, 'appspec_v1', enabled)
    monkeypatch.setattr(engine, 'ensure_frontend_build', no_frontend_build)
    asyncio.run(engine._advance(user_id, project_id, None))
    files = artifacts(user_id, project_id, 1)
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['status'] == 'ready' and project['current_version'] == 1
        assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=?', (project_id,)).fetchone()[0] == 1
    if not enabled:
        assert not set(files) & set(SPEC_ARTIFACT_PATHS)
        return
    document = json.loads(files['appspec.json'])
    manifest = json.loads(files['build-manifest.json'])
    assert document['spec']['architecture'] == {
        'backend_mode': backend_mode,
        'source_format': source_format,
        'state_ownership': 'server' if backend_mode == 'fastapi' else 'browser',
    }
    assert document['spec_hash'] == manifest['spec_hash']
    assert len(manifest['source_hash']) == 64
    assert {item['path'] for item in manifest['files']} == set(files) - set(SPEC_ARTIFACT_PATHS)
    with workspace_db(user_id) as db:
        source = engine.generation_source_files(db, project_id, 1)
    assert not set(source) & set(SPEC_ARTIFACT_PATHS)


@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
@pytest.mark.parametrize('target', ['static', 'fastapi'])
def test_migration_dual_writes_version_specific_contract(monkeypatch, source_format, target):
    user_id = 920200
    initial = 'fastapi' if target == 'static' else 'static'
    project_id = make_project(user_id, source_format, initial)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    monkeypatch.setattr(engine, 'ensure_frontend_build', no_frontend_build)
    asyncio.run(engine._advance(user_id, project_id, None))
    asyncio.run(engine._migrate_architecture(user_id, project_id, target, None, 'Migrate with provenance'))
    first = json.loads(artifacts(user_id, project_id, 1)['appspec.json'])
    second_files = artifacts(user_id, project_id, 2)
    second = json.loads(second_files['appspec.json'])
    assert first['spec']['architecture']['backend_mode'] == initial
    assert second['spec']['architecture']['backend_mode'] == target
    assert second['spec']['architecture']['source_format'] == source_format
    assert ('backend/main.py' in second_files) == (target == 'fastapi')
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['current_version'] == 2 and project['phase_index'] == 1
        assert project['backend_mode'] == target and project['status'] == 'ready'
        assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=?', (project_id,)).fetchone()[0] == 2


def test_refinement_uses_previous_appspec_not_a_file_map(monkeypatch):
    user_id = 920300
    project_id = make_project(user_id, 'multi-file', 'fastapi')
    monkeypatch.setattr(settings, 'appspec_v1', True)
    monkeypatch.setattr(engine, 'ensure_frontend_build', no_frontend_build)
    asyncio.run(engine._advance(user_id, project_id, None))
    received = []

    async def generated(_project, _provider, phase, _feedback, current_spec, brief):
        received.append(current_spec)
        from app.spec.compiler import compile_package
        return compile_package(current_spec['spec'], phase=phase)

    async def unexpected_file_generation(*_args):
        raise AssertionError('Legacy file-map generation must not run with AppSpec enabled')

    monkeypatch.setattr(engine, 'generate_appspec_package', generated)
    monkeypatch.setattr(engine, 'complete_package', unexpected_file_generation)
    provider = {'name': 'Test provider', 'model': 'test-model'}
    asyncio.run(engine._advance(user_id, project_id, provider, 'Refine the current phase', revise=True))
    assert len(received) == 1
    assert received[0]['spec']['product']['name'] == 'AppSpec Workflow'
    assert len(received[0]['spec_hash']) == 64
    assert 'files' not in received[0]
    assert 'appspec.json' in artifacts(user_id, project_id, 2)


def test_invalid_spec_never_reaches_frontend_build(monkeypatch):
    user_id = 920400
    project_id = make_project(user_id, 'multi-file', 'fastapi')
    monkeypatch.setattr(settings, 'appspec_v1', True)
    build_calls = []

    async def invalid_proposal(*_args, **_kwargs):
        from app.spec.defaults import local_default_appspec
        document = local_default_appspec('Invalid App', 'Invalid contract.', 'multi-file', 'fastapi').model_dump(
            mode='json', exclude_none=True,
        )
        second = dict(document['entities'][0])
        second['name'] = 'Second'
        document['entities'].append(second)
        return document

    async def unexpected_build(*_args):
        build_calls.append(True)

    monkeypatch.setattr('app.spec.service.propose_appspec', invalid_proposal)
    monkeypatch.setattr(engine, 'ensure_frontend_build', unexpected_build)
    with pytest.raises(GenerationError):
        asyncio.run(engine._advance(user_id, project_id, None))
    assert build_calls == []
    with workspace_db(user_id) as db:
        project = db.execute('SELECT current_version FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['current_version'] == 0
        assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=?', (project_id,)).fetchone()[0] == 0


def test_build_digest_ignores_provenance_metadata():
    files = local_source_package('Digest Check', 'Stable build hashing', 1, 'static')
    with_provenance = {
        **files,
        'appspec.json': '{"spec": true}',
        'build-manifest.json': '{"files": []}',
    }
    assert _digest(files) == _digest(with_provenance)


def test_provider_build_requests_appspec_instead_of_source(monkeypatch):
    user_id = 920500
    project_id = make_project(user_id, 'multi-file', 'fastapi')
    monkeypatch.setattr(settings, 'appspec_v1', True)
    monkeypatch.setattr(engine, 'ensure_frontend_build', no_frontend_build)
    calls = []

    async def structured_proposal(_provider, _system, prompt, schema, schema_name):
        from app.spec.defaults import local_default_appspec
        calls.append((prompt, schema, schema_name))
        return local_default_appspec(
            'AppSpec Workflow', 'A focused workspace with provenance.', 'multi-file', 'fastapi',
        ).model_dump(mode='json', exclude_none=True)

    async def unexpected_legacy_call(*_args):
        raise AssertionError('Legacy source generation must not be called')

    monkeypatch.setattr('app.spec.generator.complete_with_schema', structured_proposal)
    monkeypatch.setattr(engine, 'complete', unexpected_legacy_call)
    monkeypatch.setattr(engine, 'complete_package', unexpected_legacy_call)
    asyncio.run(engine._advance(user_id, project_id, {'name': 'Test provider', 'model': 'test-model'}))
    assert len(calls) == 1
    prompt, schema, schema_name = calls[0]
    assert schema_name == 'forma_appspec'
    assert schema['required'] == ['product', 'entities', 'api', 'frontend', 'acceptance']
    assert 'Current HTML' not in prompt and 'Current package files' not in prompt
    files = artifacts(user_id, project_id, 1)
    manifest = json.loads(files['build-manifest.json'])
    assert manifest['generation'] == {'mode': 'appspec', 'phase': 1}
    assert 'class ItemInput' in files['backend/app/models.py']


def test_deferred_durable_autopilot_writes_spec_for_every_version(monkeypatch):
    monkeypatch.setattr(settings, 'appspec_v1', True)
    monkeypatch.setattr(settings, 'durable_jobs_v1', True)
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': f'appspec-{uuid.uuid4().hex}@example.com',
            'name': 'AppSpec Tester', 'password': 'password123',
        })
        account = response.json()
        token = account['token']
        headers = {'Authorization': f'Bearer {token}'}
        response = client.post('/api/projects', headers=headers, json={
            'name': 'Deferred AppSpec', 'brief': 'A personal focus timer with weekly progress.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': True, 'defer': True,
        })
        assert response.status_code == 200, response.text
        project_id = response.json()['id']
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            project = client.get(f'/api/projects/{project_id}', headers=headers).json()
            if project['stage'] == 'review' or project['status'] == 'error':
                break
            time.sleep(0.03)
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['current_version'] == 3
        assert sorted(item['version'] for item in project['versions']) == [1, 2, 3]
        with workspace_db(account['user']['id']) as db:
            for path in SPEC_ARTIFACT_PATHS:
                assert db.execute('SELECT COUNT(*) FROM artifacts WHERE project_id=? AND path=?',
                                  (project_id, path)).fetchone()[0] == 3
            jobs = db.execute('SELECT status FROM generation_jobs WHERE project_id=?', (project_id,)).fetchall()
            assert len(jobs) == 6 and all(job['status'] == 'succeeded' for job in jobs)
        assert client.delete(f'/api/projects/{project_id}', headers=headers).status_code == 200
