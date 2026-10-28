import asyncio
import uuid

from fastapi.testclient import TestClient

from app.database import workspace_db
from app.jobs.events import follow_frames
from app.jobs.service import create_job, record_event
from app.main import app
from test_event_replay import auth, make_project, register


def test_follow_frames_tail_new_events_and_idle_heartbeats():
    user_id = 950001
    project_id = make_project(user_id)
    with workspace_db(user_id) as db:
        job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
        record_event(db, job_id, 'job.started', {'attempt_id': 1}, '1:started')

    async def scenario():
        stream = follow_frames(user_id, project_id, 0, 200, 0.02)
        assert await anext(stream) == ': heartbeat\n\n'
        assert await anext(stream) == 'retry: 1500\n\n'
        first = await anext(stream)
        assert 'job.started' in first and 'id: 1' in first
        assert await anext(stream) == ': heartbeat\n\n'
        with workspace_db(user_id) as db:
            record_event(db, job_id, 'job.succeeded', {'attempt_id': 1}, '1:succeeded')
        second = await anext(stream)
        assert 'job.succeeded' in second and 'id: 2' in second
        await stream.aclose()

    asyncio.run(scenario())


def test_follow_endpoint_streams_live_and_validates_cursor(monkeypatch):
    with TestClient(app) as client:
        account = register(client, 'follow-endpoint')
        project_id = make_project(account['user']['id'])
        with workspace_db(account['user']['id']) as db:
            job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
            record_event(db, job_id, 'job.started', {'attempt_id': 1}, '1:started')
        from app.jobs.events import replay_frames
        monkeypatch.setattr('app.api.follow_frames', lambda _user, project, cursor, _limit, _heartbeat: replay_frames([{
            'schema_version': '1.0', 'id': 1, 'job_id': job_id, 'attempt_id': 1,
            'type': 'job.started', 'timestamp': '2026-01-01T00:00:00+00:00', 'payload': {},
        }], project, cursor))

        response = client.get(
            f'/api/projects/{project_id}/events?follow=true&heartbeat_seconds=0.01',
            headers=auth(account['token']),
        )
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/event-stream')
        assert ': heartbeat' in response.text and 'retry: 1500' in response.text
        assert 'job.started' in response.text
        expired = client.get(
            f'/api/projects/{project_id}/events?follow=true&after=99',
            headers=auth(account['token']),
        )
        assert expired.status_code == 409
        assert expired.json()['detail']['error'] == 'cursor_expired'
