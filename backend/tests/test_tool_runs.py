import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

import httpx

from app import llm
from app.database import workspace_db
from app.jobs.context import JobContext, activate_job_context, reset_job_context
from app.jobs.leases import lease_next_job
from app.jobs.processes import run_process
from app.jobs.service import create_job
from app.jobs.tool_runs import finish_tool_run, start_tool_run
from app.security import encrypt_secret
from test_event_replay import make_project


def ownership(user_id):
    project_id = make_project(user_id)
    with workspace_db(user_id) as db:
        job_id, _ = create_job(db, project_id, 'build', uuid.uuid4().hex, 'advance-stage', uuid.uuid4().hex)
        attempt = lease_next_job(db, 'tool-run-test', job_id=job_id)
    return project_id, job_id, attempt


def activate(user_id, project_id, job_id, attempt):
    context = JobContext(
        user_id, project_id, job_id, attempt['attempt_id'], 'tool-run-trace', asyncio.Event(),
    )
    return activate_job_context(context)


def test_tool_run_envelope_records_timing_retry_and_safe_provenance():
    user_id = 960200
    _project_id, job_id, attempt = ownership(user_id)
    run = start_tool_run(
        'provider.http', 'v1',
        {'url': 'https://example.com/v1?api_key=super-secret', 'api_key': 'super-secret'},
        retry_count=2, provenance={'access_token': 'super-secret'},
        output_ref='https://user:pass@example.com/output?token=super-secret',
        spec_hash='spec-hash', source_hash='source-hash',
        user_id=user_id, job_id=job_id, attempt_id=attempt['attempt_id'],
    )
    assert run is not None and run.status == 'running'
    finished = finish_tool_run(run, 'succeeded', duration_ms=17)
    assert finished is not None
    with workspace_db(user_id) as db:
        row = db.execute('SELECT * FROM tool_runs WHERE id=?', (run.id,)).fetchone()
    assert row['job_id'] == job_id and row['attempt_id'] == attempt['attempt_id']
    assert row['tool_name'] == 'provider.http' and row['tool_version'] == 'v1'
    assert row['status'] == 'succeeded' and row['retry_count'] == 2
    assert row['started_at'] and row['ended_at']
    assert row['output_ref'] == 'https://example.com/output'
    provenance = json.loads(row['provenance'])
    assert provenance['spec_hash'] == 'spec-hash' and provenance['source_hash'] == 'source-hash'
    assert provenance['duration_ms'] == 17 and provenance['access_token'] == '<redacted>'
    assert 'super-secret' not in row['provenance'] and 'user:pass' not in row['output_ref']


def test_processes_persist_distinct_success_and_failure_spans():
    user_id = 960201
    project_id, job_id, attempt = ownership(user_id)

    async def scenario():
        token = activate(user_id, project_id, job_id, attempt)
        try:
            await run_process(
                [sys.executable, '-c', "print('safe')"], Path.cwd(), dict(os.environ), 5, 'test process',
            )
            await run_process(
                [sys.executable, '-c', 'import sys; sys.exit(3)'],
                Path.cwd(), dict(os.environ), 5, 'test process',
            )
        finally:
            reset_job_context(token)

    asyncio.run(scenario())
    with workspace_db(user_id) as db:
        rows = db.execute('SELECT * FROM tool_runs WHERE job_id=? ORDER BY rowid', (job_id,)).fetchall()
    assert len(rows) == 2 and len({row['id'] for row in rows}) == 2
    assert [row['status'] for row in rows] == ['succeeded', 'failed']
    assert [json.loads(row['provenance'])['returncode'] for row in rows] == [0, 3]
    assert all(row['tool_name'] == 'test process' and row['ended_at'] for row in rows)


def test_provider_fallback_preserves_each_http_attempt_without_prompt_storage(monkeypatch):
    user_id = 960202
    project_id, job_id, attempt = ownership(user_id)

    class Response:
        def __init__(self, status, content=''):
            self.status_code = status
            self.text = content

        def json(self):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': self.text}}]}

    class Client:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return Response(400, 'schema unsupported')
            return Response(200, '{"product":{}}')

    client = Client()
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: client)
    provider = {
        'name': 'Telemetry Provider', 'model': 'fixture-model',
        'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }

    async def scenario():
        token = activate(user_id, project_id, job_id, attempt)
        try:
            return await llm.complete_with_schema(
                provider, 'Private system prompt', 'Private user prompt', {'type': 'object'}, 'fixture_schema',
            )
        finally:
            reset_job_context(token)

    assert asyncio.run(scenario()) == {'product': {}}
    with workspace_db(user_id) as db:
        rows = db.execute('SELECT * FROM tool_runs WHERE job_id=? ORDER BY rowid', (job_id,)).fetchall()
    assert len(rows) == 2
    assert [row['status'] for row in rows] == ['failed', 'succeeded']
    assert [row['retry_count'] for row in rows] == [0, 1]
    assert len({row['input_hash'] for row in rows}) == 2
    serialized = json.dumps([dict(row) for row in rows])
    assert 'Private system prompt' not in serialized and 'Private user prompt' not in serialized
    assert 'not-a-real-key' not in serialized and 'super-secret' not in serialized
