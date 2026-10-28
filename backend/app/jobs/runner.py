"""Durable execution for API-triggered generation operations."""

import asyncio
from collections.abc import Awaitable, Callable
import sqlite3
import uuid

from ..database import workspace_db
from .cancellation import cancellation_event, clear_job, register_job
from .checkpoints import checkpoint
from .context import JobContext, activate_job_context, reset_job_context
from .idempotency import canonical_input_hash
from .leases import complete_attempt, finalize_job, heartbeat, lease_next_job
from .models import JobCancelledError, JobStatus, LeaseLostError
from .service import create_job, get_job, record_event
from .snapshots import (
    capture_attempt_snapshot, discard_attempt_snapshot, rollback_attempt_snapshot,
)
from .transactions import job_transaction

_ACTIVE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.LEASED.value,
    JobStatus.RUNNING.value,
    JobStatus.WAITING_ON_TOOL.value,
    JobStatus.FINALIZING.value,
    JobStatus.RETRY_SCHEDULED.value,
    JobStatus.WAITING_FOR_APPROVAL.value,
    JobStatus.CANCEL_REQUESTED.value,
    JobStatus.CANCELLING.value,
}
_RETRYABLE_STATUSES = {
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.DEAD_LETTER.value,
    JobStatus.RECOVERY_REQUIRED.value,
}


def _project_error(db: sqlite3.Connection, project_id: str, message: str) -> None:
    db.execute("UPDATE projects SET status='error',updated_at=CURRENT_TIMESTAMP WHERE id=?", (project_id,))
    db.execute('INSERT INTO events(project_id,message,level) VALUES(?,?,?)', (project_id, message, 'error'))
    db.execute('INSERT INTO messages(project_id,role,content,kind) VALUES(?,?,?,?)',
               (project_id, 'agent', message, 'error'))


def _prepare_attempt(
    user_id: int,
    project_id: str,
    stage: str,
    action: str,
    input_hash: str,
    trace_id: str,
    worker_id: str,
    lease_seconds: int,
    retry_succeeded: bool = False,
) -> tuple[str, dict] | None:
    with workspace_db(user_id) as db:
        job_id, created = create_job(db, project_id, stage, input_hash, action, trace_id)
        job = get_job(db, job_id)
        if job is None:
            raise RuntimeError('The generation job could not be loaded')
        status = job['status']
        if not created:
            if status in _ACTIVE_STATUSES or (status == JobStatus.SUCCEEDED.value and not retry_succeeded):
                return None
            if status in _RETRYABLE_STATUSES or (retry_succeeded and status == JobStatus.SUCCEEDED.value):
                with job_transaction(db):
                    db.execute('UPDATE generation_jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=?',
                               (JobStatus.RECOVERY_REQUIRED.value, job_id, status))
                    record_event(db, job_id, 'recovery_required', {'previous_status': status, 'trace_id': trace_id})
            else:
                raise RuntimeError(f'Unsupported generation job state: {status}')
        attempt = lease_next_job(db, worker_id, lease_seconds, job_id=job_id)
        if attempt is None:
            return None
        with job_transaction(db):
            db.execute('UPDATE generation_jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=?',
                       (JobStatus.RUNNING.value, job_id, JobStatus.LEASED.value))
            checkpoint(db, job_id, attempt['attempt_id'], 'start', {
                'stage': stage, 'action': action, 'trace_id': attempt['trace_id'],
            })
            record_event(db, job_id, 'job.started', {
                'stage': stage, 'action': action,
                'attempt_id': attempt['attempt_id'], 'trace_id': attempt['trace_id'],
            }, f'{attempt["attempt_id"]}:started')
        return job_id, attempt


async def _heartbeat_loop(user_id: int, attempt_id: int, lease_seconds: int, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        with workspace_db(user_id) as db:
            if not heartbeat(db, attempt_id, lease_seconds):
                raise LeaseLostError('The generation lease expired or is no longer owned by this worker')


def _record_project_refresh(db: sqlite3.Connection, job_id: str, attempt: dict, status: str) -> None:
    record_event(db, job_id, 'project.refresh', {
        'status': status, 'attempt_id': attempt['attempt_id'],
    }, f'{attempt["attempt_id"]}:project.refresh')


def _mark_cancelling(user_id: int, job_id: str, attempt: dict) -> None:
    with workspace_db(user_id) as db:
        with job_transaction(db):
            db.execute('UPDATE generation_jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=?',
                       (JobStatus.CANCELLING.value, job_id, JobStatus.CANCEL_REQUESTED.value))
            record_event(db, job_id, 'cancelling', {'attempt_id': attempt['attempt_id']},
                         f'{attempt["attempt_id"]}:cancelling')


def _cancel_attempt(user_id: int, project_id: str, job_id: str, attempt: dict, message: str) -> None:
    with workspace_db(user_id) as db:
        with job_transaction(db):
            complete_attempt(db, attempt['attempt_id'], JobStatus.CANCELLED.value, 'cancelled')
            checkpoint(db, job_id, attempt['attempt_id'], 'cancelled', {'reason': message})
            record_event(db, job_id, 'cancelled', {'reason': message}, f'{attempt["attempt_id"]}:cancelled:event')
            _record_project_refresh(db, job_id, attempt, 'cancelled')
            _project_error(db, project_id, message)


def _fail_attempt(user_id: int, job_id: str, attempt: dict, exc: BaseException) -> None:
    with workspace_db(user_id) as db:
        with job_transaction(db):
            complete_attempt(db, attempt['attempt_id'], JobStatus.FAILED.value, type(exc).__name__)
            checkpoint(db, job_id, attempt['attempt_id'], 'failed', {'error': str(exc)[:2000]})
            record_event(db, job_id, 'failed', {
                'failure_type': type(exc).__name__, 'error': str(exc)[:2000],
            }, f'{attempt["attempt_id"]}:failed')
            _record_project_refresh(db, job_id, attempt, 'failed')


async def run_generation_job(
    user_id: int,
    project_id: str,
    stage: str,
    action: str,
    input_data: dict,
    operation_factory: Callable[[], Awaitable[None]],
    worker_id: str | None = None,
    lease_seconds: int = 60,
    heartbeat_interval: float | None = None,
    retry_succeeded: bool = False,
) -> bool:
    """Run one leased attempt; return False when an equivalent job already owns the work."""
    if lease_seconds <= 0:
        raise ValueError('lease_seconds must be positive')
    interval = heartbeat_interval if heartbeat_interval is not None else min(15.0, max(0.1, lease_seconds / 3))
    if interval <= 0:
        raise ValueError('heartbeat_interval must be positive')
    input_hash = canonical_input_hash(input_data)
    trace_id = uuid.uuid4().hex
    worker_id = worker_id or f'local-{uuid.uuid4().hex}'
    prepared = _prepare_attempt(
        user_id, project_id, stage, action, input_hash, trace_id, worker_id, lease_seconds, retry_succeeded,
    )
    if prepared is None:
        return False
    job_id, attempt = prepared
    cancellation = register_job(job_id)
    with workspace_db(user_id) as db:
        if get_job(db, job_id)['status'] in {JobStatus.CANCEL_REQUESTED.value, JobStatus.CANCELLING.value}:
            cancellation.set()
    snapshot = capture_attempt_snapshot(user_id, project_id, job_id, attempt['attempt_id'], action, input_data)
    context = JobContext(
        user_id=user_id, project_id=project_id, job_id=job_id,
        attempt_id=attempt['attempt_id'], trace_id=attempt['trace_id'], cancellation=cancellation,
    )
    context_token = activate_job_context(context)
    operation = asyncio.create_task(operation_factory())
    cancellation_waiter = asyncio.create_task(cancellation.wait())
    heartbeat_task = asyncio.create_task(_heartbeat_loop(user_id, attempt['attempt_id'], lease_seconds, interval))
    try:
        done, _pending = await asyncio.wait(
            {operation, cancellation_waiter, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        if operation not in done and cancellation_waiter in done:
            _mark_cancelling(user_id, job_id, attempt)
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            rollback_attempt_snapshot(snapshot)
            _cancel_attempt(user_id, project_id, job_id, attempt, 'Generation cancelled. Retry this stage.')
            return True
        if operation not in done and heartbeat_task in done:
            await heartbeat_task
        await operation
        with workspace_db(user_id) as db:
            with job_transaction(db):
                job = get_job(db, job_id)
                cancelled = job['status'] in {JobStatus.CANCEL_REQUESTED.value, JobStatus.CANCELLING.value}
                if not cancelled:
                    project = db.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()
                    if project is None or project['status'] == 'error':
                        complete_attempt(db, attempt['attempt_id'], JobStatus.FAILED.value, 'generation_failed')
                        checkpoint(db, job_id, attempt['attempt_id'], 'failed', {'reason': 'Project generation failed'})
                        record_event(db, job_id, 'failed', {'reason': 'Project generation failed'},
                                     f'{attempt["attempt_id"]}:failed')
                        _record_project_refresh(db, job_id, attempt, 'failed')
                        return True
                    finalize_job(db, attempt, input_hash)
                    record_event(db, job_id, 'job.succeeded', {
                        'stage': stage, 'action': action, 'attempt_id': attempt['attempt_id'],
                    }, f'{attempt["attempt_id"]}:succeeded')
                    _record_project_refresh(db, job_id, attempt, 'succeeded')
                    checkpoint(db, job_id, attempt['attempt_id'], 'end', {
                        'stage': stage, 'action': action, 'trace_id': attempt['trace_id'],
                    })
        if cancelled:
            _mark_cancelling(user_id, job_id, attempt)
            rollback_attempt_snapshot(snapshot)
            _cancel_attempt(user_id, project_id, job_id, attempt, 'Generation cancelled. Retry this stage.')
            return True
        return True
    except JobCancelledError:
        _mark_cancelling(user_id, job_id, attempt)
        rollback_attempt_snapshot(snapshot)
        _cancel_attempt(user_id, project_id, job_id, attempt, 'Generation cancelled. Retry this stage.')
        return True
    except asyncio.CancelledError:
        operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        rollback_attempt_snapshot(snapshot)
        _cancel_attempt(user_id, project_id, job_id, attempt, 'Generation stopped. Retry this stage.')
        raise
    except Exception as exc:
        if not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        _fail_attempt(user_id, job_id, attempt, exc)
        raise
    finally:
        for task in (cancellation_waiter, heartbeat_task):
            task.cancel()
        await asyncio.gather(cancellation_waiter, heartbeat_task, return_exceptions=True)
        if cancellation_event(job_id) is cancellation:
            clear_job(job_id)
        discard_attempt_snapshot(snapshot)
        reset_job_context(context_token)
