"""Small, transaction-safe job creation and event helpers."""

import json
import sqlite3
import uuid

from .idempotency import job_idempotency_key
from .models import IdempotencyConflictError, JobStatus
from .transactions import job_transaction


def create_job(
    db: sqlite3.Connection,
    project_id: str,
    stage: str,
    input_hash: str,
    action: str,
    trace_id: str,
) -> tuple[str, bool]:
    idempotency_key = job_idempotency_key(project_id, action, input_hash)
    with job_transaction(db):
        existing = db.execute(
            'SELECT id,stage,input_hash FROM generation_jobs WHERE project_id=? AND idempotency_key=?',
            (project_id, idempotency_key),
        ).fetchone()
        if existing:
            if existing['stage'] != stage or existing['input_hash'] != input_hash:
                raise IdempotencyConflictError('The idempotency key belongs to a different job input')
            return existing['id'], False
        job_id = uuid.uuid4().hex
        db.execute('''INSERT INTO generation_jobs(
            id,project_id,stage,status,input_hash,idempotency_key,trace_id)
            VALUES(?,?,?,?,?,?,?)''',
            (job_id, project_id, stage, JobStatus.QUEUED.value, input_hash, idempotency_key, trace_id))
        return job_id, True


def get_job(db: sqlite3.Connection, job_id: str) -> dict | None:
    row = db.execute('SELECT * FROM generation_jobs WHERE id=?', (job_id,)).fetchone()
    return dict(row) if row else None


def record_event(
    db: sqlite3.Connection,
    job_id: str,
    event_type: str,
    payload: dict | None = None,
    dedupe_key: str | None = None,
) -> bool:
    cursor = db.execute(
        'INSERT OR IGNORE INTO job_events(job_id,event_type,payload,dedupe_key) VALUES(?,?,?,?)',
        (job_id, event_type, json.dumps(payload or {}, sort_keys=True), dedupe_key),
    )
    return cursor.rowcount == 1
