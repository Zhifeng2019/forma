"""Verification, account approval, and transport boundaries (no real messages)."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import uuid

from fastapi.testclient import TestClient
import httpx
import pytest

from app.authentication import delivery, service
from app.authentication.identities import canonical_phone
from app.config import settings
from app.database import control_db, init_databases, workspace_db
from app.main import app
from app.security import create_token, decrypt_secret
from fixtures.accounts import register_account


@pytest.fixture
def auth_system(monkeypatch):
    messages = {}
    def capture(channel, destination, code, challenge_id, *, purpose='registration'):
        messages[challenge_id] = {'channel': channel, 'destination': destination, 'code': code, 'purpose': purpose}
    monkeypatch.setattr(delivery, 'send_verification', capture)
    monkeypatch.setattr(delivery, 'configuration_status', lambda purpose='registration': {
        name: {'enabled': True, 'configured': True, 'available': True} for name in ('email', 'sms')
    })
    # Isolate quotas across tests without relaxing production limits.
    with control_db() as db:
        db.execute('DELETE FROM auth_rate_events')
    with TestClient(app) as client:
        admin = client.post('/api/auth/login', json={'email': 'admin@forma.local', 'password': 'admin123'}).json()
        yield client, {'Authorization': f'Bearer {admin["token"]}'}, messages


def details(**patch):
    return {'email': f'applicant-{uuid.uuid4().hex}@example.com', 'name': 'New Applicant', 'password': 'registration-password', **patch}


def start(client, body):
    response = client.post('/api/auth/register', json=body)
    assert response.status_code == 200, response.text
    assert 'token' not in response.json() and 'code' not in response.json()
    return response.json()['challenge_id']


def verify(client, challenge_id, messages):
    return client.post('/api/auth/register/verify', json={'challenge_id': challenge_id, 'code': messages[challenge_id]['code']})


def find_applicant(client, headers, body):
    users = client.get('/api/admin/users', headers=headers).json()
    return next((u for u in users if (body.get('email') and u['email'] == body['email'])
                 or (body.get('phone') and u['phone'] == canonical_phone(body['phone']))), None)


@pytest.mark.parametrize('phone', [False, True])
def test_verified_applicant_must_be_approved_before_login(auth_system, phone):
    client, headers, messages = auth_system
    body = details(role='admin', status='active')  # Client-supplied privileges must have no effect.
    if phone:
        body.pop('email')
        body['phone'] = '138 0013 8000'
    challenge_id = start(client, body)
    assert find_applicant(client, headers, body) is None
    with control_db() as db:
        challenge = dict(db.execute('SELECT * FROM registration_challenges WHERE id=?', (challenge_id,)).fetchone())
        assert challenge['code_hash'] != messages[challenge_id]['code']
        assert challenge['password_hash'] != body['password']
        assert decrypt_secret(challenge['destination_encrypted']) == messages[challenge_id]['destination']
        assert 'destination' not in challenge
    verified = verify(client, challenge_id, messages)
    assert verified.status_code == 200 and verified.json()['status'] == 'pending_approval'
    assert 'token' not in verified.json()
    applicant = find_applicant(client, headers, body)
    assert applicant['role'] == 'user' and applicant['status'] == 'pending' and applicant['verified_at'] and not applicant['reviewed_at']
    identity = body.get('email') or '+86 13800138000'
    login_body = {'identifier': identity, 'password': body['password']}
    assert client.post('/api/auth/login', json=login_body).status_code == 403
    forged = {'Authorization': f'Bearer {create_token(applicant["id"])}'}
    assert client.get('/api/projects', headers=forged).status_code == 401
    member = register_account(client, json=details()).json()
    assert client.patch(f'/api/admin/users/{applicant["id"]}', headers={'Authorization': f'Bearer {member["token"]}'}, json={'status': 'active'}).status_code == 403
    assert client.patch(f'/api/admin/users/{applicant["id"]}', headers=headers, json={'role': 'admin'}).status_code == 409
    assert client.patch(f'/api/admin/users/{applicant["id"]}', headers=headers, json={'status': 'active'}).status_code == 200
    approved = find_applicant(client, headers, body)
    assert approved['reviewed_at'] and approved['reviewed_by'] == 1
    login = client.post('/api/auth/login', json=login_body)
    assert login.status_code == 200 and login.json()['token']
    assert client.get('/api/projects', headers={'Authorization': f'Bearer {login.json()["token"]}'}).status_code == 200
    if phone:
        assert login.json()['user']['email'] is None and login.json()['user']['phone'] == '+8613800138000'
    assert verify(client, challenge_id, messages).status_code == 400


def test_rejection_and_existing_account_controls(auth_system):
    client, headers, messages = auth_system
    body = details()
    challenge_id = start(client, body)
    assert verify(client, challenge_id, messages).status_code == 200
    applicant = find_applicant(client, headers, body)
    url = f'/api/admin/users/{applicant["id"]}'
    assert client.patch(url, headers=headers, json={'status': 'rejected'}).status_code == 200
    rejected = client.post('/api/auth/login', json={'email': body['email'], 'password': body['password']})
    assert rejected.status_code == 403 and 'not approved' in rejected.json()['detail']
    assert client.post('/api/auth/register', json=body).status_code == 409
    assert client.patch(url, headers=headers, json={'status': 'active'}).status_code == 200
    assert client.patch(url, headers=headers, json={'status': 'disabled'}).status_code == 200
    assert client.post('/api/auth/login', json={'email': body['email'], 'password': body['password']}).status_code == 403
    assert client.patch(url, headers=headers, json={'status': 'active'}).status_code == 200
    assert client.patch('/api/admin/users/1', headers=headers, json={'role': 'user'}).status_code == 400
    assert client.patch('/api/admin/users/9999999', headers=headers, json={'status': 'active'}).status_code == 404


@pytest.mark.parametrize('phone', ['+85291234567', '+886912345678', '+14155551234', '12345678901', '1380013800', '+86138001380000', '１３８００１３８０００'])
def test_non_mainland_and_invalid_mobile_numbers_are_rejected(auth_system, phone):
    client, _, messages = auth_system
    assert client.post('/api/auth/register', json=details(email=None, phone=phone)).status_code == 422
    assert not messages


def test_contact_validation_and_canonical_duplicates(auth_system):
    client, _, messages = auth_system
    for body in [details(email=None), details(phone='13900139000'), details(email='bad'), details(name='   ')]:
        assert client.post('/api/auth/register', json=body).status_code == 422
    body = details(email='CaseApplicant@example.com')
    challenge_id = start(client, body)
    assert messages[challenge_id]['destination'] == 'caseapplicant@example.com'
    assert verify(client, challenge_id, messages).status_code == 200
    assert client.post('/api/auth/register', json={**body, 'email': body['email'].upper()}).status_code == 409
    phone = details(email=None, phone='0086 139-0013-9000')
    challenge_id = start(client, phone)
    assert messages[challenge_id]['destination'] == '+8613900139000'
    assert verify(client, challenge_id, messages).status_code == 200
    assert client.post('/api/auth/register', json={**phone, 'phone': '+8613900139000'}).status_code == 409


def test_codes_are_bound_expire_and_resend_invalidates_old_code(auth_system, monkeypatch):
    client, _, messages = auth_system
    clock = service.time.time()
    monkeypatch.setattr(service, 'time', SimpleNamespace(time=lambda: clock))
    body = details()
    first = start(client, body)
    original_code = messages[first]['code']
    assert client.post('/api/auth/register/resend', json={'challenge_id': first}).status_code == 429
    assert client.post('/api/auth/register', json=body).status_code == 429
    second = start(client, details())
    assert client.post('/api/auth/register/verify', json={'challenge_id': second, 'code': original_code}).status_code == 400
    clock += 601
    assert verify(client, first, messages).status_code == 410
    # Choose an explicitly different code so this test is deterministic.
    monkeypatch.setattr(service.secrets, 'randbelow', lambda _: (int(original_code) + 1) % 1_000_000)
    assert client.post('/api/auth/register/resend', json={'challenge_id': first}).status_code == 200
    assert client.post('/api/auth/register/verify', json={'challenge_id': first, 'code': original_code}).status_code == 400
    assert verify(client, first, messages).status_code == 200


def test_attempt_limits_persist_and_resending_cannot_reset_them(auth_system, monkeypatch):
    client, _, messages = auth_system
    challenge_id = start(client, details())
    bad = f'{(int(messages[challenge_id]["code"]) + 1) % 1_000_000:06d}'
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: client.post('/api/auth/register/verify', json={'challenge_id': challenge_id, 'code': bad}), range(6)))
    assert sorted(r.status_code for r in responses) == [400] * 5 + [429]
    assert verify(client, challenge_id, messages).status_code == 429
    assert client.post('/api/auth/register/resend', json={'challenge_id': challenge_id}).status_code == 429
    with control_db() as db:
        assert db.execute('SELECT attempts FROM registration_challenges WHERE id=?', (challenge_id,)).fetchone()[0] == 5


def test_only_one_concurrent_verification_creates_an_account(auth_system):
    client, headers, messages = auth_system
    body = details()
    challenge_id = start(client, body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: verify(client, challenge_id, messages), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 400]
    assert len([u for u in client.get('/api/admin/users', headers=headers).json() if u['email'] == body['email']]) == 1


def test_sending_limits_cannot_be_reset_by_starting_again(auth_system, monkeypatch):
    client, _, _ = auth_system
    clock = service.time.time()
    monkeypatch.setattr(service, 'time', SimpleNamespace(time=lambda: clock))
    body = details()
    for _ in range(5):
        start(client, body)
        clock += 61
    assert client.post('/api/auth/register', json=body).status_code == 429
    for _ in range(15):
        start(client, details())
    assert client.post('/api/auth/register', json=details()).status_code == 429


def test_delivery_failure_cannot_verify_or_leak_credentials(auth_system, monkeypatch):
    client, headers, messages = auth_system
    def fail(*args):
        raise delivery.DeliveryError('secret-provider-response')
    monkeypatch.setattr(delivery, 'send_verification', fail)
    body = details()
    response = client.post('/api/auth/register', json=body)
    assert response.status_code == 503 and 'secret-provider-response' not in response.text
    assert find_applicant(client, headers, body) is None
    assert not messages
    with control_db() as db:
        challenge = db.execute("SELECT id FROM registration_challenges WHERE name=? AND delivery_status='failed' ORDER BY created_at DESC", (body['name'],)).fetchone()
    assert client.post('/api/auth/register/verify', json={'challenge_id': challenge['id'], 'code': '123456'}).status_code == 409
    monkeypatch.setattr(delivery, 'configuration_status', lambda: {name: {'available': False} for name in ('email', 'sms')})
    assert client.get('/api/auth/registration-options').json() == {'email_available': False, 'sms_available': False, 'approval_required': True}
    assert client.post('/api/auth/register', json=details()).status_code == 503


def test_preexisting_accounts_migrate_without_approval_or_data_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_dir', str(tmp_path))
    with control_db() as db:
        db.executescript('''CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT DEFAULT 'user', status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO users(id,email,name,password_hash,role) VALUES(7,'old@example.com','Existing','unchanged','admin');
            INSERT INTO users(id,email,name,password_hash) VALUES(100,'deleted@example.com','Removed','unused');
            DELETE FROM users WHERE id=100;
        ''')
    init_databases()
    init_databases()
    with control_db() as db:
        old = db.execute('SELECT * FROM users WHERE id=7').fetchone()
        assert old['status'] == 'active' and old['password_hash'] == 'unchanged' and old['role'] == 'admin'
        assert old['verified_at'] is None
        cursor = db.execute("INSERT INTO users(phone,name,password_hash,status) VALUES('+8613700137000','Mobile','hash','pending')")
        assert cursor.lastrowid > 100
        assert db.execute('SELECT email FROM users WHERE id=?', (cursor.lastrowid,)).fetchone()[0] is None
    with workspace_db(7) as db:
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 0


@pytest.mark.parametrize('tls_mode', ['ssl', 'starttls'])
def test_smtp_delivery_requires_tls_and_never_uses_debug_output(monkeypatch, tls_mode):
    sent, actions = [], []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            actions.append(('connect', host, port, kwargs))
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def ehlo(self): actions.append('ehlo')
        def starttls(self, **kwargs): actions.append(('tls', kwargs))
        def login(self, username, password): actions.append(('login', username))
        def send_message(self, message):
            sent.append(message)
            return {}
    for key, value in {'auth_email_delivery_enabled': True, 'smtp_host': 'smtp.example.com', 'smtp_from_address': 'no-reply@example.com', 'smtp_username': 'user', 'smtp_password': 'smtp-secret', 'smtp_tls_mode': tls_mode}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(delivery.smtplib, 'SMTP_SSL', SMTP)
    monkeypatch.setattr(delivery.smtplib, 'SMTP', SMTP)
    delivery.send_verification('email', 'test@example.com', '123456', uuid.uuid4().hex)
    assert sent[0]['To'] == 'test@example.com' and '123456' in sent[0].get_content()
    if tls_mode == 'ssl':
        assert actions[0][3]['context'].check_hostname
    else:
        assert actions[2][0] == 'tls' and actions[3] == 'ehlo' and actions[4][0] == 'login'


def test_aliyun_sms_is_signed_for_mainland_number_and_provider_failures_are_sanitized(monkeypatch, caplog):
    for key, value in {'auth_sms_delivery_enabled': True, 'alibaba_cloud_access_key_id': 'test-key',
                       'alibaba_cloud_access_key_secret': 'test-secret', 'aliyun_sms_sign_name': 'Forma',
                       'aliyun_sms_registration_template_code': 'SMS_123456', 'alibaba_cloud_security_token': 'temporary-token'}.items():
        monkeypatch.setattr(settings, key, value)
    captured = []
    status = 200
    class Transport:
        def __init__(self, **kwargs):
            assert kwargs == {'verify': True, 'trust_env': False, 'retries': 0}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def handle_async_request(self, request):
            captured.append(request)
            return httpx.Response(status, json={'Code': 'OK' if status == 200 else 'ProviderSecret 123456'}, request=request)
    monkeypatch.setattr(delivery.httpx, 'AsyncHTTPTransport', Transport)
    delivery.send_verification('sms', '+8613800138000', '123456', uuid.uuid4().hex)
    request = captured[0]
    assert request.url.host == 'dysmsapi.aliyuncs.com'
    assert request.url.params['PhoneNumbers'] == '13800138000'
    assert request.url.params['TemplateParam'] == '{"code":"123456"}'
    assert request.headers['authorization'].startswith('ACS3-HMAC-SHA256 Credential=test-key,')
    assert request.headers['x-acs-security-token'] == 'temporary-token'
    assert '123456' not in caplog.text and '13800138000' not in caplog.text
    status = 500
    with pytest.raises(delivery.DeliveryError, match='^Verification delivery failed$'):
        delivery.send_verification('sms', '+8613800138000', '123456', uuid.uuid4().hex)
    assert len(captured) == 2  # No automatic retries, including uncertain provider outcomes.
    with pytest.raises(delivery.DeliveryError):
        asyncio.run(delivery._send_sms('+85291234567', '123456', 'test'))


def test_aliyun_signing_matches_published_known_answer_vector(monkeypatch):
    # Same independent Alibaba Cloud ACS3 vector verified by the reference backend.
    monkeypatch.setattr(settings, 'alibaba_cloud_access_key_id', 'YourAccessKeyId')
    monkeypatch.setattr(settings, 'alibaba_cloud_access_key_secret', 'YourAccessKeySecret')
    headers = {
        'host': 'ecs.cn-shanghai.aliyuncs.com', 'x-acs-action': 'RunInstances',
        'x-acs-version': '2014-05-26', 'x-acs-date': '2023-10-26T10:22:32Z',
        'x-acs-signature-nonce': '3156853299f313e23d1673dc12e1703d',
        'x-acs-content-sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    }
    signature = delivery._authorization('ImageId=win2019_1809_x64_dtc_zh-cn_40G_alibase_20230811.vhd&RegionId=cn-shanghai', headers)
    assert signature.endswith('Signature=06563a9e1b43f5dfe96b81484da74bceab24a1d853912eee15083a6f0f3283c0')
