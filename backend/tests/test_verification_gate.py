import asyncio
import threading
import time
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.database import control_db, workspace_db
from app.main import app


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def register(client, label):
    response = client.post('/api/auth/register', json={
        'email': f'{label}-{uuid.uuid4().hex}@example.com',
        'name': 'Gate Tester', 'password': 'password123',
    })
    assert response.status_code == 200, response.text
    return response.json()


def build_version(client, label, appspec=True):
    account = register(client, label)
    token = account['token']
    response = client.post('/api/projects', headers=auth(token), json={
        'name': 'Gate App', 'brief': 'A verified application ready for release.',
        'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
    })
    assert response.status_code == 200, response.text
    project_id = response.json()['id']
    for _ in range(3):
        response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
        assert response.status_code == 200, response.text
    assert response.json()['current_version'] == 1
    return account, project_id


def report(can_publish=True):
    failed = [] if can_publish else ['api.health']
    return {
        'schema_version': '1.0', 'project_id': 'gate-app', 'version': 1,
        'job_id': 'verification-job', 'attempt_id': 1,
        'spec_hash': 'a' * 64, 'source_hash': 'b' * 64,
        'status': 'passed' if can_publish else 'failed',
        'can_publish': can_publish, 'complete_coverage': True,
        'summary': {
            'total': 1, 'passed': int(can_publish), 'failed': int(not can_publish),
            'blocked': 0, 'skipped': 0,
            'required_failures': failed, 'optional_failures': [],
        },
        'started_at': '2026-01-01T00:00:00+00:00',
        'ended_at': '2026-01-01T00:00:01+00:00', 'duration_ms': 10,
        'checks': [{
            'id': 'build.production' if can_publish else 'api.health',
            'kind': 'build' if can_publish else 'api',
            'target': 'frontend/dist/index.html' if can_publish else '/api/health',
            'status': 'passed' if can_publish else 'failed', 'required': True,
            'mutates': False, 'tool_run_id': 'tool-1', 'duration_ms': 5,
            'output_ref': 'studio:frontend-build#ensure_frontend_build',
            **({} if can_publish else {'error': 'Health check failed'}),
        }],
    }


def fake_verifier(can_publish, calls, wait=None):
    async def verify(user_id, project_id, version, **kwargs):
        calls.append(kwargs)
        if wait is not None:
            await asyncio.to_thread(wait.wait)
        result = dict(report(can_publish))
        result['project_id'] = project_id
        result['version'] = version
        with workspace_db(user_id) as db:
            db.execute('INSERT OR REPLACE INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'verification', 'acceptance/report.json',
                        __import__('json').dumps(result), version))
        return result

    return verify


def test_failed_gate_preserves_existing_release(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', True)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'gate-failure')
        token = account['token']
        calls = []
        monkeypatch.setattr('app.api.verify_package', fake_verifier(True, calls))
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        response = client.post(f'/api/projects/{project_id}/architecture', headers=auth(token), json={
            'target_mode': 'fastapi', 'defer': False,
        })
        assert response.status_code == 200, response.text
        monkeypatch.setattr('app.api.verify_package', fake_verifier(False, calls))
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 409 and 'api.health' in response.text
        with control_db() as db:
            deployment = db.execute('SELECT published_version FROM deployment_registry WHERE project_id=?',
                                    (project_id,)).fetchone()
        assert deployment['published_version'] == 1
        assert client.get(f'/apps/{project_id}/').status_code == 200
        assert all(call['force'] is True for call in calls)


def test_successful_gate_and_idempotent_republish(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', True)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'gate-success')
        token = account['token']
        calls = []
        monkeypatch.setattr('app.api.verify_package', fake_verifier(True, calls))
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        assert len(calls) == 1


def test_publish_remains_legacy_when_gate_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', False)
    monkeypatch.setattr(settings, 'appspec_v1', False)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'gate-legacy', appspec=False)
        token = account['token']

        async def unexpected(*_args, **_kwargs):
            raise AssertionError('Flag-off publish must not run verification')

        monkeypatch.setattr('app.api.verify_package', unexpected)
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text


def test_gate_requires_a_valid_appspec(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', True)
    monkeypatch.setattr(settings, 'appspec_v1', False)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'gate-no-spec', appspec=False)
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(account['token']), json={})
        assert response.status_code == 409
        assert 'AppSpec' in response.text or 'acceptance manifest' in response.text


def test_verify_endpoint_sync_and_deferred(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', True)
    monkeypatch.setattr(settings, 'appspec_v1', True)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'gate-endpoint')
        token = account['token']
        calls = []
        monkeypatch.setattr('app.api.verify_package', fake_verifier(True, calls))
        response = client.post(f'/api/projects/{project_id}/verify', headers=auth(token), json={'defer': False})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['verification']['status'] == 'passed'
        assert payload['verification_running'] is False

        release = threading.Event()
        monkeypatch.setattr('app.api.verify_package', fake_verifier(True, calls, release))
        response = client.post(f'/api/projects/{project_id}/verify', headers=auth(token), json={'defer': True})
        assert response.status_code == 200, response.text
        assert response.json()['verification_running'] is True
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f'/api/projects/{project_id}/verification', headers=auth(token)).json()
            if not current['running'] and current['report']:
                break
            time.sleep(0.03)
        assert current['running'] is False
        assert current['report']['status'] == 'passed'

        async def failed_verification(*_args, **_kwargs):
            raise RuntimeError('Verifier unavailable')

        monkeypatch.setattr('app.api.verify_package', failed_verification)
        response = client.post(f'/api/projects/{project_id}/verify', headers=auth(token), json={'defer': True})
        assert response.status_code == 200, response.text
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = client.get(f'/api/projects/{project_id}', headers=auth(token)).json()
            if current['status'] == 'error':
                break
            time.sleep(0.03)
        assert current['status'] == 'error'
        assert current['verification_running'] is False
        assert current['messages'][-1]['role'] == 'agent'
        assert current['messages'][-1]['content'] == 'I hit a problem during verification: Verifier unavailable'


def test_verify_endpoint_rejects_disabled_flag(monkeypatch):
    monkeypatch.setattr(settings, 'acceptance_gate_v1', False)
    with TestClient(app) as client:
        account, project_id = build_version(client, 'gate-disabled', appspec=False)
        response = client.post(f'/api/projects/{project_id}/verify', headers=auth(account['token']), json={})
        assert response.status_code == 409
        assert 'not enabled' in response.text
