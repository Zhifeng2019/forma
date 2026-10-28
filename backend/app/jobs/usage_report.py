"""Owner-scoped, redacted tool-run and model-usage aggregation."""

from datetime import datetime, timezone
import json

from ..database import workspace_db
from .redaction import redact_metadata, redact_output

TERMINAL_JOB_STATUSES = {'cancelled', 'succeeded', 'failed', 'dead_letter'}


def _time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _duration(started_at, ended_at, provenance):
    recorded = provenance.get('duration_ms')
    if isinstance(recorded, int) and not isinstance(recorded, bool) and recorded >= 0:
        return recorded
    started, ended = _time(started_at), _time(ended_at)
    if not started or not ended:
        return 0
    return max(0, round((ended - started).total_seconds() * 1000))


def _availability(statuses):
    if not statuses or all(status == 'unavailable' for status in statuses):
        return 'unavailable'
    if all(status == 'reported' for status in statuses):
        return 'reported'
    return 'partial'


def _cost_status(statuses):
    if any(status in {'estimated', 'partial'} for status in statuses):
        return 'estimated' if all(status == 'estimated' for status in statuses) else 'partial'
    return 'unknown'


def _sum_known(values):
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _usage(row):
    if not row:
        return None
    metadata = redact_metadata(json.loads(row['metadata'] or '{}'))
    status = row['usage_status'] or 'unavailable'
    observed = metadata.get('observed_tokens', {}) if isinstance(metadata, dict) else {}
    input_tokens = observed.get('input') if 'input' in observed else (
        row['input_tokens'] if status != 'unavailable' else None
    )
    output_tokens = observed.get('output') if 'output' in observed else (
        row['output_tokens'] if status != 'unavailable' else None
    )
    total_tokens = observed.get('total') if 'total' in observed else row['total_tokens']
    cost_status = row['cost_status'] or 'unknown'
    return {
        'provider': row['provider'], 'model': row['model'],
        'provider_request_id': row['provider_request_id'], 'finish_reason': row['finish_reason'],
        'latency_ms': row['latency_ms'], 'usage_status': status,
        'input_tokens': input_tokens, 'output_tokens': output_tokens, 'total_tokens': total_tokens,
        'cost_status': cost_status,
        'estimated_cost': row['estimated_cost'] if cost_status == 'estimated' else None,
        'currency': row['currency'], 'input_price_per_million': row['input_price_per_million'],
        'output_price_per_million': row['output_price_per_million'], 'metadata': metadata,
    }


def _tool_run(row, job, usage):
    provenance = redact_metadata(json.loads(row['provenance'] or '{}'))
    status = row['status']
    ended_at = row['ended_at']
    if status == 'running' and job['status'] in TERMINAL_JOB_STATUSES:
        status = 'cancelled' if job['status'] == 'cancelled' else 'failed'
        ended_at = job['updated_at']
        provenance['reported_closure'] = 'terminal_job'
    duration = _duration(row['started_at'], ended_at, provenance)
    if status == 'running':
        duration = _duration(row['started_at'], datetime.now(timezone.utc).isoformat(), provenance)
    return {
        'id': row['id'], 'attempt_id': row['attempt_id'],
        'tool_name': row['tool_name'], 'tool_version': row['tool_version'],
        'input_hash': row['input_hash'], 'output_ref': redact_output(row['output_ref'] or ''),
        'status': status, 'retry_count': row['retry_count'],
        'started_at': row['started_at'], 'ended_at': ended_at, 'duration_ms': duration,
        'provenance': provenance, 'usage': _usage(usage),
    }


def _aggregate(job, runs):
    statuses = [run['usage']['usage_status'] for run in runs if run['usage']]
    costs = [run['usage']['cost_status'] for run in runs if run['usage']]
    estimates = [run['usage']['estimated_cost'] for run in runs
                 if run['usage'] and run['usage']['estimated_cost'] is not None]
    currencies = sorted({run['usage']['currency'] for run in runs
                         if run['usage'] and run['usage']['estimated_cost'] is not None
                         and run['usage']['currency']})
    health_runs = [run for run in runs if run['tool_name'] == 'runtime.health']
    latest_health = health_runs[-1]['status'] if health_runs else None
    runtime_health = (
        'healthy' if latest_health == 'succeeded' else 'starting' if latest_health == 'running'
        else 'stopped' if latest_health == 'cancelled' else 'degraded' if latest_health else 'unavailable'
    )
    provenance = [run['provenance'] for run in runs]
    return {
        'job_id': job['id'], 'stage': job['stage'], 'status': job['status'],
        'current_attempt': job['current_attempt'], 'trace_id': job['trace_id'],
        'created_at': job['created_at'], 'updated_at': job['updated_at'],
        'tool_run_count': len(runs), 'request_count': len(statuses),
        'retry_count': sum(run['retry_count'] for run in runs),
        'duration_ms': sum(run['duration_ms'] for run in runs),
        'token_status': _availability(statuses),
        'input_tokens': _sum_known([run['usage']['input_tokens'] for run in runs if run['usage']]),
        'output_tokens': _sum_known([run['usage']['output_tokens'] for run in runs if run['usage']]),
        'total_tokens': _sum_known([run['usage']['total_tokens'] for run in runs if run['usage']]),
        'cost_status': _cost_status(costs),
        'estimated_cost': round(sum(estimates), 12) if estimates else None,
        'currency': currencies[0] if len(currencies) == 1 else None, 'currencies': currencies,
        'runtime_health': runtime_health,
        'spec_hashes': sorted({item['spec_hash'] for item in provenance if item.get('spec_hash')}),
        'source_hashes': sorted({item['source_hash'] for item in provenance if item.get('source_hash')}),
        'tool_runs': runs,
    }


def _summary(jobs):
    health = {job['runtime_health'] for job in jobs}
    runtime_health = (
        'degraded' if 'degraded' in health else 'starting' if 'starting' in health
        else 'healthy' if 'healthy' in health else 'stopped' if 'stopped' in health and len(health) == 1
        else 'unavailable'
    )
    estimates = [job['estimated_cost'] for job in jobs if job['estimated_cost'] is not None]
    currencies = sorted({currency for job in jobs for currency in job['currencies']})
    return {
        'job_count': len(jobs), 'tool_run_count': sum(job['tool_run_count'] for job in jobs),
        'request_count': sum(job['request_count'] for job in jobs),
        'retry_count': sum(job['retry_count'] for job in jobs),
        'duration_ms': sum(job['duration_ms'] for job in jobs),
        'token_status': _availability([job['token_status'] for job in jobs]),
        'input_tokens': _sum_known([job['input_tokens'] for job in jobs]),
        'output_tokens': _sum_known([job['output_tokens'] for job in jobs]),
        'total_tokens': _sum_known([job['total_tokens'] for job in jobs]),
        'cost_status': _cost_status([job['cost_status'] for job in jobs]),
        'estimated_cost': round(sum(estimates), 12) if estimates else None,
        'currency': currencies[0] if len(currencies) == 1 else None, 'currencies': currencies,
        'runtime_health': runtime_health,
        'spec_hashes': sorted({value for job in jobs for value in job['spec_hashes']}),
        'source_hashes': sorted({value for job in jobs for value in job['source_hashes']}),
    }


def project_usage(user_id: int, project_id: str) -> dict:
    with workspace_db(user_id) as db:
        jobs = db.execute(
            'SELECT * FROM generation_jobs WHERE project_id=? ORDER BY created_at,id', (project_id,),
        ).fetchall()
        tool_rows = db.execute('''SELECT tool_runs.* FROM tool_runs JOIN generation_jobs ON generation_jobs.id=tool_runs.job_id
            WHERE generation_jobs.project_id=? ORDER BY tool_runs.started_at,tool_runs.rowid''', (project_id,)).fetchall()
        usage_rows = db.execute('''SELECT usage_ledger.* FROM usage_ledger
            JOIN generation_jobs ON generation_jobs.id=usage_ledger.job_id
            WHERE generation_jobs.project_id=? ORDER BY usage_ledger.id''', (project_id,)).fetchall()
    usage_by_tool = {row['tool_run_id']: row for row in usage_rows}
    runs_by_job = {}
    for row in tool_rows:
        runs_by_job.setdefault(row['job_id'], []).append(row)
    job_views = [
        _aggregate(job, [
            _tool_run(row, job, usage_by_tool.get(row['id']))
            for row in runs_by_job.get(job['id'], [])
        ])
        for job in jobs
    ]
    return {
        'schema_version': '1.0', 'project_id': project_id,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'summary': _summary(job_views), 'jobs': job_views,
    }
