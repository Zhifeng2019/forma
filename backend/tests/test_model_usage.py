import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app import llm
from app.database import workspace_db
from app.jobs.context import reset_job_context
from app.jobs.tool_runs import finish_tool_run, start_tool_run
from app.jobs.usage import record_observed_completion
from app.schemas import ProviderInput
from app.security import encrypt_secret
from test_tool_runs import activate, ownership


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.text = str(payload)
        self.headers = {}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def completed_run(user_id, job_id, attempt, duration=25):
    run = start_tool_run(
        'provider.http', 'v1', {'model': 'fixture'},
        user_id=user_id, job_id=job_id, attempt_id=attempt['attempt_id'],
    )
    return finish_tool_run(run, 'succeeded', duration_ms=duration)


def provider(**overrides):
    return {
        'name': 'Usage Provider', 'model': 'fixture-model',
        'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
        **overrides,
    }


def test_reported_usage_snapshots_prices_and_computes_estimate():
    user_id = 960300
    _project, job_id, attempt = ownership(user_id)
    run = completed_run(user_id, job_id, attempt)
    response = Response({
        'id': 'request-123', 'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
        'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
    })
    observation = record_observed_completion(
        provider(input_price_per_million=10, output_price_per_million=30, currency='usd'),
        response, run, response_format={'type': 'json_object'},
        request_reason='initial', reason_detail=None, retry_count=0,
    )
    assert observation.usage_status == 'reported'
    assert (observation.input_tokens, observation.output_tokens, observation.total_tokens) == (100, 50, 150)
    assert observation.cost_status == 'estimated' and observation.estimated_cost == 0.0025
    assert observation.provider_request_id == 'request-123' and observation.finish_reason == 'stop'
    with workspace_db(user_id) as db:
        row = db.execute('SELECT * FROM usage_ledger WHERE tool_run_id=?', (run.id,)).fetchone()
    assert row['latency_ms'] == 25 and row['currency'] == 'USD'
    assert row['input_price_per_million'] == 10 and row['output_price_per_million'] == 30
    assert row['estimated_cost'] == 0.0025 and row['usage_status'] == 'reported'
    assert row['cost_status'] == 'estimated' and row['total_tokens'] == 150


def test_missing_and_partial_usage_remain_unknown_not_zero_estimates():
    user_id = 960301
    _project, job_id, attempt = ownership(user_id)
    configured = provider(input_price_per_million=10, output_price_per_million=20)
    missing_run = completed_run(user_id, job_id, attempt)
    missing = record_observed_completion(
        configured, Response({'choices': []}), missing_run, response_format={'type': 'json_object'},
        request_reason='initial', reason_detail=None, retry_count=0,
    )
    partial_run = completed_run(user_id, job_id, attempt)
    partial = record_observed_completion(
        configured, Response({'usage': {'prompt_tokens': 5}}), partial_run,
        response_format={'type': 'json_object'}, request_reason='initial', reason_detail=None, retry_count=0,
    )
    assert missing.usage_status == 'unavailable' and missing.input_tokens is None
    assert missing.cost_status == 'unknown' and missing.estimated_cost is None
    assert partial.usage_status == 'partial' and partial.total_tokens is None
    assert partial.cost_status == 'unknown' and partial.estimated_cost is None
    with workspace_db(user_id) as db:
        rows = db.execute('SELECT metadata,usage_status,cost_status FROM usage_ledger WHERE job_id=? ORDER BY rowid',
                          (job_id,)).fetchall()
    assert [row['usage_status'] for row in rows] == ['unavailable', 'partial']
    assert all(row['cost_status'] == 'unknown' for row in rows)
    missing_tokens = json.loads(rows[0]['metadata'])['observed_tokens']
    assert missing_tokens == {'input': None, 'output': None, 'total': None}


def test_zero_usage_and_zero_prices_are_explicitly_reported_and_estimated():
    user_id = 960302
    _project, job_id, attempt = ownership(user_id)
    run = completed_run(user_id, job_id, attempt)
    observation = record_observed_completion(
        provider(input_price_per_million=0, output_price_per_million=0),
        Response({'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}), run,
        response_format={'type': 'json_object'}, request_reason='initial', reason_detail=None, retry_count=0,
    )
    assert observation.usage_status == 'reported'
    assert observation.cost_status == 'estimated' and observation.estimated_cost == 0


class Client:
    responses = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, _url, **_kwargs):
        return self.responses.pop(0)


def usage(prompt, completion, request_id, finish):
    return {
        'id': request_id,
        'usage': {'prompt_tokens': prompt, 'completion_tokens': completion, 'total_tokens': prompt + completion},
        'choices': [{'finish_reason': finish, 'message': {'content': '{"document":"ready"}'}}],
    }


def test_schema_fallback_records_separate_usage_and_reasons(monkeypatch):
    user_id = 960303
    project_id, job_id, attempt = ownership(user_id)
    Client.responses = [Response(ValueError('not json'), 400), Response(usage(20, 10, 'fallback-2', 'stop'))]
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())

    async def scenario():
        token = activate(user_id, project_id, job_id, attempt)
        try:
            return await llm.complete_with_schema(
                provider(input_price_per_million=1, output_price_per_million=2),
                'System', 'Prompt', {'type': 'object'}, 'fixture_schema',
            )
        finally:
            reset_job_context(token)

    assert asyncio.run(scenario()) == {'document': 'ready'}
    with workspace_db(user_id) as db:
        rows = db.execute('SELECT * FROM usage_ledger WHERE job_id=? ORDER BY rowid', (job_id,)).fetchall()
    assert len(rows) == 2
    assert [json.loads(row['metadata'])['request_reason'] for row in rows] == ['initial', 'schema_fallback']
    assert [row['usage_status'] for row in rows] == ['unavailable', 'reported']
    assert rows[1]['provider_request_id'] == 'fallback-2' and rows[1]['estimated_cost'] == 0.00004


def test_output_repair_records_finish_reason_tokens_and_cost_per_request(monkeypatch):
    user_id = 960304
    project_id, job_id, attempt = ownership(user_id)
    Client.responses = [Response(usage(10, 20, 'repair-1', 'length')), Response(usage(30, 40, 'repair-2', 'stop'))]
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())

    async def scenario():
        token = activate(user_id, project_id, job_id, attempt)
        try:
            return await llm.complete(provider(input_price_per_million=1, output_price_per_million=2), 'System', 'Prompt')
        finally:
            reset_job_context(token)

    assert asyncio.run(scenario()) == {'document': 'ready'}
    with workspace_db(user_id) as db:
        rows = db.execute('SELECT * FROM usage_ledger WHERE job_id=? ORDER BY rowid', (job_id,)).fetchall()
    assert len(rows) == 2
    assert [json.loads(row['metadata'])['request_reason'] for row in rows] == ['initial', 'output_repair']
    assert json.loads(rows[1]['metadata'])['reason_detail'] == 'truncated by the output token limit'
    assert [row['finish_reason'] for row in rows] == ['length', 'stop']
    assert [row['estimated_cost'] for row in rows] == [0.00005, 0.00011]


def test_provider_pricing_validation_accepts_zero_and_rejects_invalid_values():
    free = ProviderInput(name='Free provider', model='fixture', input_price_per_million=0,
                         output_price_per_million=0, currency='usd')
    assert free.input_price_per_million == 0 and free.output_price_per_million == 0
    with pytest.raises(ValidationError):
        ProviderInput(name='Invalid provider', model='fixture', input_price_per_million=-1)
    with pytest.raises(ValidationError):
        ProviderInput(name='Invalid provider', model='fixture', currency='US$')
