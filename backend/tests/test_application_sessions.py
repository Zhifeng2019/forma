import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import runtime_response
from app.app_origins import application_origin, published_url
from app.application_auth import application_cookie
from app.config import ROOT, settings
from app.main import app
from fixtures.cookie_application import install_cookie_application


@pytest.mark.parametrize('preview', [False, True])
def test_cookie_scope_preserves_values_expiry_flags_and_individual_headers(preview):
    values = [
        'session="quoted\\\";value"; Domain=.apps.localhost; Path=/api/auth; HttpOnly; SameSite=Strict; Priority=High',
        'csrf=abc; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; domain=apps.localhost; path=/api',
        '__Host-special=value; Secure; Path=/; Partitioned; SameSite=None',
    ]
    upstream = httpx.Response(200, headers=[('set-cookie', value) for value in values], json={'ok': True})
    response = runtime_response(upstream, 'preview' if preview else 'public')
    cookies = response.headers.getlist('set-cookie')
    assert len(cookies) == 3
    assert 'session="quoted\\\";value"' in cookies[0]
    assert 'HttpOnly' in cookies[0] and 'Priority=High' in cookies[0]
    assert 'Max-Age=0' in cookies[1] and 'Expires=Thu, 01 Jan 1970 00:00:00 GMT' in cookies[1]
    assert all('domain=' not in cookie.lower() and 'Path=/' in cookie for cookie in cookies)
    assert all('/api' not in cookie for cookie in cookies)
    if preview:
        assert all('Secure' in cookie and 'SameSite=None' in cookie and 'Partitioned' in cookie for cookie in cookies)
    else:
        assert 'SameSite=Strict' in cookies[0] and 'Partitioned' not in cookies[0]
    assert 'Secure' in application_cookie('session=abc; HttpOnly', preview=False, https=True)


@pytest.mark.parametrize('cookie', ['invalid name=abc', 'invalid', 'x="unterminated', 'x=abc\r\nSet-Cookie: other=x'])
def test_malformed_cookies_are_not_forwarded(cookie):
    assert application_cookie(cookie, preview=True, https=True) is None


def create_cookie_project(client):
    account = client.post('/api/auth/register', json={
        'email': f'cookies-{uuid.uuid4().hex}@example.com', 'name': 'Cookie Owner', 'password': 'password123',
    }).json()
    headers = {'Authorization': f'Bearer {account["token"]}'}
    project = client.post('/api/projects', headers=headers, json={
        'name': 'Cookie application', 'brief': 'A private cookie session test.',
        'backend_mode': 'static', 'source_format': 'single-file', 'auto_mode': False,
    }).json()
    install_cookie_application(account['user']['id'], project['id'])
    return account, headers, project['id']


def test_cookie_login_renewal_csrf_and_logout_through_private_and_public_proxies(monkeypatch):
    # HTTPX follows the standard Secure-cookie rule; the browser test below also checks localhost.
    monkeypatch.setattr(settings, 'apps_base_url', 'https://apps.example.net')
    with TestClient(app) as client:
        _account, headers, pid = create_cookie_project(client)
        client.cookies.set('studio_session', 'studio-only', domain='testserver.local', path='/')
        preview = client.post(f'/api/projects/{pid}/preview-session', headers=headers).json()['url']
        assert client.get(preview + 'api/auth/me').status_code == 401
        login = client.post(preview + 'api/auth/login')
        assert login.status_code == 200, login.text
        assert len(login.headers.get_list('set-cookie')) == 2
        assert client.get(preview + 'api/auth/me').json() == {
            'role': 'admin', 'studio_cookie': None, 'authorization': None,
        }
        assert client.post(preview + 'api/auth/touch').status_code == 403
        assert client.post(preview + 'api/auth/touch', headers={'X-CSRFToken': 'fixture-csrf'}).status_code == 200
        renewed = client.post(f'/api/projects/{pid}/preview-session', headers={
            **headers, 'Origin': 'http://127.0.0.1:5173',
        }).json()['url']
        assert renewed != preview
        assert client.get(renewed + 'api/auth/me').status_code == 200
        assert client.post(f'/api/projects/{pid}/publish', headers=headers, json={}).status_code == 200
        public = published_url(pid)
        assert client.get(public + 'api/auth/me').status_code == 401
        assert client.post(public + 'api/auth/login').status_code == 200
        assert client.get(public + 'api/auth/me').status_code == 200
        assert client.post(public + 'api/auth/logout').status_code == 200
        assert client.get(public + 'api/auth/me').status_code == 401
        assert client.get(renewed + 'api/auth/me').status_code == 200
        assert 'cookie' not in client.build_request('GET', application_origin('other-project') + '/').headers
        assert client.post(renewed + 'api/auth/logout').status_code == 200
        assert client.get(renewed + 'api/auth/me').status_code == 401


def test_cookie_sessions_work_in_a_real_isolated_iframe_and_public_page(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node and Playwright are required for cookie browser verification')
    with TestClient(app) as client:
        account, headers, pid = create_cookie_project(client)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'STUDIO_BASE_URL': base, 'APPS_BASE_URL': f'http://apps.localhost:{port}',
           'CORS_ORIGINS': base, 'DATA_DIR': str(settings.data_path), 'SANDBOX_V1': 'false'}
    with (tmp_path / 'server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=base, headers=headers, trust_env=False, timeout=10) as api:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        if api.get('/api/health').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail((tmp_path / 'server.log').read_text())
                preview = api.post(f'/api/projects/{pid}/preview-session').json()['url']
                public = api.post(f'/api/projects/{pid}/publish', json={}).json()['published_url']
            browser_env = {**env, 'COOKIE_TEST': json.dumps({
                'base': base, 'projectId': pid, 'token': account['token'], 'preview': preview, 'public': public,
            }), 'FRONTEND_PACKAGE': str(ROOT.parent / 'frontend' / 'package.json')}
            result = subprocess.run([node, str(Path(__file__).parent / 'fixtures' / 'cookie_browser.mjs')],
                                    cwd=ROOT.parent / 'frontend', env=browser_env, capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stdout + result.stderr + '\n' + (tmp_path / 'server.log').read_text()[-3000:]
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
