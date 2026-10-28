import asyncio
import json
import uuid

from fastapi.testclient import TestClient

from app.database import workspace_db
from app.jobs.leases import complete_attempt, lease_next_job
from app.jobs.models import JobCancelledError, JobStatus
from app.jobs.runner import run_generation_job
from app.jobs.service import create_job
from app.jobs.tool_runs import finish_tool_run, start_tool_run
from app.jobs.usage import record_observed_completion
from app.main import app
from test_event_replay import auth, make_project, register


class Response:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.status_code = 200

    def json(self):
        return self.payload


def usage_payload(prompt=100, completion=50):
    return {
        'id': 'request-1',
        'usage': {'prompt_tokens': prompt, 'completion_tokens': completion,
                  'total_tokens': prompt + completion},
        'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
    }


def test_usage_api_aggregates_attempts_and_protects_owner_and_secrets():
    with TestClient(app) as client:
        owner = register(client, 'usage-owner')
        other = register(client, 'usage-other')
        user_id = owner['user']['id']
        project_id = make_project(user_id)
        with workspace_db(user_id) as db:
            job_id, _ = create_job(db, project_id, 'build', uuid.uuid4().hex, 'advance-stage', uuid.uuid4().hex)
            first = lease_next_job(db, 'usage-first', job_id=job_id)
        run = start_tool_run(
            'provider.http', 'v1', {'request': 1}, spec_hash='spec-1', source_hash='source-1',
            user_id=user_id, job_id=job_id, attempt_id=first['attempt_id'],
        )
        run = finish_tool_run(run, 'succeeded', duration_ms=10)
        record_observed_completion(
            {'name': 'Usage Provider', 'model': 'model-1', 'input_price_per_million': 1,
             'output_price_per_million': 2, 'currency': 'USD'},
            Response(usage_payload()), run, response_format={'type': 'json_object'},
            request_reason='initial', reason_detail=None, retry_count=0,
        )
        with workspace_db(user_id) as db:
            complete_attempt(db, first['attempt_id'], JobStatus.FAILED.value, 'retry')
            db.execute("UPDATE generation_jobs SET status='recovery_required' WHERE id=?", (job_id,))
            second = lease_next_job(db, 'usage-second', job_id=job_id)
        failed = start_tool_run(
            'provider.http', 'v1', {'request': 2}, retry_count=1,
            provenance={'spec_hash': 'spec-1', 'source_hash': 'source-1', 'access_token': 'super-secret'},
            output_ref='https://user:pass@example.com/output?token=super-secret',
            user_id=user_id, job_id=job_id, attempt_id=second['attempt_id'],
        )
        failed = finish_tool_run(failed, 'failed', duration_ms=20)
        record_observed_completion(
            {'name': 'Usage Provider', 'model': 'model-1'}, Response({'choices': []}), failed,
            response_format={'type': 'json_object'}, request_reason='output_repair',
            reason_detail='invalid JSON', retry_count=1,
        )
        health = start_tool_run(
            'runtime.health', 'http.v1', {'project_id': project_id},
            provenance={'spec_hash': 'spec-1', 'source_hash': 'source-1'},
            user_id=user_id, job_id=job_id, attempt_id=second['attempt_id'],
        )
        finish_tool_run(health, 'succeeded', duration_ms=5)
        with workspace_db(user_id) as db:
            complete_attempt(db, second['attempt_id'], JobStatus.SUCCEEDED.value)
            db.execute("UPDATE generation_jobs SET status='succeeded' WHERE id=?", (job_id,))
            create_job(db, project_id, 'review', uuid.uuid4().hex, 'advance-stage', uuid.uuid4().hex)

        response = client.get(f'/api/projects/{project_id}/usage', headers=auth(owner['token']))
        assert response.status_code == 200, response.text
        payload = response.json()
        summary = payload['summary']
        assert summary['job_count'] == 2 and summary['tool_run_count'] == 3
        assert summary['request_count'] == 2 and summary['retry_count'] == 1
        assert summary['duration_ms'] == 35
        assert summary['token_status'] == 'partial'
        assert (summary['input_tokens'], summary['output_tokens'], summary['total_tokens']) == (100, 50, 150)
        assert summary['cost_status'] == 'partial' and summary['estimated_cost'] == 0.0002
        assert summary['runtime_health'] == 'healthy'
        assert summary['spec_hashes'] == ['spec-1'] and summary['source_hashes'] == ['source-1']
        job = next(item for item in payload['jobs'] if item['job_id'] == job_id)
        assert job['current_attempt'] == 2 and job['cost_status'] == 'partial'
        local = next(item for item in payload['jobs'] if item['job_id'] != job_id)
        assert local['token_status'] == 'unavailable' and local['estimated_cost'] is None
        assert client.get(f'/api/projects/{project_id}/usage', headers=auth(other['token'])).status_code == 404
        serialized = json.dumps(payload)
        assert 'super-secret' not in serialized and 'user:pass' not in serialized
        assert 'token=super-secret' not in serialized


def test_cancelled_and_legacy_spans_close_in_storage_and_usage_view():
    with TestClient(app) as client:
        account = register(client, 'usage-cancelled')
        user_id = account['user']['id']
        project_id = make_project(user_id)
        seen = {}

        async def operation():
            run = start_tool_run('test.span', 'v1', {'operation': 'cancel'})
            seen.update(job_id=run.job_id, attempt_id=run.attempt_id, run_id=run.id)
            raise JobCancelledError('cancel during tool')

        asyncio.run(run_generation_job(
            user_id, project_id, 'build', 'advance-stage', {'version': 0}, operation,
        ))
        with workspace_db(user_id) as db:
            row = db.execute('SELECT * FROM tool_runs WHERE id=?', (seen['run_id'],)).fetchone()
        assert row['status'] == 'cancelled' and row['ended_at']
        assert json.loads(row['provenance'])['closure_reason'] == 'job_cancelled'
        legacy = start_tool_run(
            'legacy.running', 'v1', {}, user_id=user_id,
            job_id=seen['job_id'], attempt_id=seen['attempt_id'],
        )
        assert legacy is not None and legacy.status == 'running'
        response = client.get(f'/api/projects/{project_id}/usage', headers=auth(account['token']))
        assert response.status_code == 200, response.text
        job = response.json()['jobs'][0]
        assert job['status'] == 'cancelled' and job['tool_run_count'] == 2
        assert all(run['status'] == 'cancelled' and run['ended_at'] for run in job['tool_runs'])
        assert response.json()['summary']['token_status'] == 'unavailable'
        assert response.json()['summary']['cost_status'] == 'unknown'
