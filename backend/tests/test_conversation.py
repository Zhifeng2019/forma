from fixtures.accounts import register_account
import asyncio
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import api as api_module, conversation, engine
from app.config import settings
from app.database import workspace_db
from app.llm import GenerationError
from app.main import app
from app.schemas import MessageInput


@pytest.fixture
def workspace():
    with TestClient(app) as client:
        account = register_account(client, json={
            'email': f'conversation-{uuid.uuid4().hex}@example.com', 'name': 'Owner', 'password': 'password123',
        }).json()
        headers = {'Authorization': f'Bearer {account["token"]}'}
        project = client.post('/api/projects', headers=headers, json={
            'name': 'Conversation test', 'brief': 'A personal focus timer with a weekly overview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
        }).json()
        yield client, account['user']['id'], headers, project['id']


def state(user_id, project_id):
    with workspace_db(user_id) as db:
        project = dict(db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone())
        project.pop('updated_at')
        return {
            'project': project,
            **{table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} WHERE project_id=? ORDER BY id', (project_id,))]
               for table in ('artifacts', 'versions', 'events', 'generation_jobs')},
        }


def settled(client, headers, project_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        project = client.get(f'/api/projects/{project_id}', headers=headers).json()
        if project['status'] != 'working':
            return project
        time.sleep(0.02)
    raise AssertionError('Conversation remained busy')


def no_edit(*_args, **_kwargs):
    raise AssertionError('An answer must never enter the editing pipeline')


@pytest.mark.parametrize('stage,version', [('design', 0), ('plan', 0), ('build', 0), ('build', 1), ('review', 1), ('deploy', 1)])
@pytest.mark.parametrize('durable', [False, True])
@pytest.mark.parametrize('defer', [False, True])
def test_questions_preserve_project_and_artifacts(workspace, monkeypatch, stage, version, durable, defer):
    client, user_id, headers, project_id = workspace
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    monkeypatch.setattr(engine, 'provider_for_user', lambda *_: {'name': 'Test model'})
    monkeypatch.setattr(api_module, 'generate_stage', no_edit)
    monkeypatch.setattr(api_module, 'revise_document', no_edit)
    with workspace_db(user_id) as db:
        db.execute('UPDATE projects SET stage=?,current_version=?,phase_index=? WHERE id=?',
                   (stage, version, version, project_id))
        if version:
            db.execute('INSERT INTO versions(project_id,version,label) VALUES(?,?,?)', (project_id, version, 'Existing'))
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'build', 'index.html', '<html>Current source evidence</html>', version))
        # A different version must not be passed off as current implementation.
        db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                   (project_id, 'build', 'backend/main.py', 'WRONG_VERSION_SECRET', 99))
    calls = []

    async def complete(_provider, system, prompt, _schema, schema_name):
        payload = json.loads(prompt)
        calls.append(schema_name)
        assert payload['current_message'] == 'What are the admin login credentials?'
        assert payload['selected_element']['selector'] == '#login'
        if schema_name == 'message_intent':
            return {'intent': 'answer'}
        assert 'runtime database' in system and 'Never invent credentials' in system
        assert payload['context']['runtime_data_available'] is False
        assert 'WRONG_VERSION_SECRET' not in prompt
        assert 'product.md' in prompt
        if version:
            assert 'Current source evidence' in prompt
        return {'answer': 'I cannot verify the live admin credentials from the project source.'}

    monkeypatch.setattr(conversation, 'complete_with_schema', complete)
    before = state(user_id, project_id)
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers, json={
        'content': 'What are the admin login credentials?', 'defer': defer,
        'selection': {'selector': '#login', 'text': 'Log in'},
    })
    assert response.status_code == 200, response.text
    project = settled(client, headers, project_id)
    assert state(user_id, project_id) == before
    assert project['messages'][-1]['kind'] == 'answer'
    assert project['messages'][-1]['content'].startswith('I cannot verify')
    assert calls == ['message_intent', 'project_answer']


@pytest.mark.parametrize('message', [
    'What is the login credentials for admin?', 'Give me the admin password.',
    'Please reset the admin password.', 'How would you add login?', 'Why does this button fail?',
    'Can you change my admin password?', 'Create an admin account for me.',
    'Can you explain this selected element?', 'Make no changes. Explain the design.',
    'Please do not rebuild. What is the status?', '管理员的登录密码是什么？',
    'Looks good', 'Go ahead', 'Login is confusing',
])
def test_local_questions_operations_and_ambiguity_are_not_edits(message):
    project = {'name': 'Demo', 'stage': 'review', 'current_version': 4}
    result = asyncio.run(conversation.resolve_message(1, project, None, message, {'selector': '#login'}))
    assert result.intent in {'answer', 'clarify'}
    assert result.reply


@pytest.mark.parametrize('message', [
    'Make the header smaller.', 'Can you add a password-reset screen?', 'Fix the login error.',
    'Phase 1 must show invoice currency without conversion.', 'Reduce the top space a bit.', 'Keep approval history in phase 1.',
])
def test_local_explicit_changes_remain_edits(message):
    result = asyncio.run(conversation.resolve_message(1, {}, None, message))
    assert result.intent == 'change'


@pytest.mark.parametrize('reply', [None, {}, {'intent': 'rebuild'}, {'intent': True},
                                   {'intent': 'change', 'files': {}}, {'answer': 'Edit it'}])
def test_invalid_routing_and_provider_errors_never_edit(workspace, monkeypatch, reply):
    client, user_id, headers, project_id = workspace
    monkeypatch.setattr(engine, 'provider_for_user', lambda *_: {'name': 'Test model'})
    monkeypatch.setattr(api_module, 'generate_stage', no_edit)
    monkeypatch.setattr(api_module, 'revise_document', no_edit)

    async def complete(*_args):
        if reply is None:
            raise GenerationError('Provider unavailable')
        return reply

    monkeypatch.setattr(conversation, 'complete_with_schema', complete)
    before = state(user_id, project_id)
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers,
                           json={'content': 'What is the admin password?', 'defer': True})
    assert response.status_code == 200
    project = settled(client, headers, project_id)
    assert state(user_id, project_id) == before
    assert project['messages'][-1]['content'] == conversation.UNAVAILABLE


@pytest.mark.parametrize('answer', [None, '', ' ', {'files': {}}, 'x' * 12_001])
def test_invalid_answers_do_not_fall_back_to_generation(workspace, monkeypatch, answer):
    client, user_id, headers, project_id = workspace
    monkeypatch.setattr(engine, 'provider_for_user', lambda *_: {'name': 'Test model'})

    async def complete(_provider, _system, _prompt, _schema, schema_name):
        return {'intent': 'answer'} if schema_name == 'message_intent' else {'answer': answer}

    monkeypatch.setattr(conversation, 'complete_with_schema', complete)
    before = state(user_id, project_id)
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers, json={'content': 'Explain the plan'})
    assert response.status_code == 200
    assert state(user_id, project_id) == before
    assert response.json()['messages'][-1]['content'] == conversation.UNAVAILABLE


@pytest.mark.parametrize('durable', [False, True])
def test_question_then_change_only_creates_a_version_for_the_change(workspace, monkeypatch, durable):
    client, user_id, headers, project_id = workspace
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    for _ in range(3):
        project = client.post(f'/api/projects/{project_id}/advance', headers=headers, json={}).json()
    before = state(user_id, project_id)
    assert project['current_version'] == 1
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers,
                           json={'content': 'What is the admin password?'})
    assert response.status_code == 200
    assert state(user_id, project_id) == before
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers,
                           json={'content': 'Make the primary action clearer.', 'defer': True})
    assert response.status_code == 200
    project = settled(client, headers, project_id)
    assert (project['current_version'], project['phase_index']) == (2, 1)
    assert project['versions'][0]['note'] == 'Make the primary action clearer.'


def test_question_preserves_an_existing_error_status(workspace):
    client, user_id, headers, project_id = workspace
    with workspace_db(user_id) as db:
        db.execute("UPDATE projects SET status='error' WHERE id=?", (project_id,))
    before = state(user_id, project_id)
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers, json={'content': 'Why did it fail?'})
    assert response.status_code == 200
    assert state(user_id, project_id) == before


def test_interrupted_reply_does_not_leave_the_project_failed_or_busy(workspace, monkeypatch):
    _client, user_id, _headers, project_id = workspace
    before = state(user_id, project_id)

    async def cancel_reply():
        started = asyncio.Event()

        async def waiting(*_args):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(api_module, 'resolve_message', waiting)
        task = asyncio.create_task(api_module.send_message(
            project_id, MessageInput(content='What is the admin password?'), user={'id': user_id},
        ))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_reply())
    assert state(user_id, project_id) == before


def test_empty_or_other_owners_messages_do_not_reach_routing(workspace, monkeypatch):
    client, user_id, headers, project_id = workspace
    monkeypatch.setattr(api_module, 'resolve_message', no_edit)
    before = state(user_id, project_id)
    assert client.post(f'/api/projects/{project_id}/messages', headers=headers,
                       json={'content': '   '}).status_code == 422
    other = register_account(client, json={
        'email': f'other-{uuid.uuid4().hex}@example.com', 'name': 'Other', 'password': 'password123',
    }).json()
    assert client.post(f'/api/projects/{project_id}/messages',
                       headers={'Authorization': f'Bearer {other["token"]}'},
                       json={'content': 'What is the admin password?'}).status_code == 404
    assert state(user_id, project_id) == before


@pytest.mark.parametrize('intent', ['change', 'clarify'])
def test_model_decisions_do_not_request_an_answer_or_read_source(workspace, monkeypatch, intent):
    _client, user_id, _headers, project_id = workspace
    monkeypatch.setattr(conversation, '_answer_context', no_edit)

    async def complete(_provider, system, _prompt, _schema, schema_name):
        assert schema_name == 'message_intent'
        # Providers without native JSON Schema support still need the exact JSON contract.
        assert '{"intent":"answer"}' in system
        return {'intent': intent}

    monkeypatch.setattr(conversation, 'complete_with_schema', complete)
    result = asyncio.run(conversation.resolve_message(
        user_id, state(user_id, project_id)['project'], {'name': 'Model'},
        'Make the heading smaller.' if intent == 'change' else 'Looks good.',
    ))
    assert result.intent == intent
    assert result.reply == (conversation.CLARIFICATION if intent == 'clarify' else '')


@pytest.mark.parametrize('durable', [False, True])
def test_question_pauses_autopilot_without_refining_or_advancing(workspace, monkeypatch, durable):
    client, user_id, headers, project_id = workspace
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    real = engine.generate_stage

    async def delayed(*args, **kwargs):
        await real(*args, **kwargs)
        await asyncio.sleep(0.2)

    monkeypatch.setattr(api_module, 'generate_stage', delayed)
    created = client.post('/api/projects', headers=headers, json={
        'name': 'Autopilot question', 'brief': 'A personal focus timer.',
        'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': True, 'defer': True,
    }).json()
    project_id = created['id']
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        project = client.get(f'/api/projects/{project_id}', headers=headers).json()
        if project['current_version'] == 1 and project['status'] == 'ready':
            break
        time.sleep(0.01)
    assert project['current_version'] == 1
    before = state(user_id, project_id)
    response = client.post(f'/api/projects/{project_id}/messages', headers=headers,
                           json={'content': 'What has been built so far?', 'defer': True})
    assert response.status_code == 200
    settled(client, headers, project_id)
    time.sleep(0.5)
    after = state(user_id, project_id)
    assert after['project']['current_version'] == after['project']['phase_index'] == 1
    assert not after['project']['auto_mode']
    for key in ('artifacts', 'versions', 'generation_jobs'):
        assert after[key] == before[key]
