"""Deterministic verification report construction and publish evaluation."""

import json


def check_result(
    check: dict,
    status: str,
    tool_run_id: str,
    duration_ms: int,
    error: str | None = None,
    output_ref: str | None = None,
    diagnostic_ref: str | None = None,
) -> dict:
    if status not in {'passed', 'failed', 'blocked', 'skipped'}:
        raise ValueError(f'Unsupported verification result status: {status}')
    result = {
        'id': check['id'], 'kind': check['kind'], 'target': check['target'],
        'status': status, 'required': check['required'], 'mutates': check['mutates'],
        'tool_run_id': tool_run_id, 'duration_ms': duration_ms,
        'output_ref': output_ref or f'{check["file"]}#{check["test"]}',
    }
    if error:
        result['error'] = error[-2000:]
    if diagnostic_ref:
        result['diagnostic_ref'] = diagnostic_ref
    return result


def can_publish(results: list[dict], complete_coverage: bool = True) -> bool:
    if not complete_coverage:
        return False
    by_id = {result['id']: result for result in results}
    if any(result['required'] and result['status'] != 'passed' for result in results):
        return False
    if by_id.get('build.production', {}).get('status') != 'passed':
        return False
    if 'api.health' in by_id and by_id['api.health']['status'] != 'passed':
        return False
    return True


def build_report(
    project_id: str,
    version: int,
    job_id: str,
    attempt_id: int,
    spec_hash: str,
    source_hash: str,
    started_at: str,
    ended_at: str,
    duration_ms: int,
    results: list[dict],
    complete_coverage: bool = True,
) -> dict:
    required_failures = [result['id'] for result in results if result['required'] and result['status'] != 'passed']
    optional_failures = [result['id'] for result in results if not result['required'] and result['status'] != 'passed']
    status = 'failed' if required_failures else 'passed_with_warnings' if optional_failures else 'passed'
    publishable = can_publish(results, complete_coverage)
    return {
        'schema_version': '1.0',
        'project_id': project_id,
        'version': version,
        'job_id': job_id,
        'attempt_id': attempt_id,
        'spec_hash': spec_hash,
        'source_hash': source_hash,
        'status': status,
        'can_publish': publishable,
        'complete_coverage': complete_coverage,
        'summary': {
            'total': len(results),
            'passed': sum(result['status'] == 'passed' for result in results),
            'failed': sum(result['status'] == 'failed' for result in results),
            'blocked': sum(result['status'] == 'blocked' for result in results),
            'skipped': sum(result['status'] == 'skipped' for result in results),
            'required_failures': required_failures,
            'optional_failures': optional_failures,
        },
        'started_at': started_at,
        'ended_at': ended_at,
        'duration_ms': duration_ms,
        'checks': sorted(results, key=lambda result: result['id']),
    }


def report_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
