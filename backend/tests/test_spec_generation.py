import asyncio

import pytest

from app.llm import GenerationError
from app.spec.contract import entity_contract
from app.spec.defaults import local_default_appspec
from app.spec.generator import propose_appspec
from app.spec.schema import AppSpecError


def proposal(backend_mode='fastapi', source_format='multi-file'):
    return local_default_appspec('Generated App', 'A useful generated workflow', source_format, backend_mode).model_dump(
        mode='json', exclude_none=True,
    )


def test_local_proposals_are_deterministic_and_validate_the_crud_contract():
    for backend_mode in ('static', 'fastapi'):
        for source_format in ('single-file', 'multi-file'):
            first = asyncio.run(propose_appspec(
                None, 'Local App', 'A local workflow', source_format, backend_mode,
            ))
            second = asyncio.run(propose_appspec(
                None, 'Local App', 'A local workflow', source_format, backend_mode,
            ))
            assert first == second
            contract = entity_contract(first)
            assert contract.collection == 'items'
            assert len(contract.fields) == 2


def test_provider_proposal_uses_schema_and_studio_owned_policy(monkeypatch):
    calls = []

    async def complete(_provider, _system, prompt, schema, schema_name):
        calls.append((prompt, schema, schema_name))
        document = proposal()
        document['product']['name'] = 'Model-selected name'
        document['dependencies'] = {'python': ['requests==1.0'], 'npm': ['axios']}
        document['manifest'] = {'files': [{'path': '../../secret', 'owner': 'backend'}], 'generation_order': []}
        document['architecture'] = {'backend_mode': 'static', 'source_format': 'single-file', 'state_ownership': 'browser'}
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Requested App', 'A shared workflow', 'multi-file', 'fastapi',
    ))
    assert len(calls) == 1
    prompt, schema, schema_name = calls[0]
    assert schema_name == 'forma_appspec'
    assert schema['required'] == ['product', 'entities', 'api', 'frontend', 'acceptance']
    assert 'no source code, filenames' not in prompt  # The system prompt carries this rule.
    assert 'Do not return manifest, dependencies, architecture, source files, code' in prompt
    assert spec.product.name == 'Requested App'
    assert spec.architecture.backend_mode == 'fastapi'
    assert spec.architecture.source_format == 'multi-file'
    assert spec.dependencies.python == []
    assert all('secret' not in item.path for item in spec.manifest.files)


def test_invalid_semantic_proposal_gets_exactly_one_repair(monkeypatch):
    documents = [proposal(), proposal()]
    documents[0]['api'][1]['entity'] = 'Missing'
    calls = []

    async def complete(_provider, _system, prompt, _schema, _schema_name):
        calls.append(prompt)
        return documents.pop(0)

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Repair App', 'A repairable workflow', 'multi-file', 'fastapi',
    ))
    assert spec.api[1].entity == 'Item'
    assert len(calls) == 2
    assert 'failed AppSpec validation' in calls[1]
    assert 'Missing' in calls[1]


def test_second_invalid_semantic_proposal_fails_without_a_third_call(monkeypatch):
    calls = []

    async def complete(_provider, _system, prompt, _schema, _schema_name):
        calls.append(prompt)
        document = proposal()
        document['api'][1]['entity'] = 'Missing'
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    with pytest.raises(AppSpecError, match='unknown entity Missing'):
        asyncio.run(propose_appspec(
            {'name': 'Provider'}, 'Repair App', 'An invalid workflow', 'multi-file', 'fastapi',
        ))
    assert len(calls) == 2


def test_provider_failure_does_not_trigger_semantic_repair(monkeypatch):
    calls = []

    async def complete(*_args):
        calls.append(True)
        raise GenerationError('Provider returned 500')

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    with pytest.raises(GenerationError, match='Provider returned 500'):
        asyncio.run(propose_appspec(
            {'name': 'Provider'}, 'Repair App', 'A workflow', 'multi-file', 'fastapi',
        ))
    assert len(calls) == 1


def test_local_refinement_uses_previous_spec_and_preserves_entity():
    initial = asyncio.run(propose_appspec(
        None, 'Original App', 'A task workflow', 'multi-file', 'fastapi', phase=1,
    ))
    document = initial.model_dump(mode='json', exclude_none=True)
    document['entities'][0]['name'] = 'Task'
    for operation in document['api']:
        if operation['path'] != '/api/health':
            operation['entity'] = 'Task'
    revised = asyncio.run(propose_appspec(
        None, 'Original App', 'A task workflow', 'multi-file', 'fastapi',
        phase=2, feedback='Keep titles concise.', current_spec=document,
    ))
    assert revised.entities[0].name == 'Task'
    assert 'Keep titles concise.' in revised.product.brief
    assert revised.architecture == initial.architecture


def test_acceptance_metadata_is_normalized_without_a_repair_call(monkeypatch):
    document = proposal()
    for check in document['acceptance']:
        check['assertion'] = 'Provider-specific assertion text'
        check['type'] = 'provider-specific type'
    document['type'] = 'web_application'
    calls = []

    async def complete(*_args):
        calls.append(True)
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Metadata App', 'A compatible workflow', 'multi-file', 'fastapi',
    ))
    assert all(set(check.model_dump()) == {'name', 'kind', 'target'} for check in spec.acceptance)
    assert len(calls) == 1


def test_missing_fastapi_operations_receive_studio_defaults(monkeypatch):
    document = proposal()
    document['api'] = []

    async def complete(*_args):
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Incomplete App', 'An incomplete workflow', 'multi-file', 'fastapi',
    ))
    assert {(operation.method, operation.path) for operation in spec.api} == {
        ('GET', '/api/health'), ('GET', '/api/items'), ('POST', '/api/items'),
        ('PATCH', '/api/items/{item_id}'), ('DELETE', '/api/items/{item_id}'),
    }


def test_unsupported_acceptance_categories_fall_back_to_defaults(monkeypatch):
    document = proposal()
    document['acceptance'] = [{'name': 'Custom check', 'kind': 'performance', 'target': 'fast'}]

    async def complete(*_args):
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Category App', 'A categorized workflow', 'multi-file', 'fastapi',
    ))
    assert {check.kind for check in spec.acceptance} == {'build', 'browser', 'persistence', 'api'}


def test_duplicate_and_custom_api_operations_are_normalized(monkeypatch):
    document = proposal()
    document['api'].append({'name': 'Duplicate list', 'method': 'GET', 'path': '/api/items', 'entity': 'Item'})
    document['api'].append({'name': 'Custom auth', 'method': 'POST', 'path': '/api/auth/login'})

    async def complete(*_args):
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Duplicate App', 'A duplicate workflow', 'multi-file', 'fastapi',
    ))
    assert sum(operation.method == 'GET' and operation.path == '/api/items' for operation in spec.api) == 1
    assert all(not operation.path.startswith('/api/auth') for operation in spec.api)


def test_health_operation_cannot_reference_an_entity(monkeypatch):
    document = proposal()
    document['api'][0]['entity'] = 'Item'

    async def complete(*_args):
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Health App', 'A health workflow', 'multi-file', 'fastapi',
    ))
    health = next(operation for operation in spec.api if operation.path == '/api/health')
    assert health.entity is None
