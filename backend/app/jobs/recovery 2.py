"""Release generation work that lost its worker so the owner can retry it.

Leases are only taken by API requests inside this process, so after a restart every unfinished attempt and every
queued job without one is orphaned. While the studio runs, only attempts whose heartbeat lease has expired are.
"""

import asyncio
import logging

from ..database import control_db, workspace_db
from .leases import utc_now
from .models import JobStatus
from .runner import _project_error
from .service import record_event
from .tool_runs import close_open_tool_runs
from .transactions import job_transaction

logger = logging.getLogger(__name__)

RESTART_MESSAGE = 'Generation was interrupted when the studio stopped unexpectedly. Retry this stage.'
EXPIRED_MESSAGE = 'Generation stopped responding and was released. Retry this stage.'
_CANCELLING = (JobStatus.CANCEL_REQUESTED.value, JobStatus.CANCELLING.value)
_ORPHANABLE = (JobStatus.QUEUED.value, JobStatus.LEASED.value)


def recover_interrupted_work(user_id: int, *, startup: bool) -> int:
    """Close orphaned attempts and jobs for one workspace; return how many jobs were released."""
    now = utc_now()
    message = RESTART_MESSAGE if startup else EXPIRED_MESSAGE
    reason = 'studio_restarted' if startup else 'lease_expired'
    closed_attempts = []
    errored = set()
    released = 0
    with workspace_db(user_id) as db:
        with job_transaction(db):
            query = '''SELECT a.id,a.job_id,j.project_id,j.status FROM job_attempts a
                JOIN generation_jobs j ON j.id=a.job_id WHERE a.ended_at IS NULL'''
            attempts = db.execute(query if startup else query + ' AND a.lease_expires_at<=?',
                                  () if startup else (now,)).fetchall()
            for attempt in attempts:
                db.execute('UPDATE job_attempts SET ended_at=?,failure_code=? WHERE id=?', (now, reason, attempt['id']))
                status = (JobStatus.CANCELLED.value if attempt['status'] in _CANCELLING
                          else JobStatus.RECOVERY_REQUIRED.value)
                db.execute('UPDATE generation_jobs SET status=?,updated_at=? WHERE id=?', (status, now, attempt['job_id']))
                record_event(db, attempt['job_id'], status, {'reason': reason, 'attempt_id': attempt['id']},
                             f'{attempt["id"]}:{reason}')
                record_event(db, attempt['job_id'], 'project.refresh', {'status': status, 'attempt_id': attempt['id']},
                             f'{attempt["id"]}:{reason}:project.refresh')
                errored.add(attempt['project_id'])
                closed_attempts.append((attempt['job_id'], attempt['id']))
                released += 1
            if startup:
                placeholders = ','.join('?' for _ in _ORPHANABLE)
                orphans = db.execute(f'''SELECT id,project_id FROM generation_jobs j WHERE status IN ({placeholders})
                    AND NOT EXISTS (SELECT 1 FROM job_attempts a WHERE a.job_id=j.id AND a.ended_at IS NULL)''',
                    _ORPHANABLE).fetchall()
                for job in orphans:
                    db.execute('UPDATE generation_jobs SET status=?,updated_at=? WHERE id=?',
                               (JobStatus.RECOVERY_REQUIRED.value, now, job['id']))
                    record_event(db, job['id'], JobStatus.RECOVERY_REQUIRED.value, {'reason': reason}, f'{job["id"]}:{reason}:{now}')
                    errored.add(job['project_id'])
                    released += 1
                # Legacy in-memory generation leaves no job row; no task survives a restart.
                errored.update(row['id'] for row in db.execute("SELECT id FROM projects WHERE status='working'"))
            for project_id in sorted(errored):
                _project_error(db, project_id, message)
    for job_id, attempt_id in closed_attempts:
        close_open_tool_runs(user_id, job_id, attempt_id, 'failed', reason)
    return released


def _user_ids() -> list[int]:
    with control_db() as db:
        return [row['id'] for row in db.execute('SELECT id FROM users')]


def recover_all_workspaces(*, startup: bool) -> int:
    released = 0
    for user_id in _user_ids():
        try:
            released += recover_interrupted_work(user_id, startup=startup)
        except Exception:
            logger.exception('Could not recover interrupted generation work for user %s', user_id)
    return released


async def recovery_loop(interval: float = 30.0) -> None:
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(recover_all_workspaces, startup=False)
