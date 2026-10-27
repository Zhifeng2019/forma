import asyncio
import json
import uuid

from fastapi.testclient import TestClient

from app import engine
from app.config import settings
from app.database import workspace_db, workspace_for
from app.main import app
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.spec.review import appspec_review
from app.spec.schema import appspec_document


def make_project(user_id: int, stage: str = 'plan') -> str:
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,stage,backend_mode,source_format)
            VALUES(?,?,?,?,?,?)''', (
            project_id, 'Contract Review', 'A reviewable workspace with persistent items.',
            stage, 'static', 'single-file',
        ))
    return project_id


def draft(user_id: int, project_id: str, version: int = 0) -> dict:
    with workspace_db(user_id) as db:
        row = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                         (project_id, 'appspec.json', version)).fetchone()
    assert row is not None
    return json.loads(row['content'])


async def no_frontend_build(*_args):
    return ''


def test_planning_creates_draft_and_first_build_reuses_it(monkeypatch):
    user_id = 930100
    project_id = make_project(user_id)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    monkeypatch.setattr(engine, 'ensure_frontend_build', no_frontend_build)
    asyncio.run(engine._advance(user_id, project_id, None))
    initial = draft(user_id, project_id)
    assert initial['spec']['product']['name'] == 'Contract Review'
    assert initial['spec']['entities'][0]['name'] == 'Item'
    assert appspec_review(json.dumps(initial), for_compilation=True)['appspec_valid'] is True
    received = []

    async def generated(_project, _provider, phase, _feedback, current_spec, brief):
        received.append(current_spec)
        return compile_package(current_spec['spec'], phase=phase)

    monkeypatch.setattr(engine, 'generate_appspec_package', generated)
    asyncio.run(engine._advance(user_id, project_id, None))
    assert received[0]['spec_hash'] == initial['spec_hash']
    assert draft(user_id, project_id, 1)['spec_hash'] == initial['spec_hash']
    with workspace_db(user_id) as db:
        project = db.execute('SELECT current_version,stage,status FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['current_version'] == 1 and project['stage'] == 'build' and project['status'] == 'ready'


def test_plan_feedback_revises_the_draft_before_build(monkeypatch):
    user_id = 930101
    project_id = make_project(user_id)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    asyncio.run(engine._advance(user_id, project_id, None))
    initial = draft(user_id, project_id)
    asyncio.run(engine._revise_document(user_id, project_id, None, 'Emphasize a calm weekly overview.'))
    revised = draft(user_id, project_id)
    assert revised['spec_hash'] != initial['spec_hash']
    assert 'calm weekly overview' in revised['spec']['product']['brief']
    with workspace_db(user_id) as db:
        project = db.execute('SELECT current_version,status FROM projects WHERE id=?', (project_id,)).fetchone()
        plan = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path="plan.md"', (project_id,)).fetchone()
        assert project['current_version'] == 0 and project['status'] == 'ready'
        assert 'Revision direction' in plan['content']


def test_prebuild_message_revises_draft_without_creating_a_version(monkeypatch):
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': f'prebuild-feedback-{uuid.uuid4().hex}@example.com',
            'name': 'Prebuild Feedback Tester', 'password': 'password123',
        })
        account = response.json()
        user_id = account['user']['id']
        token = account['token']
        headers = {'Authorization': f'Bearer {token}'}
        project_id = make_project(user_id, stage='build')
        spec = local_default_appspec('Contract Review', 'A reviewable workspace.', 'single-file', 'static')
        with workspace_db(user_id) as db:
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'plan', 'plan.md', '# Plan', 0))
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'plan', 'appspec.json', appspec_document(spec), 0))
        response = client.post(f'/api/projects/{project_id}/messages', headers=headers, json={
            'content': 'Emphasize a calm weekly overview.', 'defer': False,
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['current_version'] == 0 and payload['versions'] == []
        assert 'calm weekly overview' in payload['appspec']['spec']['product']['brief']
        assert 'plan.md' in payload['messages'][-1]['content']


def test_prebuild_migration_updates_the_reviewed_architecture(monkeypatch):
    user_id = 930102
    project_id = make_project(user_id)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    asyncio.run(engine._advance(user_id, project_id, None))
    asyncio.run(engine._migrate_architecture(user_id, project_id, 'fastapi', None, 'Add shared state'))
    migrated = draft(user_id, project_id)
    assert migrated['spec']['architecture']['backend_mode'] == 'fastapi'
    assert migrated['spec']['architecture']['state_ownership'] == 'server'
    assert any(operation['path'] == '/api/health' for operation in migrated['spec']['api'])
    with workspace_db(user_id) as db:
        project = db.execute('SELECT backend_mode,current_version FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['backend_mode'] == 'fastapi' and project['current_version'] == 0


def test_invalid_plan_proposal_stops_before_saving_a_draft(monkeypatch):
    user_id = 930103
    project_id = make_project(user_id)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    monkeypatch.setattr(settings, 'durable_jobs_v1', False)

    async def invalid_proposal(*_args, **_kwargs):
        document = local_default_appspec('Invalid Draft', 'Invalid draft.', 'single-file', 'static').model_dump(
            mode='json', exclude_none=True,
        )
        second = dict(document['entities'][0])
        second['name'] = 'Second'
        document['entities'].append(second)
        return document

    monkeypatch.setattr(engine, 'propose_appspec', invalid_proposal)
    asyncio.run(engine.generate_stage(user_id, project_id, None))
    with workspace_db(user_id) as db:
        project = db.execute('SELECT stage,status,current_version FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['stage'] == 'plan' and project['status'] == 'error' and project['current_version'] == 0
        assert db.execute('SELECT COUNT(*) FROM artifacts WHERE project_id=?', (project_id,)).fetchone()[0] == 0


def test_review_detects_content_hash_tampering():
    spec = local_default_appspec('Hash Review', 'A hash-checked contract.', 'single-file', 'static')
    envelope = json.loads(appspec_document(spec))
    envelope['spec']['product']['name'] = 'Changed without rehashing'
    review = appspec_review(json.dumps(envelope), for_compilation=True)
    assert review['appspec_valid'] is False
    assert 'hash does not match' in review['appspec_error']


def test_invalid_draft_returns_review_error_and_blocks_approval(monkeypatch):
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        response = client.post('/api/auth/register', json={
            'email': f'invalid-draft-{uuid.uuid4().hex}@example.com',
            'name': 'Invalid Draft Tester', 'password': 'password123',
        })
        account = response.json()
        user_id = account['user']['id']
        token = account['token']
        headers = {'Authorization': f'Bearer {token}'}
        project_id = make_project(user_id, stage='build')
        with workspace_db(user_id) as db:
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'plan', 'appspec.json', '{"spec":{}}', 0))
        response = client.get(f'/api/projects/{project_id}', headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload['appspec_enabled'] is True
        assert payload['appspec'] is None and payload['appspec_valid'] is False
        assert payload['appspec_error']
        response = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={})
        assert response.status_code == 409
        assert 'AppSpec requires correction before building' in response.text
        with workspace_db(user_id) as db:
            assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=?', (project_id,)).fetchone()[0] == 0
            project = db.execute('SELECT current_version,status FROM projects WHERE id=?', (project_id,)).fetchone()
            assert project['current_version'] == 0 and project['status'] == 'ready'
