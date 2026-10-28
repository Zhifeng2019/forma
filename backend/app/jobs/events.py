"""Versioned, content-safe job event envelopes and bounded SSE replay."""

import asyncio
from datetime import datetime, timezone
import json
import sqlite3

from ..config import ROOT, settings
from ..database import workspace_db
from .processes import redact_output

EVENT_SCHEMA_VERSION = '1.0'
EVENT_TYPES = {
    'checkpoint': 'job.progress',
    'cancel_requested': 'job.cancel_requested',
    'cancelling': 'job.cancelling',
    'cancelled': 'job.cancelled',
    'failed': 'job.failed',
    'recovery_required': 'job.recovery_required',
    'verification_report': 'verification.report',
    'project.refresh': 'project.refresh',
}


def timestamp(value: str | None = None) -> str:
    if not value:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromisoformat(value.replace(' ', 'T')).replace(tzinfo=timezone.utc).isoformat()


def safe_payload(value):
    if isinstance(value, dict):
        return {str(key): safe_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_payload(item) for item in value]
    if isinstance(value, str):
        text = value.replace(str(settings.data_path), '<workspace>').replace(str(ROOT.parent), '<studio>')
        return redact_output(text)[:4000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:4000]


def event_envelope(row: sqlite3.Row) -> dict:
    payload = json.loads(row['payload'] or '{}')
    dedupe_key = row['dedupe_key'] or ''
    attempt_text = dedupe_key.split(':', 1)[0]
    attempt_id = int(attempt_text) if attempt_text.isdigit() else None
    event_type = EVENT_TYPES.get(row['event_type'], row['event_type'])
    return {
        'schema_version': EVENT_SCHEMA_VERSION,
        'id': row['id'],
        'job_id': row['job_id'],
        'attempt_id': attempt_id,
        'type': event_type,
        'timestamp': timestamp(row['created_at']),
        'payload': safe_payload(payload),
    }


def high_watermark(db: sqlite3.Connection, project_id: str) -> int:
    row = db.execute('''SELECT COALESCE(MAX(job_events.id),0) AS cursor FROM job_events
        JOIN generation_jobs ON generation_jobs.id=job_events.job_id
        WHERE generation_jobs.project_id=?''', (project_id,)).fetchone()
    return row['cursor']


def replay_events(db: sqlite3.Connection, project_id: str, after: int, limit: int) -> list[dict]:
    rows = db.execute('''SELECT job_events.* FROM job_events
        JOIN generation_jobs ON generation_jobs.id=job_events.job_id
        WHERE generation_jobs.project_id=? AND job_events.id>? ORDER BY job_events.id LIMIT ?''',
        (project_id, after, limit)).fetchall()
    return [event_envelope(row) for row in rows]


def sse_frame(event: dict) -> str:
    return (f'id: {event["id"]}\nevent: {event["type"]}\n'
            f'data: {json.dumps(event, ensure_ascii=False, separators=(",", ":"))}\n\n')


def replay_frames(events: list[dict], project_id: str, after: int):
    yield ': heartbeat\n\n'
    yield 'retry: 1500\n\n'
    for event in events:
        yield sse_frame(event)
    cursor = events[-1]['id'] if events else after
    complete = {
        'schema_version': EVENT_SCHEMA_VERSION,
        'id': cursor,
        'job_id': project_id,
        'attempt_id': None,
        'type': 'stream.complete',
        'timestamp': timestamp(),
        'payload': {'count': len(events), 'high_watermark': cursor},
    }
    yield sse_frame(complete)


async def follow_frames(
    user_id: int, project_id: str, after: int, limit: int, heartbeat_seconds: float,
    poll_seconds: float = 0.25,
):
    """Tail persisted events without retaining a database connection across awaits."""
    yield ': heartbeat\n\n'
    yield 'retry: 1500\n\n'
    cursor = after
    idle_seconds = 0.0
    while True:
        with workspace_db(user_id) as db:
            events = replay_events(db, project_id, cursor, limit)
        for event in events:
            cursor = event['id']
            yield sse_frame(event)
        if not events and idle_seconds >= heartbeat_seconds:
            yield ': heartbeat\n\n'
            idle_seconds = 0.0
        delay = min(poll_seconds, heartbeat_seconds)
        await asyncio.sleep(delay)
        idle_seconds += delay
