"""Contact-bound, one-use password resets with no account lookup disclosure."""

import hmac
import secrets
import time
import uuid

from fastapi import HTTPException

from ..database import control_db
from ..security import decrypt_secret, encrypt_secret, hash_password
from ..user_activity import track_user_activity
from . import delivery
from .service import CODE_TTL_SECONDS, MAX_ATTEMPTS, _contact, _public_challenge, _reserve_delivery, keyed_hash

REQUEST_MESSAGE = 'If this contact has an account, a verification code will be sent. Check your inbox or messages.'
INVALID_CODE = 'The verification code is invalid or expired. Check the code or request a new one.'


def _code_hash(challenge_id: str, code: str) -> str:
    return keyed_hash('password-reset-code', challenge_id + ':' + code)


def _check_available(channel: str) -> None:
    if not delivery.configuration_status('password_reset')[channel]['available']:
        raise HTTPException(503, f'{"Email" if channel == "email" else "SMS"} password reset is unavailable. Please contact the administrator.')


def _public(challenge_id: str, channel: str, destination: str, expires_at: float) -> dict:
    return {**_public_challenge(challenge_id, channel, destination, expires_at), 'message': REQUEST_MESSAGE}


def _eligible_user(db, challenge):
    user = db.execute('SELECT * FROM users WHERE id=?', (challenge['user_id'],)).fetchone()
    contact = decrypt_secret(challenge['destination_encrypted'])
    column = 'email' if challenge['channel'] == 'email' else 'phone'
    if (user and user['status'] != 'deleting' and user['session_version'] == challenge['session_version']
            and user[column] == contact):
        return user
    return None


def _deliver(challenge_id: str, generation: int, code: str) -> None:
    # Run after returning the same response for known and unknown contacts.
    with control_db() as db:
        challenge = db.execute('SELECT * FROM password_reset_challenges WHERE id=? AND generation=?',
                               (challenge_id, generation)).fetchone()
        if not challenge:
            return
        if challenge['user_id'] is not None:
            track_user_activity(challenge['user_id'])
        user = _eligible_user(db, challenge)
    status = 'sent'
    if user:
        try:
            delivery.send_verification(challenge['channel'], decrypt_secret(challenge['destination_encrypted']),
                                       code, challenge_id, purpose='password_reset')
        except delivery.DeliveryError:
            # Do not leak account existence or provider details via response differences.
            status = 'failed'
    with control_db() as db:
        db.execute('UPDATE password_reset_challenges SET delivery_status=? WHERE id=? AND generation=?',
                   (status, challenge_id, generation))


def begin_password_reset(body, ip: str, background_tasks) -> dict:
    channel, destination = _contact(body)
    _check_available(channel)
    now = time.time()
    challenge_id = uuid.uuid4().hex
    code = f'{secrets.randbelow(1_000_000):06d}'
    # Share send limits across registration and reset to prevent bypassing quotas.
    identity_key = keyed_hash('registration-contact', channel + ':' + destination)
    column = 'email' if channel == 'email' else 'phone'
    with control_db() as db:
        db.execute('BEGIN IMMEDIATE')
        _reserve_delivery(db, identity_key, ip, now)
        user = db.execute(f"SELECT id,session_version FROM users WHERE {column}=? AND status!='deleting'",
                          (destination,)).fetchone()
        if user:
            track_user_activity(user['id'])
        db.execute('''INSERT INTO password_reset_challenges(
            id,user_id,session_version,channel,identity_key,destination_encrypted,code_hash,created_at,expires_at,last_sent_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)''', (
                challenge_id, user['id'] if user else None, user['session_version'] if user else None,
                channel, identity_key, encrypt_secret(destination), _code_hash(challenge_id, code), now,
                now + CODE_TTL_SECONDS, now,
            ))
    background_tasks.add_task(_deliver, challenge_id, 1, code)
    return _public(challenge_id, channel, destination, now + CODE_TTL_SECONDS)


def resend_password_reset(challenge_id: str, ip: str, background_tasks) -> dict:
    now = time.time()
    code = f'{secrets.randbelow(1_000_000):06d}'
    with control_db() as db:
        db.execute('BEGIN IMMEDIATE')
        challenge = db.execute('SELECT * FROM password_reset_challenges WHERE id=?', (challenge_id,)).fetchone()
        if not challenge or now - challenge['created_at'] >= 86400:
            raise HTTPException(404, 'Password reset request not found. Start again.')
        if challenge['attempts'] >= MAX_ATTEMPTS:
            raise HTTPException(429, 'Too many incorrect codes. Start a new password reset request.')
        if hmac.compare_digest(challenge['code_hash'], _code_hash(challenge_id, code)):
            code = f'{(int(code) + 1) % 1_000_000:06d}'
        _check_available(challenge['channel'])
        _reserve_delivery(db, challenge['identity_key'], ip, now)
        if challenge['user_id'] is not None:
            track_user_activity(challenge['user_id'])
        destination = decrypt_secret(challenge['destination_encrypted'])
        generation = challenge['generation'] + 1
        db.execute('''UPDATE password_reset_challenges SET code_hash=?,generation=?,delivery_status='sending',
            expires_at=?,last_sent_at=? WHERE id=?''',
            (_code_hash(challenge_id, code), generation, now + CODE_TTL_SECONDS, now, challenge_id))
    background_tasks.add_task(_deliver, challenge_id, generation, code)
    return _public(challenge_id, challenge['channel'], destination, now + CODE_TTL_SECONDS)


def confirm_password_reset(challenge_id: str, code: str, password: str) -> dict:
    with control_db() as db:
        db.execute('BEGIN IMMEDIATE')
        challenge = db.execute('SELECT * FROM password_reset_challenges WHERE id=?', (challenge_id,)).fetchone()
        if not challenge:
            raise HTTPException(400, INVALID_CODE)
        if challenge['attempts'] >= MAX_ATTEMPTS:
            raise HTTPException(429, 'Too many incorrect codes. Start a new password reset request.')
        if challenge['expires_at'] <= time.time():
            raise HTTPException(410, 'This code has expired. Request a new code.')
        user = _eligible_user(db, challenge)
        matches = hmac.compare_digest(challenge['code_hash'], _code_hash(challenge_id, code))
        if not matches or not user or challenge['delivery_status'] != 'sent':
            db.execute('UPDATE password_reset_challenges SET attempts=attempts+1 WHERE id=?', (challenge_id,))
            db.commit()
            raise HTTPException(400, INVALID_CODE)
        track_user_activity(user['id'])
        db.execute('UPDATE users SET password_hash=?,session_version=session_version+1 WHERE id=?',
                   (hash_password(password), user['id']))
        # A second contact/challenge cannot undo a completed reset; approval is unchanged.
        db.execute('DELETE FROM password_reset_challenges WHERE user_id=? OR identity_key=?',
                   (user['id'], challenge['identity_key']))
    return {'status': 'password_reset', 'message': 'Your password has been updated. Sign in with your new password.'}
