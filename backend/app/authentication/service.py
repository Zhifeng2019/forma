"""One-use verification challenges. No account or session exists before verification."""
import hashlib
import hmac
import math
import secrets
import time
import uuid

from fastapi import HTTPException

from ..config import settings
from ..database import control_db, workspace_for
from ..security import decrypt_secret, encrypt_secret, hash_password
from ..user_activity import track_user_activity
from . import delivery

CODE_TTL_SECONDS = 600
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5


def keyed_hash(purpose: str, value: str) -> str:
    return hmac.new(settings.secret_key.encode(), f'forma:{purpose}:{value}'.encode(), hashlib.sha256).hexdigest()


def _code_hash(challenge_id: str, code: str) -> str:
    return keyed_hash('registration-code', challenge_id + ':' + code)


def _contact(body) -> tuple[str, str]:
    return ('email', str(body.email).lower()) if body.email is not None else ('sms', body.phone)


def _existing(db, channel: str, destination: str):
    column = 'email' if channel == 'email' else 'phone'
    return db.execute(f'SELECT id FROM users WHERE {column}=?', (destination,)).fetchone()


def _check_available(channel: str):
    if not delivery.configuration_status()[channel]['available']:
        raise HTTPException(503, f'{"Email" if channel == "email" else "SMS"} verification is unavailable. Please contact the administrator.')


def _reserve_delivery(db, identity_key: str, ip: str, now: float):
    ip_key = keyed_hash('registration-ip', ip)
    recent = db.execute("SELECT created_at FROM auth_rate_events WHERE kind='send' AND identity_key=? ORDER BY created_at DESC LIMIT 1", (identity_key,)).fetchone()
    if recent and now - recent['created_at'] < RESEND_SECONDS:
        retry = max(1, math.ceil(RESEND_SECONDS - (now - recent['created_at'])))
        raise HTTPException(429, f'Wait {retry} seconds before requesting another code.', headers={'Retry-After': str(retry)})
    for column, key, maximum in [('identity_key', identity_key, 5), ('ip_key', ip_key, 20)]:
        count = db.execute(f"SELECT COUNT(*) FROM auth_rate_events WHERE kind='send' AND {column}=? AND created_at>?", (key, now - 3600)).fetchone()[0]
        if count >= maximum:
            raise HTTPException(429, 'Too many verification messages requested. Try again in an hour.', headers={'Retry-After': '3600'})
    db.execute("INSERT INTO auth_rate_events(identity_key,ip_key,kind,created_at) VALUES(?,?,'send',?)", (identity_key, ip_key, now))
    db.execute('DELETE FROM auth_rate_events WHERE created_at<?', (now - 86400,))
    db.execute('DELETE FROM registration_challenges WHERE created_at<?', (now - 86400,))
    db.execute('DELETE FROM password_reset_challenges WHERE created_at<?', (now - 86400,))


def _public_challenge(challenge_id: str, channel: str, destination: str, expires_at: float) -> dict:
    if channel == 'email':
        local, domain = destination.split('@')
        masked = local[0] + '***@' + domain
    else:
        masked = destination[:5] + '*****' + destination[-4:]
    return {'challenge_id': challenge_id, 'channel': channel, 'destination': masked,
            'expires_at': expires_at, 'resend_after': RESEND_SECONDS, 'status': 'verification_required'}


def _deliver(challenge_id: str, channel: str, destination: str, code: str, generation: int):
    try:
        delivery.send_verification(channel, destination, code, challenge_id)
    except delivery.DeliveryError:
        with control_db() as db:
            db.execute("UPDATE registration_challenges SET delivery_status='failed' WHERE id=? AND generation=?", (challenge_id, generation))
        raise HTTPException(503, 'The verification message could not be sent. Wait a minute and try again.') from None
    with control_db() as db:
        db.execute("UPDATE registration_challenges SET delivery_status='sent' WHERE id=? AND generation=?", (challenge_id, generation))


def begin_registration(body, ip: str) -> dict:
    channel, destination = _contact(body)
    _check_available(channel)
    now = time.time()
    challenge_id = uuid.uuid4().hex
    code = f'{secrets.randbelow(1_000_000):06d}'
    identity_key = keyed_hash('registration-contact', channel + ':' + destination)
    password_hash = hash_password(body.password)
    with control_db() as db:
        db.execute('BEGIN IMMEDIATE')
        if _existing(db, channel, destination):
            raise HTTPException(409, 'This contact already has an account. Sign in to check its approval status.')
        _reserve_delivery(db, identity_key, ip, now)
        db.execute('''INSERT INTO registration_challenges(id,channel,identity_key,destination_encrypted,
            name,password_hash,code_hash,created_at,expires_at,last_sent_at) VALUES(?,?,?,?,?,?,?,?,?,?)''', (
                challenge_id, channel, identity_key, encrypt_secret(destination), body.name, password_hash,
                _code_hash(challenge_id, code), now, now + CODE_TTL_SECONDS, now,
            ))
    # No database transaction is held while the external provider is contacted.
    _deliver(challenge_id, channel, destination, code, 1)
    return _public_challenge(challenge_id, channel, destination, now + CODE_TTL_SECONDS)


def resend_registration(challenge_id: str, ip: str) -> dict:
    now = time.time()
    code = f'{secrets.randbelow(1_000_000):06d}'
    with control_db() as db:
        db.execute('BEGIN IMMEDIATE')
        challenge = db.execute('SELECT * FROM registration_challenges WHERE id=?', (challenge_id,)).fetchone()
        if not challenge or now - challenge['created_at'] >= 86400:
            raise HTTPException(404, 'Registration not found. Start registration again.')
        if challenge['attempts'] >= MAX_ATTEMPTS:
            raise HTTPException(429, 'Too many incorrect codes. Start registration again.')
        _check_available(challenge['channel'])
        destination = decrypt_secret(challenge['destination_encrypted'])
        if _existing(db, challenge['channel'], destination):
            raise HTTPException(409, 'This contact already has an account. Sign in to check its approval status.')
        _reserve_delivery(db, challenge['identity_key'], ip, now)
        generation = challenge['generation'] + 1
        db.execute('''UPDATE registration_challenges SET code_hash=?,generation=?,delivery_status='sending',
            expires_at=?,last_sent_at=? WHERE id=?''', (_code_hash(challenge_id, code), generation, now + CODE_TTL_SECONDS, now, challenge_id))
    _deliver(challenge_id, challenge['channel'], destination, code, generation)
    return _public_challenge(challenge_id, challenge['channel'], destination, now + CODE_TTL_SECONDS)


def verify_registration(challenge_id: str, code: str) -> dict:
    with control_db() as db:
        db.execute('BEGIN IMMEDIATE')
        challenge = db.execute('SELECT * FROM registration_challenges WHERE id=?', (challenge_id,)).fetchone()
        if not challenge:
            raise HTTPException(400, 'This verification request is invalid or has already been used.')
        if challenge['attempts'] >= MAX_ATTEMPTS:
            raise HTTPException(429, 'Too many incorrect codes. Start registration again.')
        if challenge['expires_at'] <= time.time():
            raise HTTPException(410, 'This code has expired. Request a new code.')
        if challenge['delivery_status'] != 'sent':
            raise HTTPException(409, 'The verification message has not been sent. Request a new code.')
        if not hmac.compare_digest(challenge['code_hash'], _code_hash(challenge_id, code)):
            db.execute('UPDATE registration_challenges SET attempts=attempts+1 WHERE id=?', (challenge_id,))
            db.commit()  # Failed guesses must persist even though the request is rejected.
            raise HTTPException(400, 'The verification code is incorrect.')
        destination = decrypt_secret(challenge['destination_encrypted'])
        if _existing(db, challenge['channel'], destination):
            raise HTTPException(409, 'This contact already has an account. Sign in to check its approval status.')
        cursor = db.execute('''INSERT INTO users(email,phone,name,password_hash,status,verified_at)
            VALUES(?,?,?,?,'pending',CURRENT_TIMESTAMP)''', (
                destination if challenge['channel'] == 'email' else None,
                destination if challenge['channel'] == 'sms' else None,
                challenge['name'], challenge['password_hash'],
            ))
        user_id = cursor.lastrowid
        track_user_activity(user_id)
        db.execute('INSERT INTO preferences(user_id) VALUES(?)', (user_id,))
        # Remove every competing request for this identity, including its frozen password.
        db.execute('DELETE FROM registration_challenges WHERE identity_key=?', (challenge['identity_key'],))
    workspace_for(user_id)
    return {'status': 'pending_approval', 'message': 'Your contact is verified. Your registration has been sent to the administrator for approval.'}
