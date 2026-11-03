import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import api as api_module, engine
from app.config import settings
from app.main import app
from test_durable_runner import auth, register


def poll(client, token, project_id, done, timeout=20):
    deadline = time.monotonic() + timeout
    project = {}
    while time.monotonic() < deadline:
        project = client.get(f'/api/projects/{project_id}', headers=auth(token)).json()
        if done(project):
            return project
        time.sleep(0.02)
    raise AssertionError(f'Project did not reach the expected state: {project["stage"]} {project["status"]}')


@pytest.mark.parametrize('durable', [False, True])
def test_feedback_pauses_autopilot_and_refines_current_phase(monkeypatch, durable):
    monkeypatch.setattr(settings, 'durable_jobs_v1', durable)
    real = engine.generate_stage

    async def delayed(*args, **kwargs):
        # Job finalization leaves a window between autopilot steps in which the owner can reply.
        await real(*args, **kwargs)
        await asyncio.sleep(0.3)

    monkeypatch.setattr(api_module, 'generate_stage', delayed)
    with TestClient(app) as client:
        token = register(client, f'feedback-autopilot-{durable}')['token']
        project_id = client.post('/api/projects', headers=auth(token), json={
            'name': 'Feedback Autopilot', 'brief': 'A personal focus timer with a weekly overview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': True, 'defer': True,
        }).json()['id']
        poll(client, token, project_id, lambda p: p['stage'] == 'build' and p['phase_index'] == 1 and p['status'] == 'ready')
        advance = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={'feedback': '', 'defer': True})
        assert advance.status_code == 409
        response = client.post(f'/api/projects/{project_id}/messages', headers=auth(token),
                               json={'content': 'Reduce the top space a bit.', 'defer': True})
        assert response.status_code == 200, response.text
        project = poll(client, token, project_id, lambda p: p['status'] != 'working' and p['current_version'] == 2)
        time.sleep(0.8)
        project = client.get(f'/api/projects/{project_id}', headers=auth(token)).json()
        assert (project['stage'], project['phase_index'], project['current_version']) == ('build', 1, 2)
        assert not project['auto_mode']
        latest = max(project['versions'], key=lambda item: item['version'])
        assert (latest['label'], latest['note']) == ('Refinement', 'Reduce the top space a bit.')
        assert not any('Phase 2' in message['content'] for message in project['messages'])
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200


def test_feedback_is_rejected_while_an_autopilot_step_runs(monkeypatch):
    real = engine.generate_stage

    async def delayed(*args, **kwargs):
        await asyncio.sleep(0.3)
        return await real(*args, **kwargs)

    monkeypatch.setattr(api_module, 'generate_stage', delayed)
    with TestClient(app) as client:
        token = register(client, 'feedback-mid-step')['token']
        project_id = client.post('/api/projects', headers=auth(token), json={
            'name': 'Mid Step', 'brief': 'A personal focus timer with a weekly overview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': True, 'defer': True,
        }).json()['id']
        poll(client, token, project_id, lambda p: p['stage'] == 'build' and p['phase_index'] == 1)
        response = client.post(f'/api/projects/{project_id}/messages', headers=auth(token),
                               json={'content': 'Reduce the top space a bit.', 'defer': True})
        assert response.status_code == 409
        project = poll(client, token, project_id, lambda p: p['stage'] == 'review' and p['status'] == 'ready')
        assert project['phase_index'] == 3


def test_approving_release_does_not_regenerate(monkeypatch):
    with TestClient(app) as client:
        token = register(client, 'approve-release')['token']
        project_id = client.post('/api/projects', headers=auth(token), json={
            'name': 'Release Approval', 'brief': 'A personal focus timer with a weekly overview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': True, 'defer': True,
        }).json()['id']
        project = poll(client, token, project_id, lambda p: p['stage'] == 'review' and p['status'] == 'ready')
        version = project['current_version']
        response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={'feedback': ''})
        assert response.status_code == 200, response.text
        project = response.json()
        assert (project['stage'], project['current_version']) == ('deploy', version)
        assert len(project['versions']) == version
        assert project['messages'][-1]['content'] == 'The release is approved. Publish it when you are ready.'
