"""Policy enforcement through the same APIs used by the studio and public apps."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import uuid

from fastapi.testclient import TestClient
import pytest

from app.database import backfill_deployment_registry, control_db, init_databases, workspace_db
from app.deployment_registry import get_deployment, upsert_deployment
from app.engine import provider_for_user
from app.hosting import stop_expired_hosting
from app.main import app
from app.policy import hosting_expired

DEFAULT_POLICY = {
    'allow_user_llm_config': True, 'global_provider_id': None,
    'max_projects_per_user': 5, 'hosting_duration_hours': 1,
}
PROVIDER = {'name': 'Policy provider', 'base_url': 'https://provider.example/v1',
            'model': 'test-model', 'api_key': 'private-test-key'}
PROJECT = {'name': 'Policy app', 'brief': 'A simple app to exercise studio policy.', 'backend_mode': 'static'}


def auth(account):
    return {'Authorization': f'Bearer {account["token"]}'}


def register(client):
    response = client.post('/api/auth/register', json={
        'email': f'policy-{uuid.uuid4().hex}@example.com', 'name': 'Policy User', 'password': 'password123',
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def studio(monkeypatch):
    with control_db() as db:
        previous = dict(db.execute('SELECT * FROM studio_policy WHERE id=1').fetchone())
        db.execute('''UPDATE studio_policy SET allow_user_llm_config=1,global_provider_id=NULL,
            max_projects_per_user=5,hosting_duration_hours=1 WHERE id=1''')
    generator = AsyncMock()
    monkeypatch.setattr('app.api.generate_stage', generator)
    with TestClient(app) as client:
        admin = client.post('/api/auth/login', json={'email': 'admin@forma.local', 'password': 'admin123'}).json()
        yield client, admin, register(client), generator
    with control_db() as db:
        db.execute('''UPDATE studio_policy SET allow_user_llm_config=?,global_provider_id=?,
            max_projects_per_user=?,hosting_duration_hours=? WHERE id=1''', (
                previous['allow_user_llm_config'], previous['global_provider_id'],
                previous['max_projects_per_user'], previous['hosting_duration_hours'],
            ))


def set_policy(client, admin, **changes):
    response = client.put('/api/admin/policy', headers=auth(admin), json={**DEFAULT_POLICY, **changes})
    assert response.status_code == 200, response.text
    return response.json()


def add_provider(client, account, **changes):
    response = client.post('/api/providers', headers=auth(account), json={**PROVIDER, **changes})
    assert response.status_code == 200, response.text
    return response.json()['id']


def build_project(client, account):
    response = client.post('/api/projects', headers=auth(account), json=PROJECT)
    assert response.status_code == 200, response.text
    project_id = response.json()['id']
    with workspace_db(account['user']['id']) as db:
        db.execute('UPDATE projects SET current_version=1 WHERE id=?', (project_id,))
        db.execute("INSERT INTO versions(project_id,version,label) VALUES(?,1,'Test release')", (project_id,))
        db.execute("INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,'build','index.html','<html>Hosted app</html>',1)", (project_id,))
    return project_id


def publish(client, account, project_id):
    response = client.post(f'/api/projects/{project_id}/publish', headers=auth(account), json={})
    assert response.status_code == 200, response.text
    return response.json()


def expire(account, project_id):
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with workspace_db(account['user']['id']) as db:
        db.execute('UPDATE projects SET hosting_expires_at=? WHERE id=?', (past, project_id))
    upsert_deployment(account['user']['id'], project_id)
    return past


def test_defaults_permissions_and_policy_validation(studio):
    client, admin, user, _ = studio
    assert client.get('/api/policy', headers=auth(user)).json() == DEFAULT_POLICY
    assert client.get('/api/policy').status_code == 401
    assert client.put('/api/admin/policy', headers=auth(user), json=DEFAULT_POLICY).status_code == 403
    for field, value in [('max_projects_per_user', 0), ('max_projects_per_user', 1.5),
                         ('hosting_duration_hours', 0), ('hosting_duration_hours', 8761),
                         ('hosting_duration_hours', 1.5)]:
        result = client.put('/api/admin/policy', headers=auth(admin), json={**DEFAULT_POLICY, field: value})
        assert result.status_code == 422, result.text
    assert set_policy(client, admin, hosting_duration_hours=8760)['hosting_duration_hours'] == 8760
    init_databases()
    assert client.get('/api/policy', headers=auth(user)).json()['hosting_duration_hours'] == 8760
    for provider_id in [999999, add_provider(client, admin, enabled=False), add_provider(client, user)]:
        assert client.put('/api/admin/policy', headers=auth(admin), json={**DEFAULT_POLICY, 'global_provider_id': provider_id}).status_code == 400


def test_private_provider_ownership_and_credentials(studio):
    client, admin, user, _ = studio
    other = register(client)
    own_id = add_provider(client, user)
    shared_id = add_provider(client, admin)
    own = next(p for p in client.get('/api/providers', headers=auth(user)).json() if p['id'] == own_id)
    assert own['can_manage'] and own['has_key'] and own['owner_user_id'] == user['user']['id']
    assert 'api_key' not in own and 'api_key_encrypted' not in own
    for account in (other, admin):
        assert own_id not in [p['id'] for p in client.get('/api/providers', headers=auth(account)).json()]
        assert client.put(f'/api/providers/{own_id}', headers=auth(account), json=PROVIDER).status_code == 404
        assert client.delete(f'/api/providers/{own_id}', headers=auth(account)).status_code == 404
        assert client.post(f'/api/providers/{own_id}/test', headers=auth(account)).status_code == 404
        assert client.put('/api/preferences', headers=auth(account), json={'provider_id': own_id}).status_code == 400
    assert client.put(f'/api/providers/{shared_id}', headers=auth(user), json=PROVIDER).status_code == 404
    assert client.delete(f'/api/providers/{shared_id}', headers=auth(user)).status_code == 404
    assert client.put('/api/preferences', headers=auth(user), json={'provider_id': own_id}).status_code == 200
    with control_db() as db:
        encrypted = db.execute('SELECT api_key_encrypted FROM providers WHERE id=?', (own_id,)).fetchone()[0]
        assert encrypted != PROVIDER['api_key']
        assert provider_for_user(db, user['user']['id'])['id'] == own_id
    assert client.put(f'/api/providers/{own_id}', headers=auth(user), json={**PROVIDER, 'api_key': '', 'model': 'updated-model'}).status_code == 200
    with control_db() as db:
        assert db.execute('SELECT api_key_encrypted FROM providers WHERE id=?', (own_id,)).fetchone()[0] == encrypted
    assert client.put(f'/api/providers/{own_id}', headers=auth(user), json={**PROVIDER, 'enabled': False}).status_code == 200
    assert client.get('/api/preferences', headers=auth(user)).json()['provider_id'] is None
    assert client.delete(f'/api/providers/{own_id}', headers=auth(user)).status_code == 200
    assert client.get('/api/preferences', headers=auth(user)).json()['provider_id'] is None


def test_managed_model_overrides_old_preferences_and_cannot_be_bypassed(studio):
    client, admin, user, generator = studio
    own_id = add_provider(client, user)
    global_id = add_provider(client, admin)
    client.put('/api/preferences', headers=auth(user), json={'provider_id': own_id})
    set_policy(client, admin, allow_user_llm_config=False, global_provider_id=global_id)
    pref = client.get('/api/preferences', headers=auth(user)).json()
    assert pref['provider_id'] == global_id and not pref['can_configure_llm']
    assert [p['id'] for p in client.get('/api/providers', headers=auth(user)).json()] == [global_id]
    for provider_id in (own_id, global_id, None):
        assert client.put('/api/preferences', headers=auth(user), json={'provider_id': provider_id}).status_code == 403
    assert client.post('/api/providers', headers=auth(user), json=PROVIDER).status_code == 403
    assert client.put(f'/api/providers/{own_id}', headers=auth(user), json=PROVIDER).status_code == 403
    assert client.delete(f'/api/providers/{own_id}', headers=auth(user)).status_code == 403
    assert client.post(f'/api/providers/{own_id}/test', headers=auth(user)).status_code == 403
    response = client.put('/api/preferences', headers=auth(user), json={'auto_mode': True, 'theme': 'dark'})
    assert response.status_code == 200 and response.json()['provider_id'] == global_id
    assert client.post('/api/projects', headers=auth(user), json=PROJECT).status_code == 200
    assert generator.await_args.args[2]['id'] == global_id
    # Admin accounts still select their own engine; protected global providers cannot disappear.
    assert client.put('/api/preferences', headers=auth(admin), json={'provider_id': None}).status_code == 200
    assert client.delete(f'/api/providers/{global_id}', headers=auth(admin)).status_code == 409
    assert client.put(f'/api/providers/{global_id}', headers=auth(admin), json={**PROVIDER, 'enabled': False}).status_code == 409
    set_policy(client, admin)
    assert client.get('/api/preferences', headers=auth(user)).json()['provider_id'] == own_id
    assert client.post('/api/projects', headers=auth(user), json=PROJECT).status_code == 200
    assert generator.await_args.args[2]['id'] == own_id


def test_project_quota_is_atomic_and_deletion_frees_a_slot(studio):
    client, admin, user, _ = studio
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post('/api/projects', headers=auth(user), json=PROJECT), range(8)))
    assert sorted(r.status_code for r in responses) == [200] * 5 + [409] * 3
    projects = client.get('/api/projects', headers=auth(user)).json()
    assert len(projects) == 5
    assert client.delete(f'/api/projects/{projects[0]["id"]}', headers=auth(user)).status_code == 200
    assert client.post('/api/projects', headers=auth(user), json=PROJECT).status_code == 200
    set_policy(client, admin, max_projects_per_user=2)
    assert len(client.get('/api/projects', headers=auth(user)).json()) == 5
    assert client.post('/api/projects', headers=auth(user), json=PROJECT).status_code == 409
    another = register(client)
    assert client.post('/api/projects', headers=auth(another), json=PROJECT).status_code == 200
    set_policy(client, admin, max_projects_per_user=6)
    assert client.post('/api/projects', headers=auth(user), json=PROJECT).status_code == 200


def test_hosting_deadline_blocks_all_public_routes_and_can_be_renewed(studio, monkeypatch):
    client, admin, user, _ = studio
    project_id = build_project(client, user)
    published = publish(client, user, project_id)
    expires = datetime.fromisoformat(published['hosting_expires_at'])
    assert 3590 < (expires - datetime.now(timezone.utc)).total_seconds() <= 3600
    public_url = published['published_url']
    assert client.get(public_url).status_code == 200
    assert client.get(public_url).headers['cache-control'] == 'no-store'
    past = expire(user, project_id)
    # The request-time check does not depend on the background reaper running.
    for suffix in ['', 'assets/main.js', 'api/health']:
        assert client.get(public_url + suffix).status_code == 410
    assert client.post(public_url + 'api/items', json={}).status_code == 410
    detail = client.get(f'/api/projects/{project_id}', headers=auth(user)).json()
    assert detail['hosting_expired'] and detail['published_url'] is None
    assert client.get('/api/projects', headers=auth(user)).json()[0]['hosting_expired']
    stop = AsyncMock()
    monkeypatch.setattr('app.hosting.runtime_manager.stop_project', stop)
    async def expire_during_generation():
        from app.api import project_lock
        async with project_lock(project_id):
            await asyncio.wait_for(stop_expired_hosting(), timeout=1)
    asyncio.run(expire_during_generation())
    stop.assert_any_await(project_id, channel='public')
    # Backfilling and policy changes must never renew an expired release.
    set_policy(client, admin, hosting_duration_hours=8760)
    backfill_deployment_registry(user['user']['id'])
    assert get_deployment(project_id)['hosting_expires_at'] == past
    assert client.get(public_url).status_code == 410
    renewed = publish(client, user, project_id)
    assert not renewed['hosting_expired']
    assert 8760 * 3600 - 10 < (datetime.fromisoformat(renewed['hosting_expires_at']) - datetime.now(timezone.utc)).total_seconds() <= 8760 * 3600
    assert client.get(public_url).status_code == 200
    assert client.post(f'/api/projects/{project_id}/unpublish', headers=auth(user)).status_code == 200
    assert get_deployment(project_id) is None
    with workspace_db(user['user']['id']) as db:
        assert db.execute('SELECT hosting_expires_at FROM projects WHERE id=?', (project_id,)).fetchone()[0] is None


def test_legacy_release_gets_one_deadline_and_restart_preserves_it(studio):
    client, admin, user, _ = studio
    project_id = build_project(client, user)
    with workspace_db(user['user']['id']) as db:
        db.execute('UPDATE projects SET published_version=1 WHERE id=?', (project_id,))
    init_databases()
    first = get_deployment(project_id)['hosting_expires_at']
    assert first and not hosting_expired(first)
    set_policy(client, admin, hosting_duration_hours=48)
    init_databases()
    assert get_deployment(project_id)['hosting_expires_at'] == first
    past = expire(user, project_id)
    init_databases()
    assert get_deployment(project_id)['hosting_expires_at'] == past
    assert client.get(f'/apps/{project_id}/').status_code == 410


def test_pre_policy_database_schema_is_migrated_in_place(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'data_dir', str(tmp_path))
    with control_db() as db:
        db.executescript('''
            CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, name TEXT, password_hash TEXT,
                role TEXT, status TEXT DEFAULT 'active', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO users(id,email,name,password_hash,role) VALUES(1,'legacy@example.com','Legacy','unused','user');
            CREATE TABLE providers (id INTEGER PRIMARY KEY, name TEXT, base_url TEXT, model TEXT,
                api_key_encrypted TEXT, enabled INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO providers VALUES(7,'Existing model','https://legacy.example/v1','legacy-model','encrypted-key',1,'2026-01-01');
            CREATE TABLE preferences (user_id INTEGER PRIMARY KEY, provider_id INTEGER, auto_mode INTEGER DEFAULT 0,
                theme TEXT DEFAULT 'light', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO preferences(user_id,provider_id) VALUES(1,7);
            CREATE TABLE deployment_registry (project_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                published_version INTEGER NOT NULL, backend_mode TEXT NOT NULL, source_format TEXT NOT NULL,
                runtime_metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
    project_id = uuid.uuid4().hex
    with workspace_db(1) as db:
        db.executescript('''CREATE TABLE projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, brief TEXT NOT NULL, description TEXT DEFAULT '',
            stage TEXT DEFAULT 'deploy', stage_index INTEGER DEFAULT 5, phase_index INTEGER DEFAULT 1,
            status TEXT DEFAULT 'ready', auto_mode INTEGER DEFAULT 0, published_version INTEGER,
            current_version INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')
        db.execute("INSERT INTO projects(id,name,brief,published_version) VALUES(?,'Legacy release','Preserve me',1)", (project_id,))
    init_databases()
    with control_db() as db:
        assert provider_for_user(db, 1)['model'] == 'legacy-model'
        assert provider_for_user(db, 1)['owner_user_id'] is None
        assert provider_for_user(db, 1)['api_key_encrypted'] == 'encrypted-key'
        assert dict(db.execute('SELECT * FROM studio_policy').fetchone()) == {'id': 1, **DEFAULT_POLICY}
    deadline = get_deployment(project_id)['hosting_expires_at']
    assert deadline and not hosting_expired(deadline)
    init_databases()
    assert get_deployment(project_id)['hosting_expires_at'] == deadline
