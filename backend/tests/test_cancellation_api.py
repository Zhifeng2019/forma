import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import workspace_db, workspace_for
from app.jobs.context import (
    JobContext, activate_job_context, current_job_context, reset_job_context,
)
from app.jobs.leases import request_cancellation
from app.jobs.models import JobCancelledError
from app.jobs.runner import run_generation_job
from app.jobs.service import active_job, create_job
from app.main import app


def register(client, label):
    response = client.post('/api/auth/register', json={
        'email': f'{label}-{uuid.uuid4().hex}@example.com',
        'name': 'Cancellation Tester', 'password': 'password123',
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
                   (project_id, 'Cancellation App', 'Verify cooperative cancellation', 'build', 'static'))
    return project_id


def test_job_context_traces_tool_ownership_and_cancellation():
    event = asyncio.Event()
    context = JobContext(
        user_id=920001, project_id='project-fixture', job_id='job-fixture',
        attempt_id=7, trace_id='trace-fixture', cancellation=event,
    )
    token = activate_job_context(context)
    try:
        assert current_job_context() is context
        ownership = context.own_tool('tool-1', 4242)
        assert ownership.process_group_id == 4242
        assert context.owns_tool('tool-1', 4242)
        with pytest.raises(ValueError, match='different owner'):
            context.own_tool('tool-1', 4243)
        assert context.release_tool('tool-1') == ownership
        assert context.tool_owners == {}
    finally:
        reset_job_context(token)
    assert current_job_context() is None
    event.set()
    with pytest.raises(JobCancelledError, match='Retry this stage'):
        context.raise_if_cancelled()


def test_cancel_endpoint_is_owner_scoped_and_idempotent():
    with TestClient(app) as client:
        owner = register(client, 'cancel-owner')
        other = register(client, 'cancel-other')
        user_id = owner['user']['id']
        project_id = make_project(user_id)
        with workspace_db(user_id) as db:
            job_id, created = create_job(
                db, project_id, 'build', 'fixture-input', 'advance-stage', uuid.uuid4().hex,
            )
            assert created
        url = f'/api/projects/{project_id}/jobs/{job_id}/cancel'
        assert client.post(url).status_code == 401
        assert client.post(url, headers=auth(other['token'])).status_code == 404

        first = client.post(url, headers=auth(owner['token']))
        assert first.status_code == 200, first.text
        assert first.json() == {
            'job_id': job_id, 'status': 'cancel_requested', 'current_attempt': 0, 'changed': True,
        }
        project = client.get(f'/api/projects/{project_id}', headers=auth(owner['token'])).json()
        assert project['active_job']['id'] == job_id
        assert project['active_job']['status'] == 'cancel_requested'

        second = client.post(url, headers=auth(owner['token']))
        assert second.status_code == 200
        assert second.json()['changed'] is False
        assert second.json()['current_attempt'] == 0
        with workspace_db(user_id) as db:
            assert db.execute('SELECT COUNT(*) FROM job_attempts WHERE job_id=?', (job_id,)).fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type='cancel_requested'",
                              (job_id,)).fetchone()[0] == 1
            assert db.execute('SELECT current_attempt FROM generation_jobs WHERE id=?', (job_id,)).fetchone()[0] == 0


def test_running_cancellation_persists_each_transition_once_without_retry():
    user_id = 920002
    project_id = make_project(user_id)

    async def scenario():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        observed = []

        async def operation():
            context = current_job_context()
            observed.append((context.job_id, context.attempt_id, context.trace_id))
            context.own_tool('operation-probe', 4343)
            context.release_tool('operation-probe')
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(run_generation_job(
            user_id, project_id, 'build', 'advance-stage',
            {'project_id': project_id, 'stage': 'build', 'version': 1}, operation,
        ))
        await asyncio.wait_for(started.wait(), timeout=2)
        with workspace_db(user_id) as db:
            job_id = db.execute('SELECT id FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0]
            assert request_cancellation(db, job_id) is True
            assert request_cancellation(db, job_id) is False
        assert await asyncio.wait_for(task, timeout=2) is True
        assert cancelled.is_set()
        return job_id, observed

    job_id, observed = asyncio.run(scenario())
    with workspace_db(user_id) as db:
        job = db.execute('SELECT * FROM generation_jobs WHERE id=?', (job_id,)).fetchone()
        attempts = db.execute('SELECT * FROM job_attempts WHERE job_id=?', (job_id,)).fetchall()
        assert job['status'] == 'cancelled' and job['current_attempt'] == 1
        assert len(attempts) == 1 and attempts[0]['failure_code'] == 'cancelled'
        assert observed == [(job_id, attempts[0]['id'], job['trace_id'])]
        for status in ('cancel_requested', 'cancelling', 'cancelled'):
            count = db.execute('SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type=?',
                               (job_id, status)).fetchone()[0]
            assert count == 1, status
        assert active_job(db, project_id) is None
        project = db.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['status'] == 'error'
