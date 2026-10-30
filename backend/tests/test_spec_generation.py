import asyncio
import json

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
    assert 'frontend.presentation' in prompt
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


@pytest.mark.parametrize('empty_state,expected_title,expected_message', [
    ({'title': 'No tasks yet', 'message': 'Add your first task.'}, 'No tasks yet', 'Add your first task.'),
    ('Add your first task.', None, 'Add your first task.'),
])
def test_presentation_aliases_are_normalized_without_repair(monkeypatch, empty_state, expected_title, expected_message):
    document = proposal()
    document['frontend']['presentation'] = {
        'primary_headline': 'Focus on useful work',
        'entity_label_singular': 'task',
        'entity_label_plural': 'tasks',
        'primary_create_label': 'Add a task',
        'empty_state': empty_state,
    }
    calls = []

    async def complete(*_args):
        calls.append(True)
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Task App', 'A focused task workflow', 'multi-file', 'fastapi',
    ))
    presentation = spec.frontend.presentation
    assert presentation.headline == 'Focus on useful work'
    assert presentation.entity_label == 'task' and presentation.entity_plural_label == 'tasks'
    assert presentation.create_label == 'Add a task'
    assert presentation.empty_title == expected_title
    assert presentation.empty_message == expected_message
    serialized = presentation.model_dump(mode='json', exclude_none=True)
    assert not {'primary_headline', 'entity_label_singular', 'entity_label_plural', 'primary_create_label', 'empty_state'} & serialized.keys()
    assert len(calls) == 1


@pytest.mark.parametrize('as_json_string', [False, True])
def test_value_wrapped_proposal_and_product_aliases_are_normalized(monkeypatch, as_json_string):
    document = proposal()
    document['product'] = {
        'name': 'Provider-selected name',
        'description': 'A concise product brief',
        'workflow': 'Complete the primary user workflow',
    }
    calls = []

    async def complete(*_args):
        calls.append(True)
        return {'value': json.dumps(document) if as_json_string else document}

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Requested App', 'Authoritative brief', 'multi-file', 'fastapi',
    ))
    assert spec.product.name == 'Requested App'
    assert spec.product.brief == 'A concise product brief'
    assert spec.product.primary_workflow == 'Complete the primary user workflow'
    assert len(calls) == 1


def test_missing_product_fields_use_authoritative_brief_without_repair(monkeypatch):
    document = proposal()
    document['product'].pop('brief')
    document['product'].pop('primary_workflow')
    calls = []

    async def complete(*_args):
        calls.append(True)
        return {'value': document}

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Requested App', 'Authoritative user brief', 'multi-file', 'fastapi',
    ))
    assert spec.product.brief == 'Authoritative user brief'
    assert spec.product.primary_workflow == 'Authoritative user brief'
    assert len(calls) == 1


def test_api_metadata_and_missing_names_are_normalized_without_repair(monkeypatch):
    document = proposal()
    for operation in document['api']:
        operation.pop('name')
        operation['description'] = 'Descriptive text that is not part of the executable contract'
    calls = []

    async def complete(*_args):
        calls.append(True)
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Requested App', 'A shared workflow', 'multi-file', 'fastapi',
    ))
    assert all(not hasattr(operation, 'description') for operation in spec.api)
    assert all(operation.name == 'Descriptive text that is not part of the executable contract' for operation in spec.api)
    assert len(calls) == 1


def test_entity_labels_and_descriptive_metadata_are_normalized(monkeypatch):
    document = proposal()
    entity = document['entities'][0]
    entity['label'] = 'Task'
    entity['plural_label'] = 'Tasks'
    entity['description'] = 'Entity description'
    for field in entity['fields']:
        field['label'] = 'Display label'
        field['description'] = 'Field description'
    calls = []

    async def complete(*_args):
        calls.append(True)
        return document

    monkeypatch.setattr('app.spec.generator.complete_with_schema', complete)
    spec = asyncio.run(propose_appspec(
        {'name': 'Provider'}, 'Task App', 'A task workflow', 'multi-file', 'fastapi',
    ))
    assert spec.frontend.presentation.entity_label == 'task'
    assert spec.frontend.presentation.entity_plural_label == 'tasks'
    assert not hasattr(spec.entities[0], 'label') and not hasattr(spec.entities[0], 'plural_label')
    assert all(not hasattr(field, 'label') and not hasattr(field, 'description') for field in spec.entities[0].fields)
    assert len(calls) == 1
