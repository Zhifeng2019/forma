import uuid

from fastapi.testclient import TestClient

from app.database import backfill_deployment_registry, control_db
from app.main import app


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def register(client, label):
    response = client.post('/api/auth/register', json={
        'email': f'{label}-{uuid.uuid4().hex}@example.com',
        'name': 'Deployment Tester', 'password': 'password123',
    })
    assert response.status_code == 200, response.text
    return response.json()


def build_and_publish(client, label):
    account = register(client, label)
    token = account['token']
    response = client.post('/api/projects', headers=auth(token), json={
        'name': 'Registry App', 'brief': 'A portable application with versioned deployments.',
        'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
    })
    assert response.status_code == 200, response.text
    project = response.json()
    project_id = project['id']
    for _ in range(3):
        response = client.post(f'/api/projects/{project_id}/advance', headers=auth(token), json={})
        assert response.status_code == 200, response.text
    assert response.json()['current_version'] == 1
    response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
    assert response.status_code == 200, response.text
    return account, project_id


def registry_row(project_id):
    with control_db() as db:
        row = db.execute('SELECT * FROM deployment_registry WHERE project_id=?', (project_id,)).fetchone()
    return dict(row) if row else None


def test_publish_unpublish_and_delete_are_write_through():
    with TestClient(app) as client:
        account, project_id = build_and_publish(client, 'write-through')
        token = account['token']
        row = registry_row(project_id)
        assert row['user_id'] == account['user']['id']
        assert row['published_version'] == 1
        assert row['backend_mode'] == 'static' and row['source_format'] == 'single-file'
        assert client.post(f'/api/projects/{project_id}/unpublish', headers=auth(token)).status_code == 200
        assert registry_row(project_id) is None
        assert client.get(f'/apps/{project_id}/').status_code == 404
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        assert registry_row(project_id)['published_version'] == 1
        assert client.get(f'/apps/{project_id}/').status_code == 200
        assert client.delete(f'/api/projects/{project_id}', headers=auth(token)).status_code == 200
        assert registry_row(project_id) is None
        assert client.get(f'/apps/{project_id}/').status_code == 404


def test_public_lookup_uses_registry_without_workspace_scan(monkeypatch):
    with TestClient(app) as client:
        _account, project_id = build_and_publish(client, 'registry-lookup')

        def forbidden_scan(*_args, **_kwargs):
            raise AssertionError('Public lookup must not scan workspace databases')

        monkeypatch.setattr('app.main.workspace_db', forbidden_scan, raising=False)
        response = client.get(f'/apps/{project_id}/')
        assert response.status_code == 200 and 'Registry App' in response.text
        assert client.get('/apps/does-not-exist/').status_code == 404


def test_backfill_restores_and_updates_version_metadata():
    with TestClient(app) as client:
        account, project_id = build_and_publish(client, 'registry-backfill')
        with control_db() as db:
            db.execute('DELETE FROM deployment_registry WHERE project_id=?', (project_id,))
            db.execute('''INSERT INTO deployment_registry(
                project_id,user_id,published_version,backend_mode,source_format,runtime_metadata)
                VALUES(?,?,?,?,?,?)''', (project_id, account['user']['id'], 99, 'fastapi', 'multi-file', '{}'))
        backfill_deployment_registry(account['user']['id'])
        row = registry_row(project_id)
        assert row['published_version'] == 1
        assert row['backend_mode'] == 'static' and row['source_format'] == 'single-file'
        assert client.get(f'/apps/{project_id}/').status_code == 200


def test_migration_and_republish_preserve_version_specific_registry():
    with TestClient(app) as client:
        account, project_id = build_and_publish(client, 'registry-migration')
        token = account['token']
        response = client.post(f'/api/projects/{project_id}/architecture', headers=auth(token), json={
            'target_mode': 'fastapi', 'defer': False,
        })
        assert response.status_code == 200, response.text
        row = registry_row(project_id)
        assert row['published_version'] == 1 and row['backend_mode'] == 'static'
        assert client.get(f'/apps/{project_id}/api/health').status_code == 404
        response = client.post(f'/api/projects/{project_id}/publish', headers=auth(token), json={})
        assert response.status_code == 200, response.text
        row = registry_row(project_id)
        assert row['published_version'] == 2 and row['backend_mode'] == 'fastapi'
        response = client.get(f'/apps/{project_id}/api/health')
        assert response.status_code == 200, response.text
