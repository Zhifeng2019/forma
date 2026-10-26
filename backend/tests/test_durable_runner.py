import asyncio
from datetime import datetime, timedelta
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import engine
from app.config import settings
from app.database import workspace_db, workspace_for
from app.jobs.leases import request_cancellation
from app.jobs.models import StaleJobError
from app.jobs.runner import run_generation_job
from app.main import app


def make_project(user_id: int, stage: str = 'build', backend_mode: str = 'static') -> str:
    project_id = uuid.uuid4().hex
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        db.execute('INSERT INTO projects(id,name,brief,stage,backend_mode) VALUES(?,?,?,?,?)',
                   (project_id, 'Durable Test', 'Verify durable generation', stage, backend_mode))
    return project_id


def execute_job(user_id: int, project_id: str, operation_factory, **kwargs) -> bool:
    input_data = kwargs.pop('input_data', {
        'project_id': project_id, 'stage': 'build', 'version': 1, 'source_format': 'single-file',
    })
    return asyncio.run(run_generation_job(
        user_id, project_id, 'build', 'advance-stage', input_data, operation_factory, **kwargs,
    ))


def test_successful_job_persists_attempt_and_checkpoints():
    user_id = 910101
    project_id = make_project(user_id)
    calls = []

    async def operation():
        calls.append('ran')

    assert execute_job(user_id, project_id, operation) is True
    assert calls == ['ran']
    with workspace_db(user_id) as db:
        job = db.execute('SELECT * FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()
        assert job['status'] == 'succeeded' and job['current_attempt'] == 1
        assert len(job['trace_id']) == 32
        attempt = db.execute('SELECT * FROM job_attempts WHERE job_id=?', (job['id'],)).fetchone()
        assert attempt['attempt_number'] == 1 and attempt['ended_at'] is not None
        events = db.execute('SELECT payload FROM job_events WHERE job_id=? ORDER BY id', (job['id'],)).fetchall()
        assert [json.loads(row['payload'])['name'] for row in events] == ['start', 'end']


def test_duplicate_job_does_not_start_another_attempt():
    user_id = 910102
    project_id = make_project(user_id)
    calls = []

    async def operation():
        calls.append('ran')

    assert execute_job(user_id, project_id, operation) is True
    assert execute_job(user_id, project_id, operation) is False
    assert calls == ['ran']
    with workspace_db(user_id) as db:
        assert db.execute('SELECT COUNT(*) FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0] == 1
        assert db.execute('''SELECT COUNT(*) FROM job_attempts JOIN generation_jobs
            ON job_attempts.job_id=generation_jobs.id WHERE generation_jobs.project_id=?''',
            (project_id,)).fetchone()[0] == 1


def test_concurrent_duplicate_does_not_start_another_operation():
    user_id = 910107
    project_id = make_project(user_id)

    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def operation():
            calls.append('ran')
            started.set()
            await release.wait()

        input_data = {'project_id': project_id, 'stage': 'build', 'version': 1}
        first = asyncio.create_task(run_generation_job(
            user_id, project_id, 'build', 'advance-stage', input_data, operation,
        ))
        await asyncio.wait_for(started.wait(), timeout=2)
        duplicate = await run_generation_job(
            user_id, project_id, 'build', 'advance-stage', input_data, operation,
        )
        assert duplicate is False
        release.set()
        assert await asyncio.wait_for(first, timeout=2) is True
        assert calls == ['ran']

    asyncio.run(scenario())
    with workspace_db(user_id) as db:
        assert db.execute('SELECT COUNT(*) FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0] == 1
        assert db.execute('''SELECT COUNT(*) FROM job_attempts JOIN generation_jobs
            ON job_attempts.job_id=generation_jobs.id WHERE generation_jobs.project_id=?''',
            (project_id,)).fetchone()[0] == 1


def test_shutdown_cancellation_finalizes_attempt_and_project_error():
    user_id = 910108
    project_id = make_project(user_id)

    async def scenario():
        started = asyncio.Event()

        async def operation():
            started.set()
            await asyncio.sleep(30)

        task = asyncio.create_task(run_generation_job(
            user_id, project_id, 'build', 'advance-stage',
            {'project_id': project_id, 'stage': 'build', 'version': 1}, operation,
        ))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    with workspace_db(user_id) as db:
        job = db.execute('SELECT * FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()
        attempt = db.execute('SELECT * FROM job_attempts WHERE job_id=?', (job['id'],)).fetchone()
        project = db.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()
        event = db.execute('SELECT message FROM events WHERE project_id=? ORDER BY id DESC LIMIT 1', (project_id,)).fetchone()
        assert job['status'] == 'cancelled' and attempt['failure_code'] == 'cancelled'
        assert attempt['ended_at'] is not None and project['status'] == 'error'
        assert event['message'] == 'Generation stopped. Retry this stage.'


def test_failed_job_retries_as_a_new_attempt():
    user_id = 910103
    project_id = make_project(user_id)

    async def fail():
        raise RuntimeError('deliberate failure')

    async def succeed():
        pass

    with pytest.raises(RuntimeError, match='deliberate failure'):
        execute_job(user_id, project_id, fail)
    with workspace_db(user_id) as db:
        assert db.execute('SELECT status FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0] == 'failed'
    assert execute_job(user_id, project_id, succeed) is True
    with workspace_db(user_id) as db:
        job = db.execute('SELECT * FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()
        attempts = db.execute('SELECT * FROM job_attempts WHERE job_id=? ORDER BY attempt_number', (job['id'],)).fetchall()
        assert job['status'] == 'succeeded' and job['current_attempt'] == 2
        assert [row['attempt_number'] for row in attempts] == [1, 2]
        assert attempts[0]['failure_code'] == 'RuntimeError'
        assert attempts[1]['ended_at'] is not None


def test_heartbeat_extends_lease_for_a_longer_operation():
    user_id = 910104
    project_id = make_project(user_id)

    async def operation():
        await asyncio.sleep(0.45)

    assert execute_job(user_id, project_id, operation, lease_seconds=0.2, heartbeat_interval=0.02) is True
    with workspace_db(user_id) as db:
        attempt = db.execute('''SELECT job_attempts.* FROM job_attempts JOIN generation_jobs
            ON job_attempts.job_id=generation_jobs.id WHERE generation_jobs.project_id=?''', (project_id,)).fetchone()
        started = datetime.fromisoformat(attempt['started_at'])
        heartbeat_at = datetime.fromisoformat(attempt['heartbeat_at'])
        expires = datetime.fromisoformat(attempt['lease_expires_at'])
        assert heartbeat_at > started
        assert expires > started + timedelta(seconds=0.2)
        assert db.execute('SELECT status FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0] == 'succeeded'


def test_cancellation_stops_operation_and_leaves_retryable_project_error():
    user_id = 910105
    project_id = make_project(user_id)

    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def operation():
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(run_generation_job(
            user_id, project_id, 'build', 'advance-stage',
            {'project_id': project_id, 'stage': 'build', 'version': 1}, operation,
            heartbeat_interval=0.02,
        ))
        await asyncio.wait_for(started.wait(), timeout=2)
        with workspace_db(user_id) as db:
            job_id = db.execute('SELECT id FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0]
            assert request_cancellation(db, job_id) is True
        assert await asyncio.wait_for(task, timeout=2) is True
        assert cancelled.is_set()

    asyncio.run(scenario())
    with workspace_db(user_id) as db:
        job = db.execute('SELECT * FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()
        attempt = db.execute('SELECT * FROM job_attempts WHERE job_id=?', (job['id'],)).fetchone()
        project = db.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()
        event = db.execute('SELECT message FROM events WHERE project_id=? ORDER BY id DESC LIMIT 1', (project_id,)).fetchone()
        assert job['status'] == 'cancelled'
        assert attempt['ended_at'] is not None and attempt['failure_code'] == 'cancelled'
        assert project['status'] == 'error' and 'Retry this stage' in event['message']


def test_stale_input_hash_is_rejected_at_finalization():
    user_id = 910106
    project_id = make_project(user_id)

    async def change_input():
        with workspace_db(user_id) as db:
            db.execute('UPDATE generation_jobs SET input_hash=? WHERE project_id=?', ('stale-input', project_id))

    with pytest.raises(StaleJobError, match='Job input changed'):
        execute_job(user_id, project_id, change_input)
    with workspace_db(user_id) as db:
        job = db.execute('SELECT * FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()
        attempt = db.execute('SELECT * FROM job_attempts WHERE job_id=?', (job['id'],)).fetchone()
        assert job['status'] == 'failed' and attempt['failure_code'] == 'StaleJobError'


@pytest.mark.parametrize('enabled', [False, True])
def test_engine_generation_uses_runner_only_when_enabled(monkeypatch, enabled):
    user_id = 910110 + int(enabled)
    project_id = make_project(user_id, stage='design')
    monkeypatch.setattr(settings, 'durable_jobs_v1', enabled)
    calls = []

    async def legacy(*args):
        calls.append(('legacy', args))

    async def durable(*args):
        calls.append(('durable', args))
        return True

    monkeypatch.setattr(engine, '_generate_stage_legacy', legacy)
    monkeypatch.setattr(engine, 'run_generation_job', durable)
    asyncio.run(engine.generate_stage(user_id, project_id, None, 'Refine navigation'))
    assert [call[0] for call in calls] == ['durable' if enabled else 'legacy']
    if enabled:
        args = calls[0][1]
        assert args[2] == 'design' and args[3] == 'advance-stage'
        assert args[4]['feedback'] == 'Refine navigation'
        assert args[4]['source_format'] == 'single-file'


def test_document_and_migration_wrappers_use_durable_actions(monkeypatch):
    user_id = 910112
    project_id = make_project(user_id)
    monkeypatch.setattr(settings, 'durable_jobs_v1', True)
    calls = []

    async def durable(*args):
        calls.append(args)
        return True

    monkeypatch.setattr(engine, 'run_generation_job', durable)
    asyncio.run(engine.revise_document(user_id, project_id, None, 'Clarify the release scope'))
    asyncio.run(engine.migrate_architecture(user_id, project_id, 'fastapi', None, 'Add shared state', deferred=True))
    assert [call[3] for call in calls] == ['revise-document', 'migrate']
    assert calls[1][4]['target'] == 'fastapi'
    assert calls[1][4]['feedback'] == 'Add shared state'


def register(client: TestClient, label: str) -> dict:
    response = client.post('/api/auth/register', json={
        'email': f'{label}-{uuid.uuid4().hex}@example.com',
        'name': 'Durable Tester', 'password': 'password123',
    })
    assert response.status_code == 200, response.text
    return response.json()


def auth(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def wait_for_stage(client: TestClient, token: str, project_id: str, stage: str) -> dict:
    deadline = time.monotonic() + 10
    project = {}
    while time.monotonic() < deadline:
        project = client.get(f'/api/projects/{project_id}', headers=auth(token)).json()
        if project['stage'] == stage or project['status'] == 'error':
            return project
        time.sleep(0.03)
    raise AssertionError(f'Generation did not reach {stage}: {project}')


@pytest.mark.parametrize('durable', [False, True])
def test_deferred_autopilot_has_no_duplicate_versions(monkeypatch, durable):
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    with TestClient(app) as client:
        account = register(client, f'durable-autopilot-{durable}')
        token = account['token']
        response = client.post('/api/projects', headers=auth(token), json={
            'name': 'Durable Autopilot', 'brief': 'A personal focus timer with a weekly overview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': True, 'defer': True,
        })
        assert response.status_code == 200, response.text
        project_id = response.json()['id']
        project = wait_for_stage(client, token, project_id, 'review')
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['current_version'] == 3
        assert sorted(item['version'] for item in project['versions']) == [1, 2, 3]
        with workspace_db(account['user']['id']) as db:
            jobs = db.execute('SELECT status FROM generation_jobs WHERE project_id=?', (project_id,)).fetchall()
            assert len(jobs) == (6 if durable else 0)
            assert all(row['status'] == 'succeeded' for row in jobs)
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200


@pytest.mark.parametrize('durable', [False, True])
def test_deferred_migration_completes_once(monkeypatch, durable):
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    with TestClient(app) as client:
        account = register(client, f'durable-migration-{durable}')
        token = account['token']
        response = client.post('/api/projects', headers=auth(token), json={
            'name': 'Durable Migration', 'brief': 'A personal workspace ready for a shared API.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
        })
        assert response.status_code == 200, response.text
        project = response.json()
        project_id = project['id']
        for _ in range(3):
            response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
            assert response.status_code == 200, response.text
            project = response.json()
        assert project['current_version'] == 1
        response = client.post(f'/api/projects/{project_id}/architecture', headers=auth(token), json={
            'target_mode': 'fastapi', 'feedback': 'Add shared state.', 'defer': True,
        })
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            project = client.get(f'/api/projects/{project_id}', headers=auth(token)).json()
            if project['status'] != 'working':
                break
            time.sleep(0.03)
        assert project['status'] == 'ready', project['messages'][-1]['content']
        assert project['backend_mode'] == 'fastapi' and project['current_version'] == 2
        assert sorted(item['version'] for item in project['versions']) == [1, 2]
        with workspace_db(account['user']['id']) as db:
            assert db.execute('SELECT COUNT(*) FROM generation_jobs WHERE project_id=?',
                              (project_id,)).fetchone()[0] == (5 if durable else 0)
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200
