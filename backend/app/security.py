import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
import jwt
from cryptography.fernet import Fernet
from .config import settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 240_000)
    return f'{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, expected = stored.split('$')
        digest = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(salt), 240_000)
        return hmac.compare_digest(base64.b64encode(digest).decode(), expected)
    except (ValueError, TypeError):
        return False


def _session_version(user_id: int) -> int | None:
    from .database import control_db
    with control_db() as db:
        user = db.execute('SELECT session_version FROM users WHERE id=?', (user_id,)).fetchone()
    return user['session_version'] if user else None


def create_token(user_id: int, session_version: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    version = _session_version(user_id) if session_version is None else session_version
    return jwt.encode({'sub': str(user_id), 'sv': version or 0, 'iat': now, 'exp': now + timedelta(days=settings.access_token_days)},
                      settings.secret_key, algorithm='HS256')


def decode_session(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=['HS256'], options={'require': ['sub', 'iat', 'exp']})


def _check_session_version(payload: dict) -> None:
    if payload.get('sv', 0) != _session_version(int(payload['sub'])):
        raise jwt.InvalidTokenError('This session has expired')


def decode_token(token: str) -> int:
    payload = decode_session(token)
    _check_session_version(payload)
    return int(payload['sub'])


def _preview_key() -> bytes:
    return hmac.digest(settings.secret_key.encode(), b'forma:preview:v1', 'sha256')


def create_preview_token(user_id: int, project_id: str, version: int, parent_origin: str,
                         session_version: int | None = None) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires = int((now + timedelta(minutes=settings.preview_token_minutes)).timestamp())
    token = jwt.encode({
        'sub': str(user_id), 'project': project_id, 'version': version,
        'sv': (_session_version(user_id) if session_version is None else session_version) or 0,
        'parent_origin': parent_origin, 'aud': 'forma-preview', 'iat': now, 'exp': expires,
    }, _preview_key(), algorithm='HS256')
    return token, expires


def decode_preview_token(token: str, project_id: str, version: int) -> dict:
    payload = jwt.decode(token, _preview_key(), algorithms=['HS256'], audience='forma-preview',
                         options={'require': ['sub', 'project', 'version', 'parent_origin', 'iat', 'exp', 'aud']})
    if payload['project'] != project_id or payload['version'] != version:
        raise jwt.InvalidTokenError('Preview grant does not match this project version')
    _check_session_version(payload)
    return payload


def _fernet():
    key = hashlib.sha256(settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ''


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode() if value else ''
