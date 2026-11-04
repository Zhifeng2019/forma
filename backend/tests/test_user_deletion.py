"""Account erasure, live-work cleanup, and reuse of verified contacts."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import threading
import time
import uuid

import pytest

from app import api
from app.app_origins import preview_url
from app.config import settings
from app.database import control_db, init_databases, workspace_db
from app.deployment_registry import upsert_deployment
from app.jobs.service import create_job
from app.runtime import ManagedRuntime, runtime_manager
from app.security import create_preview_token, create_token
from fixtures.accounts import register_account
from test_registration import auth_system as deletion_system, details, start, verify

auth_system = deletion_system


def account(client):
    return register_account(client, json=details()).json()


def headers(account):
    return {'Authorization': f'Bearer {account["token"]}'}


def project(user_id):
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(id,name,brief,current_version,published_version,backend_mode)
            VALUES(?,?,?,1,1,'static')''', (project_id, 'Delete me', 'Private brief'))
        db.execute("INSERT INTO versions(project_id,version,label) VALUES(?,1,'First')", (project_id,))
        db.execute("INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,'build','index.html','<h1>Hosted</h1>',1)", (project_id,))
        db.execute("INSERT INTO messages(project_id,role,content) VALUES(?,'user','Private message')", (project_id,))
        db.execute("INSERT INTO events(project_id,message) VALUES(?,'Private event')", (project_id,))
        create_job(db, project_id, 'build', 'hash', 'build', 'trace')
    upsert_deployment(user_id, project_id)
    root = settings.data_path / 'projects' / project_id
    for relative in ('work/app.db', 'versions/v1/frontend/index.html', '.venv/private.txt', 'verification/report.json'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('private data')
    return project_id


def test_deletion_erases_owned_data_stops_jobs_and_hosting_only_for_target(auth_system):
    client, admin, _ = auth_system
    target, other = account(client), account(client)
    user_id = target['user']['id']
    projects = [project(user_id), project(user_id)]
    other_project = project(other['user']['id'])
    node = settings.data_path / 'node' / f'user_{user_id}'
    node.mkdir(parents=True)
    (node / 'private.txt').write_text('private build environment')
    with control_db() as db:
        private_provider = db.execute("INSERT INTO providers(name,base_url,model,owner_user_id) VALUES('private','https://example.com','model',?)", (user_id,)).lastrowid
        shared_provider = db.execute("INSERT INTO providers(name,base_url,model) VALUES('shared','https://example.com','model')").lastrowid
        db.execute('UPDATE preferences SET provider_id=? WHERE user_id=?', (private_provider, user_id))

    async def start_work():
        async def working():
            try:
                await asyncio.Event().wait()
            finally:
                # Cleanup must wait for task finalizers before erasing storage.
                (settings.data_path / 'projects' / projects[0] / 'finalizer.txt').write_text('finished')
        generation = api.schedule_generation(user_id, projects[0], working())
        verification = api.schedule_verification(user_id, projects[0], 1, working())
        process = await asyncio.create_subprocess_exec(sys.executable, '-c', 'import time; time.sleep(120)', start_new_session=True)
        reader = asyncio.create_task(process.wait())
        key = f'{projects[0]}:v1:public'
        runtime_manager._runtimes[key] = ManagedRuntime(key, projects[0], 1, 'public', process, 0, 'now', reader, time.monotonic())
        return generation, verification, process

    generation, verification, process = client.portal.call(start_work)
    preview, _ = create_preview_token(user_id, projects[0], 1, settings.studio_base_url)
    assert client.get(f'/apps/{projects[0]}/').status_code == 200
    response = client.delete(f'/api/admin/users/{user_id}', headers=admin)
    assert response.status_code == 200, response.text
    assert generation.cancelled() and verification.cancelled() and process.returncode is not None
    assert not any(value.project_id in projects for value in runtime_manager._runtimes.values())
    assert not (settings.data_path / 'users' / f'user_{user_id}.db').exists()
    assert not list((settings.data_path / 'users').glob(f'user_{user_id}.db*'))
    assert not node.exists()
    assert all(not (settings.data_path / 'projects' / pid).exists() for pid in projects)
    assert (settings.data_path / 'projects' / other_project / 'work/app.db').exists()
    with control_db() as db:
        for table, key in [('users', 'id'), ('preferences', 'user_id'), ('providers', 'owner_user_id'), ('deployment_registry', 'user_id')]:
            assert not db.execute(f'SELECT 1 FROM {table} WHERE {key}=?', (user_id,)).fetchone()
        assert db.execute('SELECT 1 FROM providers WHERE id=?', (shared_provider,)).fetchone()
    assert client.get('/api/me', headers=headers(target)).status_code == 401
    assert client.get(preview_url(projects[0], 1, preview)).status_code == 401
    assert client.get(f'/apps/{projects[0]}/').status_code == 404
    assert client.get(f'/apps/{other_project}/').status_code == 200
    with pytest.raises(sqlite3.OperationalError), workspace_db(user_id):
        pass
    assert not (settings.data_path / 'users' / f'user_{user_id}.db').exists()


@pytest.mark.parametrize('channel,status', [('email', 'active'), ('sms', 'pending'), ('email', 'rejected'), ('sms', 'disabled')])
def test_contact_can_register_again_with_new_id_and_fresh_approval(auth_system, channel, status):
    client, admin, messages = auth_system
    phone = '13800138001' if status == 'pending' else '13800138002'
    body = details() if channel == 'email' else details(email=None, phone=phone)
    challenge = start(client, body)
    assert verify(client, challenge, messages).status_code == 200
    contact = body['email'] if channel == 'email' else '+86' + phone
    with control_db() as db:
        target = db.execute('SELECT id FROM users WHERE email=? OR phone=?', (contact, contact)).fetchone()['id']
        db.execute('UPDATE users SET status=? WHERE id=?', (status, target))
    token = create_token(target)
    assert client.delete(f'/api/admin/users/{target}', headers=admin).status_code == 200
    # No cooldown inherited from the erased registration; still uses a new verification code.
    new_challenge = start(client, body)
    assert new_challenge != challenge
    assert verify(client, challenge, messages).status_code == 400
    assert verify(client, new_challenge, messages).status_code == 200
    with control_db() as db:
        new_user = db.execute('SELECT id,status FROM users WHERE email=? OR phone=?', (contact, contact)).fetchone()
        assert new_user['id'] > target and new_user['status'] == 'pending'
    assert client.post('/api/auth/login', json={'identifier': contact, 'password': body['password']}).status_code == 403
    assert client.get('/api/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401


def test_delete_requires_admin_and_cannot_delete_self(auth_system):
    client, admin, _ = auth_system
    target = account(client)
    endpoint = f'/api/admin/users/{target["user"]["id"]}'
    assert client.delete(endpoint).status_code == 401
    assert client.delete(endpoint, headers=headers(target)).status_code == 403
    assert client.delete('/api/admin/users/1', headers=admin).status_code == 400
    assert client.delete('/api/admin/users/99999999', headers=admin).status_code == 404
    assert client.get('/api/me', headers=headers(target)).status_code == 200


def test_failed_cleanup_is_blocked_and_retryable(auth_system, monkeypatch):
    client, admin, _ = auth_system
    target = account(client)
    user_id = target['user']['id']
    project_id = project(user_id)
    original = runtime_manager.remove_project

    async def failure(_project_id):
        raise OSError('filesystem unavailable')

    monkeypatch.setattr(runtime_manager, 'remove_project', failure)
    endpoint = f'/api/admin/users/{user_id}'
    assert client.delete(endpoint, headers=admin).status_code == 503
    assert client.get('/api/me', headers=headers(target)).status_code == 401
    assert client.get(f'/apps/{project_id}/').status_code == 404
    assert client.patch(endpoint, headers=admin, json={'status': 'active'}).status_code == 409
    users = client.get('/api/admin/users', headers=admin).json()
    assert next(user for user in users if user['id'] == user_id)['status'] == 'deleting'
    monkeypatch.setattr(runtime_manager, 'remove_project', original)
    assert client.delete(endpoint, headers=admin).status_code == 200
    assert not (settings.data_path / 'projects' / project_id).exists()


def test_deletion_drains_inflight_project_creation(auth_system, monkeypatch):
    client, admin, _ = auth_system
    target = account(client)
    started, finished = threading.Event(), threading.Event()

    async def generate(user_id, project_id, _provider):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(.01)
            with workspace_db(user_id) as db:
                db.execute("UPDATE projects SET status='error' WHERE id=?", (project_id,))
            finished.set()

    monkeypatch.setattr(api, 'generate_stage', generate)
    with ThreadPoolExecutor(max_workers=1) as executor:
        creating = executor.submit(client.post, '/api/projects', headers=headers(target), json={
            'name': 'In flight', 'brief': 'A project being created during deletion', 'defer': False,
        })
        assert started.wait(5)
        response = client.delete(f'/api/admin/users/{target["user"]["id"]}', headers=admin)
        assert response.status_code == 200, response.text
        assert finished.is_set()
        assert creating.result(timeout=5).status_code == 401
    assert not (settings.data_path / 'users' / f'user_{target["user"]["id"]}.db').exists()


def test_legacy_user_table_cannot_reuse_deleted_session_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', str(tmp_path))
    with control_db() as db:
        db.executescript('''CREATE TABLE users (
            id INTEGER PRIMARY KEY, email TEXT UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user', status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO users(id,email,name,password_hash) VALUES(41,'legacy@example.com','Legacy','hash');''')
    init_databases()
    with control_db() as db:
        db.execute('DELETE FROM users WHERE id=41')
        new_id = db.execute("INSERT INTO users(email,name,password_hash) VALUES('legacy@example.com','New','hash')").lastrowid
        assert new_id > 41
