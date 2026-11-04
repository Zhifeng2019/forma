from fixtures.accounts import register_account
import asyncio
import json
import logging
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, engine
from app.app_origins import application_origin, published_url
from app.config import Settings, configuration_report, settings
from app.database import workspace_db
from app.main import app
from app.studio_static import StudioStaticFiles
from test_planning_handoff import make_project, saved_context, source_response


def test_studio_path_prefix_keeps_origins_separate():
    configured = Settings(studio_base_url='https://www.riskcat.cn', studio_path_prefix='/forma/')
    assert configured.studio_path_prefix == '/forma'
    assert configured.studio_base_url == 'https://www.riskcat.cn'
    assert configuration_report(configured)['studio_path_prefix'] == '/forma'
    for invalid in ('forma', 'https://www.riskcat.cn/forma', '/forma?x=1', '/forma/..', '//forma'):
        with pytest.raises(ValueError, match='STUDIO_PATH_PREFIX'):
            Settings(studio_path_prefix=invalid)


def test_one_absolute_environment_file_and_visible_process_precedence(tmp_path, monkeypatch):
    backend = tmp_path / 'backend'
    backend.mkdir()
    canonical = backend / '.env'
    canonical.write_text('RUNTIME_MEMORY_MB=321\nSANDBOX_V1=true\nSECRET_KEY=file-secret-not-for-logs\n')
    (tmp_path / '.env').write_text('RUNTIME_MEMORY_MB=999\nSANDBOX_V1=false\n')
    monkeypatch.setitem(Settings.model_config, 'env_file', canonical)
    monkeypatch.delenv('RUNTIME_MEMORY_MB', raising=False)
    monkeypatch.delenv('SANDBOX_V1', raising=False)
    for cwd in (tmp_path, backend):
        monkeypatch.chdir(cwd)
        loaded = Settings()
        assert loaded.runtime_memory_mb == 321
        assert loaded.sandbox_v1 is True
    monkeypatch.setenv('RUNTIME_MEMORY_MB', '654')
    monkeypatch.setenv('SECRET_KEY', 'process-secret-not-for-logs')
    loaded = Settings()
    assert loaded.runtime_memory_mb == 654
    report = configuration_report(loaded, canonical)
    assert report['environment_file'] == str(canonical)
    assert report['ignored_environment_files'] == [str(tmp_path / '.env')]
    assert {'RUNTIME_MEMORY_MB', 'SECRET_KEY'} <= set(report['process_overrides'])
    assert report['features']['SANDBOX_V1'] is True
    assert 'llm-source' in report['generation_path']
    assert 'not-for-logs' not in json.dumps(report)


def test_startup_reports_flags_without_secret_values(monkeypatch, caplog):
    monkeypatch.setattr(settings, 'secret_key', 'startup-secret-not-for-logs')
    with caplog.at_level(logging.INFO, logger='uvicorn.error'), TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
    assert 'Forma configuration:' in caplog.text
    assert 'SANDBOX_V1' in caplog.text and str(config.ENV_FILE) in caplog.text
    assert 'startup-secret-not-for-logs' not in caplog.text


def test_production_spa_routes_preserve_assets_api_errors_and_methods(tmp_path):
    (tmp_path / 'index.html').write_text('<html>Studio shell</html>')
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'app.js').write_text('console.log("real asset")')
    (tmp_path / 'api').mkdir()
    (tmp_path / 'api' / 'missing').write_text('must never shadow an API error')
    production = FastAPI()

    @production.get('/api/health')
    def health():
        return {'status': 'ok'}

    production.mount('/', StudioStaticFiles(directory=tmp_path))
    with TestClient(production) as client:
        for path in ('/', '/login', '/login/', '/register', '/forgot-password', '/settings', '/admin', '/projects/project-1'):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.text == '<html>Studio shell</html>'
            assert response.headers['cache-control'] == 'no-cache'
            assert response.headers['content-type'].startswith('text/html')
            head = client.head(path)
            assert head.status_code == 200 and not head.content
        assert client.get('/api/health').json() == {'status': 'ok'}
        assert client.get('/assets/app.js').status_code == 200
        for path in ('/api/missing', '/apps/missing', '/preview/missing', '/assets/missing.js', '/missing.js', '/unknown'):
            response = client.get(path)
            assert response.status_code == 404, path
            assert 'Studio shell' not in response.text
        assert client.post('/login').status_code == 405


def test_studio_route_fallback_does_not_run_on_application_hosts():
    with TestClient(app) as client:
        for origin in (application_origin('a' * 32), application_origin('a' * 32, 1)):
            for path in ('/', '/login', '/settings', '/projects/' + 'a' * 32):
                assert client.get(origin + path).status_code == 404


@pytest.mark.parametrize('published', [False, True])
@pytest.mark.parametrize('phase', [1, 3])
@pytest.mark.parametrize('durable', [False, True])
@pytest.mark.parametrize('defer', [False, True])
def test_post_release_edits_create_a_draft_without_republishing(monkeypatch, published, phase, durable, defer):
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    with TestClient(app) as client:
        account = register_account(client, json={
            'email': f'release-{uuid.uuid4().hex}@example.com', 'name': 'Owner', 'password': 'password123',
        }).json()
        headers = {'Authorization': f'Bearer {account["token"]}'}
        project = client.post('/api/projects', headers=headers, json={
            'name': 'Release revisions', 'brief': 'A personal focus timer with a weekly overview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
        }).json()
        pid = project['id']
        for _ in range(2 + phase):
            project = client.post(f'/api/projects/{pid}/advance', headers=headers, json={}).json()
        if phase == 3:
            project = client.post(f'/api/projects/{pid}/advance', headers=headers, json={}).json()
        else:
            with workspace_db(account['user']['id']) as db:
                db.execute("UPDATE projects SET stage='deploy',stage_index=5 WHERE id=?", (pid,))
        if published:
            # Publishing an older version must also survive edits to the current draft.
            project = client.post(f'/api/projects/{pid}/publish', headers=headers, json={'version': 1}).json()
            live_before = client.get(published_url(pid)).text
        before = client.get(f'/api/projects/{pid}', headers=headers).json()
        response = client.post(f'/api/projects/{pid}/messages', headers=headers, json={
            'content': 'Make the primary action blue.', 'defer': defer,
        })
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 10
        while response.json()['status'] == 'working' and time.monotonic() < deadline:
            time.sleep(0.02)
            response = client.get(f'/api/projects/{pid}', headers=headers)
        project = response.json()
        assert project['status'] == 'ready'
        assert project['current_version'] == before['current_version'] + 1
        assert project['phase_index'] == phase
        assert project['stage'] == ('build' if phase < 3 else 'review')
        assert project['stage_index'] == (3 if phase < 3 else 4)
        assert project['published_version'] == before['published_version']
        assert project['versions'][0]['label'] == 'Refinement'
        assert project['versions'][1:] == before['versions']
        if published:
            assert client.get(published_url(pid)).text == live_before
        else:
            assert client.get(published_url(pid)).status_code == 404
        # Approval accepts this new version as-is, without another regeneration.
        if phase == 3:
            approved = client.post(f'/api/projects/{pid}/advance', headers=headers, json={}).json()
            assert approved['stage'] == 'deploy' and approved['current_version'] == project['current_version']


@pytest.mark.parametrize('mode', ['static', 'fastapi'])
@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
def test_post_release_refinements_inherit_planning_context_for_every_format(monkeypatch, mode, source_format):
    user_id, pid = make_project(source_format, mode)

    async def no_build(*_args, **_kwargs):
        return ''

    async def complete(_provider, _system, prompt):
        assert 'AUDIT-742' in prompt and 'TIMELINE-829' in prompt and 'EXPORT-691' in prompt
        return source_response(source_format, mode)

    monkeypatch.setattr(engine, 'ensure_frontend_build', no_build)
    monkeypatch.setattr(engine, 'complete', complete)
    provider = {'name': 'Test', 'model': 'fixture-model'}
    asyncio.run(engine._advance(user_id, pid, provider))
    original = saved_context(user_id, pid, 1)
    with workspace_db(user_id) as db:
        db.execute("UPDATE projects SET stage='deploy',stage_index=5,published_version=1 WHERE id=?", (pid,))
        db.execute("UPDATE artifacts SET content='Unapproved replacement' WHERE project_id=? AND path='plan.md'", (pid,))
    asyncio.run(engine._advance(user_id, pid, provider, 'Make the action blue.', revise=True))
    refined = saved_context(user_id, pid, 2)
    assert refined['documents'] == original['documents']
    assert refined['operation'] == 'refine'
    with workspace_db(user_id) as db:
        project = db.execute('SELECT phase_index,published_version,stage FROM projects WHERE id=?', (pid,)).fetchone()
    assert tuple(project) == (1, 1, 'build')
