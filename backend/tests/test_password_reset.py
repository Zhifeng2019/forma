"""Password recovery uses mocked delivery and isolated accounts only."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import httpx
import jwt
import pytest

from app.api import auth_payload
from app.authentication import delivery, password_reset
from app.config import settings
from app.database import control_db, workspace_db
from app.jobs.events import follow_frames
from app.security import create_preview_token, decode_preview_token, decrypt_secret, verify_password
from fixtures.accounts import register_account
from test_registration import auth_system as reset_system, details, start as start_registration

auth_system = reset_system
NEW_PASSWORD = 'new-secure-password-123'


def member(client, channel='email'):
    body = details()
    account = register_account(client, json=body).json()
    if channel == 'sms':
        phone = '138' + f'{int(uuid.uuid4().hex[:8], 16) % 100_000_000:08d}'
        with control_db() as db:
            db.execute('UPDATE users SET email=NULL,phone=? WHERE id=?', ('+86' + phone, account['user']['id']))
        contact = {'phone': '0086 ' + phone}
        identifier = '+86' + phone
    else:
        contact = {'email': body['email'].upper()}
        identifier = body['email']
    return account, contact, identifier, body['password']


def start(client, contact):
    response = client.post('/api/auth/password-reset', json=contact)
    assert response.status_code == 200, response.text
    assert not {'code', 'token', 'user_id'} & response.json().keys()
    return response.json()['challenge_id']


def confirm(client, challenge, messages, password=NEW_PASSWORD):
    return client.post('/api/auth/password-reset/confirm', json={
        'challenge_id': challenge, 'code': messages[challenge]['code'], 'password': password,
    })


@pytest.mark.parametrize('channel', ['email', 'sms'])
def test_reset_changes_password_and_invalidates_old_sessions(auth_system, channel):
    client, admin, messages = auth_system
    account, contact, identifier, old_password = member(client, channel)
    user_id = account['user']['id']
    project_id = uuid.uuid4().hex
    preview, _ = create_preview_token(user_id, project_id, 1, settings.studio_base_url)
    with control_db() as db:
        before = dict(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())
    now = datetime.now(timezone.utc)
    legacy_token = jwt.encode({'sub': str(user_id), 'iat': now, 'exp': now + timedelta(hours=1)}, settings.secret_key, algorithm='HS256')
    challenge = start(client, contact)
    assert messages[challenge]['purpose'] == 'password_reset'
    with control_db() as db:
        row = dict(db.execute('SELECT * FROM password_reset_challenges WHERE id=?', (challenge,)).fetchone())
        assert row['code_hash'] != messages[challenge]['code']
        assert decrypt_secret(row['destination_encrypted']) == identifier
        assert 'password' not in row and 'destination' not in row
        assert db.execute('SELECT password_hash FROM users WHERE id=?', (user_id,)).fetchone()[0] == before['password_hash']
    assert confirm(client, challenge, messages).json()['status'] == 'password_reset'
    assert confirm(client, challenge, messages).status_code == 400
    assert client.post('/api/auth/login', json={'identifier': identifier, 'password': old_password}).status_code == 401
    login = client.post('/api/auth/login', json={'identifier': identifier, 'password': NEW_PASSWORD})
    assert login.status_code == 200
    for token in (account['token'], legacy_token, auth_payload(before)['token']):
        assert client.get('/api/me', headers={'Authorization': f'Bearer {token}'}).status_code == 401
    assert client.get('/api/me', headers={'Authorization': f'Bearer {login.json()["token"]}'}).status_code == 200
    assert client.get('/api/me', headers=admin).status_code == 200
    with pytest.raises(jwt.InvalidTokenError):
        decode_preview_token(preview, project_id, 1)
    with control_db() as db:
        user = dict(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())
        assert user['session_version'] == before['session_version'] + 1
        assert all(user[key] == before[key] for key in ('role', 'status', 'verified_at', 'reviewed_at', 'reviewed_by'))
        assert verify_password(NEW_PASSWORD, user['password_hash'])
        assert not db.execute('SELECT 1 FROM password_reset_challenges WHERE user_id=?', (user_id,)).fetchone()


@pytest.mark.parametrize('status', ['pending', 'rejected', 'disabled'])
def test_reset_never_bypasses_admin_approval_or_reactivates_accounts(auth_system, status):
    client, _, messages = auth_system
    account, contact, identifier, _ = member(client)
    with control_db() as db:
        db.execute('UPDATE users SET status=? WHERE id=?', (status, account['user']['id']))
    challenge = start(client, contact)
    assert confirm(client, challenge, messages).status_code == 200
    assert client.post('/api/auth/login', json={'identifier': identifier, 'password': NEW_PASSWORD}).status_code == 403
    with control_db() as db:
        assert db.execute('SELECT status FROM users WHERE id=?', (account['user']['id'],)).fetchone()[0] == status


def test_unknown_contact_has_same_response_but_no_delivery_or_reset(auth_system):
    client, _, messages = auth_system
    _, contact, _, _ = member(client)
    known = client.post('/api/auth/password-reset', json=contact)
    unknown = client.post('/api/auth/password-reset', json={'email': 'unknown-reset@example.com'})
    assert unknown.status_code == known.status_code == 200
    assert unknown.json().keys() == known.json().keys()
    assert unknown.json()['message'] == known.json()['message']
    assert unknown.json()['challenge_id'] not in messages
    assert client.post('/api/auth/password-reset/confirm', json={
        'challenge_id': unknown.json()['challenge_id'], 'code': '000000', 'password': NEW_PASSWORD,
    }).status_code == 400
    assert client.post('/api/auth/password-reset', json={'email': 'unknown-reset@example.com'}).status_code == 429


def test_expiry_resend_attempt_limits_and_separate_registration_codes(auth_system, monkeypatch):
    client, _, messages = auth_system
    _, contact, _, _ = member(client)
    clock = password_reset.time.time()
    monkeypatch.setattr(password_reset, 'time', SimpleNamespace(time=lambda: clock))
    challenge = start(client, contact)
    first_code = messages[challenge]['code']
    assert client.post('/api/auth/password-reset/resend', json={'challenge_id': challenge}).status_code == 429
    assert client.post('/api/auth/password-reset', json=contact).status_code == 429
    # A registration challenge is never accepted as a password reset challenge.
    registration = start_registration(client, details())
    assert confirm(client, registration, messages).status_code == 400
    assert client.post('/api/auth/register/verify', json={'challenge_id': challenge, 'code': first_code}).status_code == 400
    clock += 601
    assert confirm(client, challenge, messages).status_code == 410
    monkeypatch.setattr(password_reset.secrets, 'randbelow', lambda _: (int(first_code) + 1) % 1_000_000)
    assert client.post('/api/auth/password-reset/resend', json={'challenge_id': challenge}).status_code == 200
    bad = {'challenge_id': challenge, 'code': first_code, 'password': NEW_PASSWORD}
    assert client.post('/api/auth/password-reset/confirm', json=bad).status_code == 400
    clock += 61
    assert client.post('/api/auth/password-reset/resend', json={'challenge_id': challenge}).status_code == 200
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda _: client.post('/api/auth/password-reset/confirm', json=bad).status_code, range(5)))
    assert sorted(results) == [400, 400, 400, 400, 429]
    assert confirm(client, challenge, messages).status_code == 429
    assert client.post('/api/auth/password-reset/resend', json={'challenge_id': challenge}).status_code == 429


def test_only_one_concurrent_reset_wins_and_all_other_challenges_are_revoked(auth_system, monkeypatch):
    client, _, messages = auth_system
    account, contact, _, _ = member(client)
    clock = password_reset.time.time()
    monkeypatch.setattr(password_reset, 'time', SimpleNamespace(time=lambda: clock))
    first = start(client, contact)
    clock += 61
    second = start(client, contact)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: confirm(client, first, messages).status_code, range(2)))
    assert sorted(results) == [200, 400]
    assert confirm(client, second, messages).status_code == 400
    with control_db() as db:
        assert db.execute('SELECT session_version FROM users WHERE id=?', (account['user']['id'],)).fetchone()[0] == 1


def test_send_limits_apply_even_to_unknown_accounts(auth_system, monkeypatch):
    client, _, messages = auth_system
    clock = password_reset.time.time()
    monkeypatch.setattr(password_reset, 'time', SimpleNamespace(time=lambda: clock))
    contact = {'email': 'unknown-limits@example.com'}
    for _ in range(5):
        start(client, contact)
        clock += 61
    assert client.post('/api/auth/password-reset', json=contact).status_code == 429
    for _ in range(15):
        start(client, {'email': f'{uuid.uuid4().hex}@example.com'})
    assert client.post('/api/auth/password-reset', json={'email': 'ip-limit@example.com'}).status_code == 429
    assert not messages


def test_delivery_failure_does_not_expose_account_or_change_password(auth_system, monkeypatch):
    client, _, messages = auth_system
    _, contact, identifier, old_password = member(client)
    captured = {}
    def failure(channel, destination, code, challenge_id, **_kwargs):
        captured[challenge_id] = {'code': code}
        raise delivery.DeliveryError('provider secret')
    monkeypatch.setattr(delivery, 'send_verification', failure)
    challenge = start(client, contact)
    assert confirm(client, challenge, captured).status_code == 400
    assert not messages
    assert client.post('/api/auth/login', json={'identifier': identifier, 'password': old_password}).status_code == 200


def test_deletion_removes_reset_requests_and_blocks_old_codes(auth_system):
    client, admin, messages = auth_system
    account, contact, _, _ = member(client)
    challenge = start(client, contact)
    assert client.delete(f'/api/admin/users/{account["user"]["id"]}', headers=admin).status_code == 200
    assert confirm(client, challenge, messages).status_code == 400
    with control_db() as db:
        assert not db.execute('SELECT 1 FROM password_reset_challenges WHERE id=?', (challenge,)).fetchone()
    unknown = start(client, contact)
    assert unknown not in messages


def test_validation_and_unavailable_channel(auth_system, monkeypatch):
    client, _, _ = auth_system
    for body in ({}, {'email': 'invalid'}, {'phone': '+85291234567'}, {'email': 'test@example.com', 'phone': '13800138000'}):
        assert client.post('/api/auth/password-reset', json=body).status_code == 422
    assert client.post('/api/auth/password-reset/confirm', json={'challenge_id': 'a' * 32, 'code': '123456', 'password': 'short'}).status_code == 422
    monkeypatch.setattr(delivery, 'configuration_status', lambda _purpose: {channel: {'available': False} for channel in ('email', 'sms')})
    assert client.get('/api/auth/password-reset/options').json() == {'email_available': False, 'sms_available': False}
    assert client.post('/api/auth/password-reset', json={'email': 'test@example.com'}).status_code == 503


def test_password_reset_closes_existing_event_stream(auth_system):
    client, _, messages = auth_system
    account, contact, _, _ = member(client)
    user_id = account['user']['id']
    project_id = uuid.uuid4().hex
    with workspace_db(user_id) as db:
        db.execute('INSERT INTO projects(id,name,brief) VALUES(?,?,?)', (project_id, 'Events', 'Reset event stream'))
    challenge = start(client, contact)
    async def scenario():
        stream = follow_frames(user_id, project_id, 0, 10, .01)
        assert await anext(stream) == ': heartbeat\n\n'
        assert await anext(stream) == 'retry: 1500\n\n'
        assert confirm(client, challenge, messages).status_code == 200
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    asyncio.run(scenario())


def test_reset_email_has_reset_instructions(monkeypatch):
    sent = []
    class SMTP:
        def __init__(self, *_args, **_kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def send_message(self, message):
            sent.append(message)
            return {}
    monkeypatch.setattr(delivery.smtplib, 'SMTP_SSL', SMTP)
    for key, value in {'smtp_from_address': 'no-reply@example.com', 'smtp_username': '', 'smtp_tls_mode': 'ssl'}.items():
        monkeypatch.setattr(settings, key, value)
    delivery._send_email('user@example.com', '123456', 'challenge', 'password_reset')
    assert 'password reset' in sent[0]['Subject'].lower()
    assert '123456' in sent[0].get_content() and 'password has not changed' in sent[0].get_content()
    assert 'administrator must approve' not in sent[0].get_content()


@pytest.mark.parametrize('reset_template,expected', [('', 'SMS_123'), ('SMS_456', 'SMS_456')])
def test_sms_reset_uses_configured_template_or_existing_verification_template(monkeypatch, reset_template, expected):
    for key, value in {'auth_sms_delivery_enabled': True, 'alibaba_cloud_access_key_id': 'test-key',
                       'alibaba_cloud_access_key_secret': 'test-secret', 'alibaba_cloud_security_token': '',
                       'aliyun_sms_sign_name': 'Forma', 'aliyun_sms_registration_template_code': 'SMS_123',
                       'aliyun_sms_password_reset_template_code': reset_template}.items():
        monkeypatch.setattr(settings, key, value)
    requests = []
    class Transport:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def handle_async_request(self, request):
            requests.append(request)
            return httpx.Response(200, json={'Code': 'OK'}, request=request)
    monkeypatch.setattr(delivery.httpx, 'AsyncHTTPTransport', Transport)
    delivery.send_verification('sms', '+8613800138000', '123456', uuid.uuid4().hex, purpose='password_reset')
    assert requests[0].url.params['TemplateCode'] == expected
