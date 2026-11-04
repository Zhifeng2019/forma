from fixtures.accounts import register_account
import time
import uuid
from urllib.parse import urlsplit

import jwt
import pytest
from fastapi.testclient import TestClient

from app.app_origins import application_origin, preview_url, published_url
from app.config import Settings
from app.database import control_db, workspace_db
from app.main import app
from app.security import _preview_key, decode_preview_token, decode_token


@pytest.fixture
def workspace():
    with TestClient(app) as client:
        account = register_account(client, json={
            'email': f'isolation-{uuid.uuid4().hex}@example.com', 'name': 'Isolation', 'password': 'password123',
        }).json()
        headers = {'Authorization': f'Bearer {account["token"]}'}
        project = client.post('/api/projects', headers=headers, json={
            'name': 'Isolated app', 'brief': 'A private application preview.',
            'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
        }).json()
        project_id = project['id']
        with workspace_db(account['user']['id']) as db:
            for version in (1, 2):
                db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                           (project_id, version, f'Version {version}', 'static', 'single-file'))
                db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (project_id, 'build', 'index.html', f'<html><body>Private version {version}</body></html>', version))
            db.execute("UPDATE projects SET current_version=2,stage='review' WHERE id=?", (project_id,))
        yield client, account, headers, project_id


def session(client, headers, project_id, version=1):
    response = client.post(f'/api/projects/{project_id}/preview-session?version={version}', headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    data = response.json()
    return data, data['url'].rstrip('/').rsplit('/', 1)[1]


def test_preview_grants_are_short_lived_and_cannot_authenticate_to_studio(workspace):
    client, account, headers, project_id = workspace
    data, token = session(client, headers, project_id)
    assert account['token'] not in str(data)
    assert 0 < data['expires_at'] - time.time() <= 15 * 60
    assert decode_preview_token(token, project_id, 1)['sub'] == str(account['user']['id'])
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token)
    assert client.get('/api/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401
    assert client.get(preview_url(project_id, 1, account['token'])).status_code == 401
    response = client.get(data['url'])
    assert response.status_code == 200 and 'Private version 1' in response.text
    assert account['token'] not in response.text
    assert 'set-cookie' not in response.headers
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert response.headers['origin-agent-cluster'] == '?1'
    assert 'http://127.0.0.1:5173' in response.headers['content-security-policy']


def test_preview_scope_expiration_and_account_revocation(workspace):
    client, account, headers, project_id = workspace
    data, token = session(client, headers, project_id)
    assert client.get(preview_url(project_id, 2, token)).status_code == 401
    assert client.get(preview_url('another-project', 1, token)).status_code == 401
    payload = decode_preview_token(token, project_id, 1)
    payload['exp'] = int(time.time()) - 1
    expired = jwt.encode(payload, _preview_key(), algorithm='HS256')
    assert client.get(preview_url(project_id, 1, expired)).status_code == 401
    # Assets and API calls must enforce expiry too, including before launching a runtime.
    for suffix in ('assets/app.js', 'api/health'):
        assert client.get(preview_url(project_id, 1, expired) + suffix).status_code == 401
    with control_db() as db:
        db.execute("UPDATE users SET status='disabled' WHERE id=?", (account['user']['id'],))
    assert client.get(data['url']).status_code == 401


def test_generated_hosts_cannot_serve_controls_or_other_applications(workspace):
    client, _account, headers, project_id = workspace
    data, _token = session(client, headers, project_id)
    client.post(f'/api/projects/{project_id}/publish', headers=headers, json={})
    origins = [data['origin'], application_origin(project_id), application_origin('other-project')]
    assert len({*origins, application_origin(project_id, 2), 'http://testserver'}) == 5
    for origin in origins:
        for path in ('/api/me', '/api/projects', '/api/health', '/', '/docs', '/openapi.json'):
            assert client.get(origin + path, headers=headers).status_code == 404
        assert client.post(origin + '/api/auth/login', json={}).status_code == 404
    preview_path = urlsplit(data['url']).path
    assert client.get('http://testserver' + preview_path).status_code == 404
    assert client.get(application_origin('other-project', 1) + preview_path).status_code == 404
    assert client.get(application_origin(project_id) + preview_path).status_code == 404
    assert client.get('http://unconfigured.example/api/health').status_code == 404
    assert client.get('http://unconfigured.example/api/health', headers={'X-Forwarded-Host': 'testserver'}).status_code == 404
    public = client.get(published_url(project_id))
    assert public.status_code == 200 and 'Private version 2' in public.text
    redirect = client.get(f'/apps/{project_id}/', follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers['location'] == published_url(project_id)
    assert 'Private version' not in redirect.text
    assert client.post(f'/apps/{project_id}/api/items', json={}).status_code == 404
    assert client.get(data['origin'] + f'/apps/{project_id}/').status_code == 404


def test_retired_query_tokens_and_cookies_never_serve_generated_content(workspace):
    client, account, headers, project_id = workspace
    for path in ('preview', 'assets/app.js', 'runtime/1/health'):
        response = client.get(f'/api/projects/{project_id}/{path}?access_token={account["token"]}', headers={
            **headers, 'Cookie': f'forma_preview={account["token"]}; forma_preview_version=1',
        })
        assert response.status_code == 404
    assert client.get(f'/api/projects/{project_id}/package?access_token={account["token"]}').status_code == 401
    assert client.post(f'/api/projects/{project_id}/preview-session').status_code == 401
    assert client.post(f'/api/projects/{project_id}/preview-session', headers={
        **headers, 'Origin': application_origin(project_id),
    }).status_code == 403
    assert client.post(f'/api/projects/{project_id}/preview-session', headers={
        **headers, 'Origin': 'http://127.0.0.1:5173',
    }).status_code == 200
    client.delete(f'/api/projects/{project_id}', headers=headers)
    assert client.post(f'/api/projects/{project_id}/preview-session', headers=headers).status_code == 404


@pytest.mark.parametrize('studio,cors,apps', [
    ('https://apps.example.com', 'https://studio.example.com', 'https://apps.example.com'),
    ('https://studio.apps.example.com', 'https://studio.example.com', 'https://apps.example.com'),
    ('https://studio.example.com', 'https://preview.apps.example.com', 'https://apps.example.com'),
    ('https://studio.example.com', '*', 'https://apps.example.com'),
    ('https://studio.example.com', 'https://studio.example.com', 'https://apps.example.com/path'),
    ('https://studio.example.com', 'https://studio.example.com', 'http://127.0.0.1:8000'),
])
def test_unsafe_host_configuration_fails_closed(studio, cors, apps):
    with pytest.raises(ValueError):
        Settings(studio_base_url=studio, cors_origins=cors, apps_base_url=apps)


def test_origins_match_browser_canonicalization():
    config = Settings(studio_base_url=' https://STUDIO.example.com:443/ ',
                      cors_origins='https://STUDIO.example.com:443/, http://localhost:80',
                      apps_base_url='https://APPS.example.net:443/')
    assert config.studio_base_url == 'https://studio.example.com'
    assert config.cors_origins == 'https://studio.example.com,http://localhost'
    assert config.apps_base_url == 'https://apps.example.net'
