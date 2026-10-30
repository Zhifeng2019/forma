import json
import httpx
import pytest

from app import llm
from app.security import encrypt_secret
from fixtures.loader import FixturePack

PACK = FixturePack()


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
        FakeResponse(PACK.read_resource(PACK.manifest.providers['truncated-model-output']), 'length'),
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
    assert 'Continue exactly from its final character' in repair


@pytest.mark.asyncio
async def test_invalid_json_gets_one_repair_attempt(monkeypatch):
    FakeClient.responses = [
        FakeResponse(PACK.read_resource(PACK.manifest.providers['invalid-json'])),
        FakeResponse('{"document":"repaired"}'),
    ]
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


@pytest.mark.asyncio
async def test_native_json_schema_is_used_for_structured_proposals(monkeypatch):
    FakeClient.responses = [FakeResponse('{"product":{}}')]
    FakeClient.calls = []
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    provider = {
        'name': 'OpenAI', 'model': 'structured-model',
        'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }
    result = await llm.complete_with_schema(
        provider, 'Design a contract', 'Return the proposal',
        {'type': 'object', 'properties': {'product': {'type': 'object'}}}, 'forma_appspec',
    )
    assert result == {'product': {}}
    response_format = FakeClient.calls[0]['json']['response_format']
    assert response_format['type'] == 'json_schema'
    assert response_format['json_schema']['strict'] is True
    assert response_format['json_schema']['name'] == 'forma_appspec'


@pytest.mark.asyncio
async def test_json_schema_falls_back_for_compatible_providers(monkeypatch):
    FakeClient.responses = [FakeResponse('unsupported', status=400), FakeResponse('{"product":{}}')]
    FakeClient.calls = []
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    provider = {
        'name': 'Compatible provider', 'model': 'json-model',
        'base_url': 'https://api.example.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }
    result = await llm.complete_with_schema(
        provider, 'Design a contract', 'Return the proposal', {'type': 'object'}, 'forma_appspec',
    )
    assert result == {'product': {}}
    assert len(FakeClient.calls) == 2
    assert FakeClient.calls[0]['json']['response_format']['type'] == 'json_schema'
    assert FakeClient.calls[1]['json']['response_format'] == {'type': 'json_object'}


@pytest.mark.asyncio
async def test_length_response_is_continued_and_reassembled(monkeypatch):
    FakeClient.responses = [
        FakeResponse('{"document":"# Design\\n\\n## Users', 'length'),
        FakeResponse('\\n\\n## Workflow\\n\\nDetails"}'),
    ]
    FakeClient.calls = []
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    provider = {
        'name': 'DeepSeek', 'model': 'deepseek-chat',
        'base_url': 'https://api.deepseek.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }

    result = await llm.complete(provider, 'Write a design', 'Return the document')

    assert result == {'document': '# Design\n\n## Users\n\n## Workflow\n\nDetails'}
    continuation = FakeClient.calls[1]['json']['messages'][-1]['content']
    assert 'Continue exactly from its final character' in continuation
    assert 'do not repeat or restart the JSON' in continuation


@pytest.mark.asyncio
async def test_literal_newlines_inside_document_json_are_normalized(monkeypatch):
    FakeClient.responses = [FakeResponse('{"document":"# Design\n\n## Users\nRegister and sign in."}')]
    FakeClient.calls = []
    monkeypatch.setattr(httpx, 'AsyncClient', FakeClient)
    provider = {
        'name': 'DeepSeek', 'model': 'deepseek-chat',
        'base_url': 'https://api.deepseek.com/v1',
        'api_key_encrypted': encrypt_secret('not-a-real-key'),
    }

    result = await llm.complete(provider, 'Write a design', 'Return the document')

    assert result == {'document': '# Design\n\n## Users\nRegister and sign in.'}
    assert len(FakeClient.calls) == 1
