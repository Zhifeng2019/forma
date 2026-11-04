"""Persisted studio policy and provider access shared by the API and generation."""

from datetime import datetime, timedelta, timezone


def studio_policy(db) -> dict:
    policy = dict(db.execute('SELECT * FROM studio_policy WHERE id=1').fetchone())
    policy.pop('id')
    policy['allow_user_llm_config'] = bool(policy['allow_user_llm_config'])
    return policy


def can_configure_llm(user, policy: dict) -> bool:
    return user['role'] == 'admin' or policy['allow_user_llm_config']


def selectable_provider(db, provider_id: int, user_id: int):
    return db.execute('''SELECT * FROM providers WHERE id=? AND enabled=1
        AND (owner_user_id IS NULL OR owner_user_id=?)''', (provider_id, user_id)).fetchone()


def effective_provider_id(db, user_id: int) -> int | None:
    user = db.execute('SELECT role FROM users WHERE id=?', (user_id,)).fetchone()
    policy = studio_policy(db)
    if user and not can_configure_llm(user, policy):
        return policy['global_provider_id']
    pref = db.execute('SELECT provider_id FROM preferences WHERE user_id=?', (user_id,)).fetchone()
    if pref and pref['provider_id'] is not None and selectable_provider(db, pref['provider_id'], user_id):
        return pref['provider_id']
    return None


def hosting_deadline(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def hosting_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    deadline = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline <= datetime.now(timezone.utc)
