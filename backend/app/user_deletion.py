"""Retryable account removal: revoke access, drain work, then erase owned data."""

import asyncio
import logging
import sqlite3

from fastapi import HTTPException

from .authentication.service import keyed_hash
from .config import settings
from .database import control_db, workspace_db
from .engine import validate_project_id
from .frontend_builder import remove_user_environment
from .runtime import runtime_manager
from .user_activity import cancel_user_requests

logger = logging.getLogger(__name__)
_locks: dict[int, asyncio.Lock] = {}


async def delete_account(user_id: int, admin_id: int, cancel_jobs) -> None:
    if user_id == admin_id:
        raise HTTPException(400, 'You cannot delete your own administrator account')
    async with _locks.setdefault(user_id, asyncio.Lock()):
        with control_db() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM users WHERE id=? AND role='admin' AND status='active'", (admin_id,)).fetchone():
                raise HTTPException(403, 'An active administrator account is required')
            user = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not user:
                raise HTTPException(404, 'User not found')
            # Keep the identity reserved until every cleanup step succeeds.
            db.execute("UPDATE users SET status='deleting' WHERE id=?", (user_id,))
        try:
            await cancel_user_requests(user_id)
            await cancel_jobs(user_id)
            workspace = settings.data_path / 'users' / f'user_{user_id}.db'
            with control_db() as db:
                project_ids = {row['project_id'] for row in db.execute(
                    'SELECT project_id FROM deployment_registry WHERE user_id=?', (user_id,))}
            if workspace.exists():
                with workspace_db(user_id) as db:
                    project_ids.update(row['id'] for row in db.execute('SELECT id FROM projects'))
            # Validate the whole set before removing anything from disk.
            for project_id in project_ids:
                validate_project_id(project_id)
            for project_id in project_ids:
                await runtime_manager.remove_project(project_id)
            await remove_user_environment(user_id)
            # No await between removing the workspace and committing account removal.
            # If a filesystem step fails, leave the account blocked and retryable.
            with control_db() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('UPDATE preferences SET provider_id=NULL WHERE provider_id IN '
                           '(SELECT id FROM providers WHERE owner_user_id=?)', (user_id,))
                db.execute('UPDATE studio_policy SET global_provider_id=NULL WHERE global_provider_id IN '
                           '(SELECT id FROM providers WHERE owner_user_id=?)', (user_id,))
                db.execute('DELETE FROM providers WHERE owner_user_id=?', (user_id,))
                db.execute('DELETE FROM preferences WHERE user_id=?', (user_id,))
                db.execute('DELETE FROM deployment_registry WHERE user_id=?', (user_id,))
                db.execute('DELETE FROM password_reset_challenges WHERE user_id=?', (user_id,))
                for channel, contact in [('email', user['email']), ('sms', user['phone'])]:
                    if contact:
                        identity = keyed_hash('registration-contact', channel + ':' + contact)
                        db.execute('DELETE FROM registration_challenges WHERE identity_key=?', (identity,))
                        db.execute('DELETE FROM password_reset_challenges WHERE identity_key=?', (identity,))
                        db.execute('DELETE FROM auth_rate_events WHERE identity_key=?', (identity,))
                db.execute('UPDATE users SET reviewed_by=NULL WHERE reviewed_by=?', (user_id,))
                for suffix in ('-wal', '-shm', '-journal', ''):
                    workspace.with_name(workspace.name + suffix).unlink(missing_ok=True)
                db.execute('DELETE FROM users WHERE id=?', (user_id,))
        except (OSError, sqlite3.Error, TimeoutError, RuntimeError, ValueError) as exc:
            logger.error('User %s cleanup failed (%s); deletion can be retried', user_id, type(exc).__name__)
            raise HTTPException(503, 'Deletion could not finish. The account is blocked. Retry deleting this user.') from None
