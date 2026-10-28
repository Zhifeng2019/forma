import uuid

from fastapi.testclient import TestClient

from app.database import workspace_db
from app.jobs.leases import complete_attempt, lease_next_job
from app.jobs.models import JobStatus
from app.jobs.service import create_job, record_event
from app.main import app
from test_event_replay import auth, events, make_project, register


def test_replay_across_attempts_is_ordered_and_deduplicated():
    with TestClient(app) as client:
        account = register(client, 'event-attempts')
        project_id = make_project(account['user']['id'])
        with workspace_db(account['user']['id']) as db:
            job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
            first = lease_next_job(db, 'worker-a', job_id=job_id)
            record_event(db, job_id, 'job.failed', {'error': 'first attempt failed'}, f'{first["attempt_id"]}:failed')
            complete_attempt(db, first['attempt_id'], JobStatus.FAILED.value, 'RuntimeError')
            db.execute("UPDATE generation_jobs SET status='recovery_required' WHERE id=?", (job_id,))
            second = lease_next_job(db, 'worker-b', job_id=job_id)
            record_event(db, job_id, 'job.succeeded', {'attempt_id': second['attempt_id']},
                         f'{second["attempt_id"]}:succeeded')
            complete_attempt(db, second['attempt_id'], JobStatus.SUCCEEDED.value)

        response = client.get(f'/api/projects/{project_id}/events', headers=auth(account['token']))
        frames = events(response)
        assert [frame['type'] for frame in frames] == ['job.failed', 'job.succeeded', 'stream.complete']
        assert [frame['attempt_id'] for frame in frames] == [1, 2, None]
        assert [frame['id'] for frame in frames] == [1, 2, 2]

        response = client.get(f'/api/projects/{project_id}/events', headers={
            **auth(account['token']), 'Last-Event-ID': '1',
        })
        frames = events(response)
        assert [frame['type'] for frame in frames] == ['job.succeeded', 'stream.complete']
        assert frames[0]['attempt_id'] == 2


def test_expired_cursor_does_not_start_a_stream(monkeypatch):
    with TestClient(app) as client:
        account = register(client, 'event-expired')
        project_id = make_project(account['user']['id'])
        with workspace_db(account['user']['id']) as db:
            job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
            record_event(db, job_id, 'job.started', {'attempt_id': 1}, '1:started')

        def unexpected(*_args, **_kwargs):
            raise AssertionError('An expired cursor must not start a stream')

        monkeypatch.setattr('app.api.follow_frames', unexpected)
        monkeypatch.setattr('app.api.replay_frames', unexpected)
        response = client.get(
            f'/api/projects/{project_id}/events?follow=true&after=999',
            headers=auth(account['token']),
        )
        assert response.status_code == 409
        assert response.json()['detail'] == {'error': 'cursor_expired', 'high_watermark': 1}
