"""Shared, attempt-owned tool-run envelopes with redacted provenance."""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
import sqlite3
import time
import uuid

from ..database import workspace_db
from .context import current_job_context
from .idempotency import canonical_input_hash
from .redaction import redact_metadata, redact_output

TERMINAL_STATUSES = {'passed', 'succeeded', 'failed', 'cancelled', 'blocked', 'skipped'}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ToolRunEnvelope:
    id: str
    user_id: int
    job_id: str
    attempt_id: int
    tool_name: str
    tool_version: str
    input_hash: str
    output_ref: str
    status: str
    retry_count: int
    started_at: str
    ended_at: str | None
    duration_ms: int
    provenance: dict
    monotonic_started: float = field(default_factory=time.monotonic, repr=False, compare=False)


def _save(run: ToolRunEnvelope) -> None:
    with workspace_db(run.user_id) as db:
        db.execute('''INSERT INTO tool_runs(
            id,job_id,attempt_id,tool_name,tool_version,input_hash,output_ref,status,retry_count,
            started_at,ended_at,provenance)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (
            run.id, run.job_id, run.attempt_id, run.tool_name, run.tool_version, run.input_hash,
            run.output_ref, run.status, run.retry_count, run.started_at, run.ended_at,
            json.dumps(run.provenance, sort_keys=True, default=str),
        ))


def start_tool_run(
    tool_name: str,
    tool_version: str,
    input_data,
    *,
    retry_count: int = 0,
    provenance: dict | None = None,
    output_ref: str | None = None,
    spec_hash: str | None = None,
    source_hash: str | None = None,
    user_id: int | None = None,
    job_id: str | None = None,
    attempt_id: int | None = None,
) -> ToolRunEnvelope | None:
    """Start one persisted tool span; detached contexts remain uninstrumented."""
    context = current_job_context()
    user_id = user_id if user_id is not None else context.user_id if context else None
    job_id = job_id or (context.job_id if context else None)
    attempt_id = attempt_id if attempt_id is not None else context.attempt_id if context else None
    if user_id is None or not job_id or attempt_id is None:
        return None
    try:
        with workspace_db(user_id) as db:
            owned = db.execute('SELECT id FROM job_attempts WHERE id=? AND job_id=?', (attempt_id, job_id)).fetchone()
    except sqlite3.OperationalError as exc:
        if 'no such table: job_attempts' not in str(exc):
            raise
        return None
    if not owned:
        return None
    if not tool_name.strip() or not tool_version.strip():
        raise ValueError('Tool name and version are required')
    if retry_count < 0:
        raise ValueError('retry_count must be non-negative')
    run_id = uuid.uuid4().hex
    metadata = dict(provenance or {})
    if spec_hash is not None:
        metadata['spec_hash'] = spec_hash
    if source_hash is not None:
        metadata['source_hash'] = source_hash
    run = ToolRunEnvelope(
        id=run_id, user_id=user_id, job_id=job_id, attempt_id=attempt_id,
        tool_name=tool_name.strip()[:200], tool_version=tool_version.strip()[:200],
        input_hash=canonical_input_hash({'value': redact_metadata(input_data)}),
        output_ref=redact_output(output_ref or f'tool-run://{run_id}/output')[:4000],
        status='running', retry_count=retry_count, started_at=utc_now(), ended_at=None,
        duration_ms=0, provenance=redact_metadata(metadata),
    )
    _save(run)
    return run


def finish_tool_run(
    run: ToolRunEnvelope | None,
    status: str,
    *,
    output_ref: str | None = None,
    provenance: dict | None = None,
    error: str | None = None,
    ended_at: str | None = None,
    duration_ms: int | None = None,
) -> ToolRunEnvelope | None:
    if run is None:
        return None
    if run.status != 'running':
        raise ValueError('Only a running tool span can be finished')
    if status not in TERMINAL_STATUSES:
        raise ValueError(f'Unsupported tool-run status: {status}')
    metadata = {**run.provenance, **redact_metadata(provenance or {})}
    if error:
        metadata['error'] = redact_output(str(error))[:2000]
    duration = duration_ms if duration_ms is not None else max(
        0, round((time.monotonic() - run.monotonic_started) * 1000),
    )
    if duration < 0:
        raise ValueError('duration_ms must be non-negative')
    metadata['duration_ms'] = duration
    finished = replace(
        run, status=status, output_ref=redact_output(output_ref or run.output_ref)[:4000],
        ended_at=ended_at or utc_now(), duration_ms=duration, provenance=metadata,
    )
    with workspace_db(run.user_id) as db:
        db.execute('''UPDATE tool_runs SET output_ref=?,status=?,ended_at=?,provenance=? WHERE id=?''', (
            finished.output_ref, status, finished.ended_at,
            json.dumps(metadata, sort_keys=True, default=str), run.id,
        ))
    return finished


def close_open_tool_runs(user_id: int, job_id: str, attempt_id: int, status: str, reason: str) -> int:
    """Close abandoned spans without changing already-terminal tool records."""
    if status not in {'cancelled', 'failed'}:
        raise ValueError('Interrupted tool runs must close as cancelled or failed')
    ended_at = utc_now()
    closed = 0
    with workspace_db(user_id) as db:
        rows = db.execute(
            "SELECT id,started_at,provenance FROM tool_runs WHERE job_id=? AND attempt_id=? AND status='running'",
            (job_id, attempt_id),
        ).fetchall()
        for row in rows:
            provenance = json.loads(row['provenance'] or '{}')
            try:
                started = datetime.fromisoformat(row['started_at'].replace('Z', '+00:00'))
                ended = datetime.fromisoformat(ended_at.replace('Z', '+00:00'))
                duration_ms = max(0, round((ended - started).total_seconds() * 1000))
            except (TypeError, ValueError):
                duration_ms = 0
            provenance.update({'duration_ms': duration_ms, 'closure_reason': reason})
            db.execute(
                'UPDATE tool_runs SET status=?,ended_at=?,provenance=? WHERE id=? AND status=\'running\'',
                (status, ended_at, json.dumps(provenance, sort_keys=True), row['id']),
            )
            closed += 1
    return closed
