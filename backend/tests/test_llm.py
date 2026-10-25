import json
import httpx
import pytest

from app import llm
from app.security import encrypt_secret


class FakeResponse:
    def __init__(self, content, finish_reason='stop', status=200):
        self.status_code = status
        self.text = content
        self._payload = {'choices': [{'finish_reason': finish_reason, 'message': {'content': content}}]}

    def json(self):
        return self._payload


class FakeClient:
    responses = []
    calls = []

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append({'url': url, **kwargs})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_truncated_output_is_retried_with_bounded_budget(monkeypatch):
    FakeClient.responses = [
        FakeResponse('{"html":"<!doctype html>', 'length'),
        FakeResponse(json.dumps({'html': '<!doctype html><html></html>'})),
    ]
    FakeClient.calls = []
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    provider = {
        'name': 'DeepSeek', 'model': 'deepseek-chat',
        'base_url': 'https://api.deepseek.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }

    result = await llm.complete(provider, 'Build an app', 'Return the HTML')

    assert result['html'] == '<!doctype html><html></html>'
    assert len(FakeClient.calls) == 2
    first = FakeClient.calls[0]['json']
    assert first['max_tokens'] == 32_768
    assert first['thinking'] == {'type': 'disabled'}
    repair = FakeClient.calls[1]['json']['messages'][-1]['content']
    assert 'truncated by the output token limit' in repair


@pytest.mark.asyncio
async def test_invalid_json_gets_one_repair_attempt(monkeypatch):
    FakeClient.responses = [FakeResponse('not-json'), FakeResponse('{"document":"repaired"}')]
    FakeClient.calls = []
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    provider = {
        'name': 'Moonshot AI', 'model': 'kimi-k3',
        'base_url': 'https://api.moonshot.cn/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }

    result = await llm.complete(provider, 'Write a document', 'Return Markdown')

    assert result == {'document': 'repaired'}
    assert len(FakeClient.calls) == 2
    assert FakeClient.calls[0]['json']['reasoning_effort'] == 'low'
