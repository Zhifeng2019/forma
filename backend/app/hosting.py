"""Stop expired public processes even when no visitors request the app."""

import asyncio
import logging

from .database import control_db
from .deployment_registry import get_deployment
from .policy import hosting_expired
from .runtime import runtime_manager

logger = logging.getLogger(__name__)
_publication_locks: dict[str, asyncio.Lock] = {}


def publication_lock(project_id: str) -> asyncio.Lock:
    # Hosting expiry must not wait for a potentially long generation job.
    return _publication_locks.setdefault(project_id, asyncio.Lock())


async def stop_expired_hosting() -> None:
    with control_db() as db:
        projects = [row['project_id'] for row in db.execute(
            'SELECT project_id,hosting_expires_at FROM deployment_registry WHERE hosting_expires_at IS NOT NULL',
        ) if hosting_expired(row['hosting_expires_at'])]
    for project_id in projects:
        async with publication_lock(project_id):
            # A republish may have renewed the deadline while we waited for this lock.
            deployment = get_deployment(project_id)
            if deployment and hosting_expired(deployment['hosting_expires_at']):
                await runtime_manager.stop_project(project_id, channel='public')


async def hosting_expiry_loop() -> None:
    while True:
        try:
            await stop_expired_hosting()
        except Exception:
            logger.exception('Unable to stop expired hosting processes')
        await asyncio.sleep(30)
