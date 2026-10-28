"""Guarded worker leases, heartbeat, recovery, and finalization."""

from datetime import datetime, timedelta, timezone
import sqlite3

from .cancellation import cancel_job
from .models import JobStatus, LeaseLostError, StaleJobError
from .transactions import job_transaction

LEASE_STATUSES = (JobStatus.QUEUED.value, JobStatus.RETRY_SCHEDULED.value, JobStatus.RECOVERY_REQUIRED.value)
TERMINAL_STATUSES = (JobStatus.SUCCEEDED.value, JobStatus.CANCELLED.value, JobStatus.DEAD_LETTER.value, JobStatus.FAILED.value)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lease_next_job(
    db: sqlite3.Connection,
    worker_id: str,
    lease_seconds: int = 60,
    job_id: str | None = None,
) -> dict | None:
    """Lease the next eligible job, or a specific job for an API-triggered run."""
    with job_transaction(db):
        placeholders = ','.join('?' for _ in LEASE_STATUSES)
        if job_id is None:
            job = db.execute(f'''SELECT * FROM generation_jobs
                WHERE status IN ({placeholders})
                ORDER BY created_at,id LIMIT 1''', LEASE_STATUSES).fetchone()
        else:
            job = db.execute(f'''SELECT * FROM generation_jobs
                WHERE id=? AND status IN ({placeholders})''', (job_id, *LEASE_STATUSES)).fetchone()
        if not job:
            return None
        now = datetime.now(timezone.utc)
        started = now.isoformat()
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        attempt_number = job['current_attempt'] + 1
        db.execute('UPDATE generation_jobs SET status=?,current_attempt=?,updated_at=? WHERE id=?',
                   (JobStatus.LEASED.value, attempt_number, started, job['id']))
        cursor = db.execute('''INSERT INTO job_attempts(
            job_id,attempt_number,worker_id,lease_expires_at,heartbeat_at,started_at)
            VALUES(?,?,?,?,?,?)''',
            (job['id'], attempt_number, worker_id, expires, started, started))
        return {
            'job_id': job['id'], 'attempt_id': cursor.lastrowid,
            'attempt_number': attempt_number, 'stage': job['stage'],
            'input_hash': job['input_hash'], 'trace_id': job['trace_id'],
            'worker_id': worker_id, 'lease_expires_at': expires,
        }


def heartbeat(db: sqlite3.Connection, attempt_id: int, lease_seconds: int = 60) -> bool:
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(seconds=lease_seconds)).isoformat()
    with job_transaction(db):
        cursor = db.execute('''UPDATE job_attempts SET heartbeat_at=?,lease_expires_at=?
            WHERE id=? AND ended_at IS NULL AND lease_expires_at>?''',
            (now.isoformat(), expires, attempt_id, now.isoformat()))
        return cursor.rowcount == 1


def complete_attempt(db: sqlite3.Connection, attempt_id: int, status: str, failure_code: str | None = None) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f'Unsupported terminal job status: {status}')
    with job_transaction(db):
        attempt = db.execute('SELECT job_id FROM job_attempts WHERE id=? AND ended_at IS NULL', (attempt_id,)).fetchone()
        if not attempt:
            raise LeaseLostError('The worker no longer owns this attempt')
        ended = utc_now()
        db.execute('UPDATE job_attempts SET ended_at=?,failure_code=? WHERE id=?', (ended, failure_code, attempt_id))
        db.execute('UPDATE generation_jobs SET status=?,updated_at=? WHERE id=?',
                   (status, ended, attempt['job_id']))


def finalize_job(db: sqlite3.Connection, attempt: dict, expected_input_hash: str) -> None:
    if attempt['input_hash'] != expected_input_hash:
        raise StaleJobError('Job input changed before finalization')
    with job_transaction(db):
        current = db.execute('''SELECT generation_jobs.input_hash,generation_jobs.status,job_attempts.worker_id
            FROM generation_jobs JOIN job_attempts ON job_attempts.job_id=generation_jobs.id
            WHERE job_attempts.id=? AND job_attempts.ended_at IS NULL''', (attempt['attempt_id'],)).fetchone()
        if not current or current['input_hash'] != expected_input_hash:
            raise StaleJobError('Job input changed before finalization')
        if current['worker_id'] != attempt['worker_id']:
            raise StaleJobError('The worker no longer owns this attempt')
        if current['status'] in {JobStatus.CANCEL_REQUESTED.value, JobStatus.CANCELLING.value, JobStatus.CANCELLED.value}:
            raise StaleJobError('Job was cancelled before finalization')
        if current['status'] not in {JobStatus.LEASED.value, JobStatus.RUNNING.value, JobStatus.WAITING_ON_TOOL.value, JobStatus.FINALIZING.value}:
            raise StaleJobError('Job is not active for finalization')
        complete_attempt(db, attempt['attempt_id'], JobStatus.SUCCEEDED.value)


def recover_expired_leases(db: sqlite3.Connection) -> int:
    now = utc_now()
    with job_transaction(db):
        expired = db.execute('SELECT id,job_id FROM job_attempts WHERE ended_at IS NULL AND lease_expires_at<=?', (now,)).fetchall()
        for attempt in expired:
            db.execute('UPDATE job_attempts SET ended_at=?,failure_code=? WHERE id=?',
                       (now, 'lease_expired', attempt['id']))
            db.execute('UPDATE generation_jobs SET status=?,updated_at=? WHERE id=?',
                       (JobStatus.RECOVERY_REQUIRED.value, now, attempt['job_id']))
        return len(expired)


def request_cancellation(db: sqlite3.Connection, job_id: str) -> bool:
    inactive_statuses = {
        *TERMINAL_STATUSES, JobStatus.CANCEL_REQUESTED.value, JobStatus.CANCELLING.value,
    }
    with job_transaction(db):
        job = db.execute('SELECT status FROM generation_jobs WHERE id=?', (job_id,)).fetchone()
        requested = False
        if job and job['status'] not in inactive_statuses:
            placeholders = ','.join('?' for _ in inactive_statuses)
            cursor = db.execute(f'''UPDATE generation_jobs SET status=?,updated_at=?
                WHERE id=? AND status NOT IN ({placeholders})''',
                (JobStatus.CANCEL_REQUESTED.value, utc_now(), job_id, *inactive_statuses))
            requested = cursor.rowcount == 1
            if requested:
                db.execute('''INSERT OR IGNORE INTO job_events(job_id,event_type,payload,dedupe_key)
                    VALUES(?,?,?,?)''', (job_id, 'cancel_requested', '{}', 'cancel-requested'))
    cancel_job(job_id)
    return requested
