import asyncio
import json
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.database import workspace_db, workspace_for
from app.jobs.leases import request_cancellation
from app.jobs.runner import run_generation_job
from app.jobs.service import create_job, record_event
from app.main import app


def register(client, label):
    response = client.post('/api/auth/register', json={
        'email': f'{label}-{uuid.uuid4().hex}@example.com',
        'name': 'Event Tester', 'password': 'password123',
    })
    assert response.status_code == 200, response.text
    return response.json()


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def make_project(user_id):
    project_id = uuid.uuid4().hex
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        db.execute('INSERT INTO projects(id,name,brief,stage,backend_mode) VALUES(?,?,?,?,?)',
                   (project_id, 'Event App', 'Verify event replay', 'build', 'static'))
    return project_id


def events(response):
    return [json.loads(line.removeprefix('data:').strip())
            for line in response.text.splitlines() if line.startswith('data:')]


def test_replay_is_ordered_bounded_and_content_safe():
    with TestClient(app) as client:
        account = register(client, 'event-replay')
        user_id = account['user']['id']
        project_id = make_project(user_id)
        with workspace_db(user_id) as db:
            job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
            record_event(db, job_id, 'checkpoint', {
                'name': 'start', 'secret': 'api_key=super-secret',
                'path': f'{settings.data_path}/private/file',
                'url': 'https://user:pass@example.com/path?token=secret',
            }, '1:start')
            record_event(db, job_id, 'job.succeeded', {'attempt_id': 1}, '1:succeeded')
            record_event(db, job_id, 'project.refresh', {'status': 'succeeded', 'attempt_id': 1}, '1:project.refresh')

        response = client.get(f'/api/projects/{project_id}/events?limit=2', headers=auth(account['token']))
        assert response.status_code == 200, response.text
        assert response.headers['content-type'].startswith('text/event-stream')
        assert response.headers['x-event-cursor'] == '2'
        assert ': heartbeat' in response.text and 'retry: 1500' in response.text
        frames = events(response)
        assert [frame['type'] for frame in frames] == ['job.progress', 'job.succeeded', 'stream.complete']
        assert [frame['id'] for frame in frames] == [1, 2, 2]
        first = frames[0]
        assert first['schema_version'] == '1.0'
        assert first['job_id'] == job_id and first['attempt_id'] == 1
        assert first['timestamp'].endswith('+00:00')
        serialized = json.dumps(first)
        assert 'super-secret' not in serialized and 'user:pass' not in serialized
        assert str(settings.data_path) not in serialized and 'token=secret' not in serialized

        response = client.get(f'/api/projects/{project_id}/events', headers={
            **auth(account['token']), 'Last-Event-ID': '2',
        })
        assert response.headers['x-event-cursor'] == '3'
        assert [frame['type'] for frame in events(response)] == ['project.refresh', 'stream.complete']

        response = client.get(f'/api/projects/{project_id}/events?after=1', headers=auth(account['token']))
        assert [frame['id'] for frame in events(response)] == [2, 3, 3]


def test_cursor_validation_and_owner_isolation():
    with TestClient(app) as client:
        owner = register(client, 'event-owner')
        other = register(client, 'event-other')
        project_id = make_project(owner['user']['id'])
        with workspace_db(owner['user']['id']) as db:
            job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
            record_event(db, job_id, 'job.succeeded', {'attempt_id': 1}, '1:succeeded')
        url = f'/api/projects/{project_id}/events'
        assert client.get(f'{url}?after=-1', headers=auth(owner['token'])).status_code == 422
        assert client.get(f'{url}?after=not-a-number', headers=auth(owner['token'])).status_code == 422
        expired = client.get(f'{url}?after=99', headers=auth(owner['token']))
        assert expired.status_code == 409
        assert expired.json()['detail']['error'] == 'cursor_expired'
        assert expired.json()['detail']['high_watermark'] == 1
        assert client.get(url).status_code == 401
        assert client.get(url, headers=auth(other['token'])).status_code == 404


def test_success_and_cancellation_emit_lifecycle_and_refresh_events():
    with TestClient(app) as client:
        account = register(client, 'event-lifecycle')
        user_id = account['user']['id']
        project_id = make_project(user_id)

        async def succeed():
            pass

        asyncio.run(run_generation_job(
            user_id, project_id, 'build', 'advance-stage',
            {'project_id': project_id, 'stage': 'build', 'version': 1}, succeed,
        ))

        async def cancel_running():
            started = asyncio.Event()

            async def operation():
                started.set()
                await asyncio.sleep(30)

            task = asyncio.create_task(run_generation_job(
                user_id, project_id, 'verify', 'verify-package',
                {'project_id': project_id, 'version': 1, 'spec_hash': 'spec', 'source_hash': 'source',
                 'include_optional': False, 'selected_check_ids': []}, operation,
            ))
            await asyncio.wait_for(started.wait(), timeout=2)
            with workspace_db(user_id) as db:
                job_id = db.execute('''SELECT id FROM generation_jobs WHERE project_id=?
                    AND status IN ('running','leased') ORDER BY updated_at DESC LIMIT 1''',
                    (project_id,)).fetchone()[0]
                assert request_cancellation(db, job_id)
            assert await asyncio.wait_for(task, timeout=2) is True

        asyncio.run(cancel_running())
        with workspace_db(user_id) as db:
            types = [row['event_type'] for row in db.execute(
                'SELECT event_type FROM job_events ORDER BY id', (),
            )]
        assert 'job.started' in types and 'job.succeeded' in types
        assert 'cancel_requested' in types and 'cancelling' in types and 'cancelled' in types
        assert types.count('project.refresh') == 2

        response = client.get(f'/api/projects/{project_id}/events', headers=auth(account['token']))
        mapped = {frame['type'] for frame in events(response)}
        assert 'job.succeeded' in mapped and 'job.cancelled' in mapped
        assert 'project.refresh' in mapped and 'stream.complete' in mapped
