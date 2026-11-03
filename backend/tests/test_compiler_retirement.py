"""The supported generator must stay selected even with stale deployment settings."""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app import engine
from app.api import project_payload
from app.backend_engine import local_backend_html, local_backend_source
from app.config import Settings, settings
from app.database import workspace_db, workspace_for
from app.features import FeatureFlag
from app.frontend_builder import _digest
from app.main import app
from app.source_packages import local_source_package
from fixtures.archived_appspec import archived_package, spec_artifacts
from test_verification_gate import auth, build_version, register


@pytest.mark.parametrize('value', ['true', 'not-a-boolean'])
def test_retired_flags_are_ignored_from_environment_and_dotenv(monkeypatch, tmp_path, value):
    env = tmp_path / '.env'
    env.write_text(f'APPSPEC_V1={value}\nSPECIALIST_WORKERS_V1={value}\n')
    monkeypatch.setenv('APPSPEC_V1', value)
    monkeypatch.setenv('SPECIALIST_WORKERS_V1', value)
    config = Settings(_env_file=env, durable_jobs_v1=True, sandbox_v1=True)
    assert 'appspec_v1' not in config.model_dump()
    assert 'specialist_workers_v1' not in config.model_dump()
    assert config.durable_jobs_v1 and config.sandbox_v1
    assert {flag.value for flag in FeatureFlag} == {'durable_jobs_v1', 'acceptance_gate_v1', 'sandbox_v1'}


@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
@pytest.mark.parametrize('backend_mode', ['static', 'fastapi'])
def test_build_refinement_and_migration_use_source_even_with_retired_flags(monkeypatch, source_format, backend_mode):
    monkeypatch.setenv('APPSPEC_V1', 'true')
    monkeypatch.setenv('SPECIALIST_WORKERS_V1', 'true')
    user_id = 970101
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    package = archived_package(source_format, backend_mode)
    old_files = {**package.files, **spec_artifacts(package)}
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,stage,stage_index,phase_index,current_version,
            published_version,backend_mode,source_format) VALUES(?,?,?,'build',3,1,1,1,?,?)''',
            (project_id, 'Source Regression', 'Preserve a custom workflow.', backend_mode, source_format))
        db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,1,?,?,?)',
                   (project_id, 'Original release', backend_mode, source_format))
        for path, content in old_files.items():
            engine.save_artifact(db, project_id, 'build', path, content, 1)

    prompts = []
    target = backend_mode

    async def complete(_provider, system, prompt):
        prompts.append(prompt)
        assert 'Return product semantics only' not in system
        if source_format == 'multi-file':
            # A real model source response, including custom source outside the old contract.
            files = local_source_package('Source Regression', 'Preserve a custom workflow.', 2, target)
            files['frontend/src/components/Custom.jsx'] = 'export default function Custom(){ return <p>Custom feature</p> }'
            return {'files': files}
        if target == 'fastapi':
            return {'html': local_backend_html('Source Regression', 'Custom feature', 2),
                    'python': local_backend_source('Source Regression')}
        return {'html': '<!doctype html><html><body>Custom feature</body></html>'}

    async def built(*_args, **_kwargs):
        return '<html></html>'

    monkeypatch.setattr(engine, 'complete', complete)
    monkeypatch.setattr(engine, 'ensure_frontend_build', built)
    provider = {'name': 'Test provider', 'model': 'test-model'}
    # Advance an old compiler-built version, refine it, then migrate architecture.
    asyncio.run(engine._advance(user_id, project_id, provider))
    asyncio.run(engine._advance(user_id, project_id, provider, 'Preserve the custom feature', revise=True))
    target = 'fastapi' if backend_mode == 'static' else 'static'
    asyncio.run(engine._migrate_architecture(user_id, project_id, target, provider, 'Preserve the custom feature'))
    assert len(prompts) == 3
    assert ('Current package files:' if source_format == 'multi-file' else 'Current HTML') in prompts[0]
    with workspace_db(user_id) as db:
        original = {r['path']: r['content'] for r in db.execute(
            'SELECT path,content FROM artifacts WHERE project_id=? AND version=1', (project_id,))}
        assert original == old_files
        for version in [2, 3, 4]:
            files = engine.generation_source_files(db, project_id, version)
            assert 'Custom feature' in '\n'.join(files.values())
            assert not db.execute('''SELECT 1 FROM artifacts WHERE project_id=? AND version=?
                AND (path IN ('appspec.json','build-manifest.json') OR path LIKE 'acceptance/%')''',
                (project_id, version)).fetchone()
        project = engine.get_project(db, project_id)
        assert project['current_version'] == 4 and project['published_version'] == 1
        assert project['backend_mode'] == target and project['phase_index'] == 2
    payload = project_payload(user_id, project_id)
    assert payload['appspec'] is None and payload['capability'] is None
    assert payload['verification_available'] is False
    assert 'appspec_enabled' not in payload and 'specialist_workers_enabled' not in payload


def test_invalid_historical_draft_no_longer_blocks_building():
    with TestClient(app) as client:
        account = register(client, 'retired-draft')
        headers = auth(account['token'])
        response = client.post('/api/projects', headers=headers, json={
            'name': 'Retired Draft', 'brief': 'A focus timer.',
            'backend_mode': 'static', 'source_format': 'single-file',
        })
        project_id = response.json()['id']
        for _ in range(2):
            response = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={})
            assert response.status_code == 200
        assert response.json()['current_version'] == 0
        with workspace_db(account['user']['id']) as db:
            engine.save_artifact(db, project_id, 'plan', 'appspec.json', '{"invalid":true}', 0)
        response = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={})
        assert response.status_code == 200, response.text
        assert response.json()['current_version'] == 1
        assert response.json()['status'] == 'ready'
        assert response.json()['appspec'] is None


def test_new_source_versions_can_publish_with_historical_gate_enabled(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', True)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError('New source versions must not require the removed compiler')

    monkeypatch.setattr('app.api.verify_package', unexpected)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'new-source-publish', appspec=False)
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(account['token']), json={})
        assert response.status_code == 200, response.text
        assert response.json()['published_version'] == 1
        verification = client.post(f'/api/projects/{project_id}/verify', headers=auth(account['token']), json={})
        assert verification.status_code == 409
        assert 'historical AppSpec versions' in verification.json()['detail']


def test_historical_metadata_is_excluded_from_source_builds():
    package = archived_package()
    assert _digest(package.files) == _digest({**package.files, **spec_artifacts(package)})
