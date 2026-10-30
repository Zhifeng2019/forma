"""Schema-aware AppSpec proposals with bounded semantic repair."""

import copy
import json

from ..llm import complete_with_schema
from ..workers.contracts import WorkerRole
from ..workers.credentials import CredentialBroker
from .contract import entity_contract
from .defaults import default_acceptance, default_api, default_dependencies, default_manifest, local_default_appspec
from .schema import AppSpecError, parse_appspec
from .types import AppSpec

SYSTEM = '''You are a senior product architect producing a typed Application Specification.
Return product semantics only: no source code, filenames, dependency versions, or implementation file maps.'''
PROPOSAL_REPAIR_ATTEMPTS = 1


def proposal_json_schema() -> dict:
    schema = AppSpec.model_json_schema()
    schema['required'] = ['product', 'entities', 'api', 'frontend', 'acceptance']
    return schema


def _current_document(current_spec: AppSpec | dict | None) -> dict | None:
    if current_spec is None:
        return None
    if isinstance(current_spec, AppSpec):
        return current_spec.model_dump(mode='json', exclude_none=True)
    if 'spec' in current_spec and isinstance(current_spec['spec'], dict):
        return copy.deepcopy(current_spec['spec'])
    return copy.deepcopy(current_spec)


def _normalize_presentation(frontend: dict) -> None:
    presentation = frontend.get('presentation')
    if not isinstance(presentation, dict):
        return
    aliases = {
        'primary_headline': 'headline',
        'entity_label_singular': 'entity_label',
        'entity_label_plural': 'entity_plural_label',
        'primary_create_label': 'create_label',
        'empty_state_title': 'empty_title',
        'empty_state_message': 'empty_message',
    }
    for alias, canonical in aliases.items():
        if alias in presentation:
            if presentation.get(canonical) in {None, ''}:
                presentation[canonical] = presentation[alias]
            presentation.pop(alias)
    empty_state = presentation.pop('empty_state', None)
    if isinstance(empty_state, dict):
        for source, target in (
            ('title', 'empty_title'), ('message', 'empty_message'), ('description', 'empty_message'),
        ):
            if source in empty_state and presentation.get(target) in {None, ''}:
                presentation[target] = empty_state[source]
    elif isinstance(empty_state, str) and presentation.get('empty_message') in {None, ''}:
        presentation['empty_message'] = empty_state


def _looks_like_appspec(value) -> bool:
    return isinstance(value, dict) and bool({'product', 'entities', 'frontend', 'api'} & value.keys())


def _unwrap_proposal(proposal):
    """Unwrap common provider envelopes without accepting arbitrary contract fields."""
    document = copy.deepcopy(proposal)
    for _attempt in range(4):
        if isinstance(document, str):
            try:
                document = json.loads(document)
            except json.JSONDecodeError:
                return document
        if not isinstance(document, dict):
            return document
        if 'value' in document:
            nested = document['value']
            if isinstance(nested, str):
                try:
                    nested = json.loads(nested)
                except json.JSONDecodeError:
                    nested = None
            if _looks_like_appspec(nested):
                document = nested
                continue
            if _looks_like_appspec(document):
                document = {key: value for key, value in document.items() if key != 'value'}
        if _looks_like_appspec(document):
            return document
        for key in ('result', 'data', 'proposal', 'appspec', 'output', 'response'):
            if key in document:
                document = document[key]
                break
        else:
            return document
    return document


def _normalize_proposal(
    proposal: dict, name: str, source_format: str, backend_mode: str,
    brief: str = '', current_spec: AppSpec | dict | None = None,
) -> AppSpec:
    document = _unwrap_proposal(proposal)
    document.pop('type', None)
    document['schema_version'] = '1.0'
    document['compiler_version'] = '1.0'
    current = _current_document(current_spec) or {}
    current_product = current.get('product', {}) if isinstance(current.get('product'), dict) else {}
    product = document.get('product') if isinstance(document.get('product'), dict) else {}
    for alias, canonical in (
        ('description', 'brief'), ('workflow', 'primary_workflow'),
        ('primaryWorkflow', 'primary_workflow'), ('user_workflow', 'primary_workflow'),
    ):
        if alias in product:
            if product.get(canonical) in {None, ''}:
                product[canonical] = product[alias]
            product.pop(alias)
    product['name'] = name
    if product.get('brief') in {None, ''}:
        product['brief'] = current_product.get('brief') or brief
    if product.get('primary_workflow') in {None, ''}:
        product['primary_workflow'] = current_product.get('primary_workflow') or product['brief']
    product['primary_workflow'] = product['primary_workflow'][:2000]
    document['product'] = product
    document['architecture'] = {
        'backend_mode': backend_mode,
        'source_format': source_format,
        'state_ownership': 'server' if backend_mode == 'fastapi' else 'browser',
    }
    document['dependencies'] = default_dependencies(source_format)
    document['manifest'] = default_manifest(source_format, backend_mode)
    frontend = document.get('frontend') if isinstance(document.get('frontend'), dict) else {}
    _normalize_presentation(frontend)
    frontend['state_adapter'] = 'forma-api' if backend_mode == 'fastapi' else 'browser-local'
    document['frontend'] = frontend
    acceptance = document.get('acceptance')
    if isinstance(acceptance, list):
        normalized = []
        for check in acceptance:
            if not isinstance(check, dict):
                continue
            item = {key: check[key] for key in ('name', 'kind', 'target') if key in check}
            if isinstance(item.get('kind'), str):
                item['kind'] = item['kind'].lower()
            normalized.append(item)
        document['acceptance'] = normalized
    if isinstance(document.get('api'), list):
        normalized_api = []
        for operation in document['api']:
            if not isinstance(operation, dict):
                continue
            item = {key: operation[key] for key in ('name', 'method', 'path', 'entity', 'errors') if key in operation}
            if not item.get('name'):
                item['name'] = str(operation.get('description') or f'{item.get("method", "GET")} {item.get("path", "/api")}')[:120]
            normalized_api.append(item)
        document['api'] = normalized_api
    if backend_mode == 'static':
        document['api'] = []
        acceptance = document.get('acceptance') if isinstance(document.get('acceptance'), list) else []
        document['acceptance'] = [check for check in acceptance
                                  if isinstance(check, dict) and check.get('kind') != 'api']
    supported = {'build', 'api', 'persistence', 'browser', 'migration', 'security'}
    valid_checks = [check for check in document.get('acceptance', [])
                    if isinstance(check, dict) and check.get('kind') in supported]
    document['acceptance'] = valid_checks or default_acceptance(backend_mode, source_format)
    if backend_mode != 'static' and isinstance(document.get('api'), list):
        collection = 'items'
        detail_path = ''
        for operation in document['api']:
            method, path = operation.get('method'), operation.get('path', '')
            if method == 'GET' and path != '/api/health' and '{' not in path:
                parts = path.split('/')
                if len(parts) > 2 and parts[2]:
                    collection = parts[2]
                break
        for operation in document['api']:
            if operation.get('method') in {'PATCH', 'DELETE'} and '{' in operation.get('path', ''):
                detail_path = operation['path']
                break
        entity_name = document['entities'][0]['name'] if document.get('entities') else 'Item'
        defaults = default_api(backend_mode, collection, entity_name)
        detail_path = detail_path or next(
            operation['path'] for operation in defaults if operation['method'] == 'PATCH'
        )
        collection_path = f'/api/{collection}'
        allowed = {
            ('GET', '/api/health'), ('GET', collection_path), ('POST', collection_path),
            ('PATCH', detail_path), ('DELETE', detail_path), ('GET', detail_path),
        }
        normalized = []
        seen = set()
        for operation in [*document['api'], *defaults]:
            key = (operation.get('method'), operation.get('path'))
            if key not in allowed or key in seen:
                continue
            if operation['path'] == '/api/health':
                operation['entity'] = None
            elif not operation.get('entity'):
                operation['entity'] = entity_name
            normalized.append(operation)
            seen.add(key)
        document['api'] = normalized
    return parse_appspec(document)


def _validate_proposal(spec: AppSpec) -> AppSpec:
    entity_contract(spec)
    return spec


def _local_proposal(
    name: str, brief: str, source_format: str, backend_mode: str,
    feedback: str, current_spec: AppSpec | dict | None,
) -> AppSpec:
    current = _current_document(current_spec)
    if not current or not current.get('entities'):
        spec = local_default_appspec(name, brief, source_format, backend_mode)
        document = spec.model_dump(mode='json', exclude_none=True)
    else:
        document = current
        if backend_mode == 'fastapi' and not document.get('api'):
            previous = _validate_proposal(_normalize_proposal(
                document, name, source_format, 'static', brief, current_spec,
            ))
            entity = document['entities'][0]['name']
            collection = entity_contract(previous).collection
            document['api'] = default_api(backend_mode, collection, entity)
        document = _normalize_proposal(document, name, source_format, backend_mode, brief, current_spec).model_dump(
            mode='json', exclude_none=True,
        )
    document = _normalize_proposal(document, name, source_format, backend_mode, brief, current_spec).model_dump(
        mode='json', exclude_none=True,
    )
    if backend_mode == 'fastapi' and not any(check.get('kind') == 'api' for check in document['acceptance']):
        document['acceptance'].append({'name': 'Runtime health', 'kind': 'api', 'target': '/api/health'})
    if feedback:
        document['product']['brief'] = f'{document["product"]["brief"]}\n\nAdditional direction:\n{feedback}'[:12_000]
    return _validate_proposal(parse_appspec(document))


def proposal_prompt(
    name: str, brief: str, source_format: str, backend_mode: str,
    phase: int, feedback: str, current_spec: AppSpec | dict | None,
) -> str:
    current = _current_document(current_spec)
    current_json = json.dumps(current, sort_keys=True, ensure_ascii=False)[:48_000] if current else 'None'
    api_requirement = (
        'Declare GET /api/health, GET and POST /api/<collection>, and PATCH and DELETE '
        '/api/<collection>/{item_id}. Every CRUD operation must reference the one entity. '
        'Do not declare other operations.'
        if backend_mode == 'fastapi' else
        'Return an empty api list and use browser-local state. Do not declare server operations.'
    )
    return f'''Product name: {name}
User brief: {brief}
Architecture: {backend_mode}; {source_format}
Implementation phase: {phase}/3
User feedback: {feedback or 'None'}
Current AppSpec to preserve and refine: {current_json}

Return one AppSpec proposal directly at the top level with product, entities, api, frontend, and acceptance sections. Do not wrap it in value, result, data, response, or output. product must include brief and primary_workflow.
In frontend.presentation, use only these keys: headline, entity_label, entity_plural_label, create_label, empty_title, empty_message. Provide concise product-facing copy and do not repeat the long workflow in the headline.
Use exactly one entity with one to eight non-ID fields. An integer id field is optional.
Supported field kinds: string, text, integer, number, boolean, date, datetime, uuid.
Supported constraints: minLength/maxLength for strings and minimum/maximum for numbers.
Do not use relationships in this version.
{api_requirement}
Keep the primary workflow coherent with the brief and preserve working contracts unless feedback requires a change.
Do not return manifest, dependencies, architecture, source files, code, Markdown, or dependency versions.'''


async def propose_appspec(
    provider: dict | None,
    name: str,
    brief: str,
    source_format: str,
    backend_mode: str,
    phase: int = 1,
    feedback: str = '',
    current_spec: AppSpec | dict | None = None,
) -> AppSpec:
    if not provider:
        return _local_proposal(name, brief, source_format, backend_mode, feedback, current_spec)
    supervised_provider = CredentialBroker(provider).for_role(WorkerRole.SUPERVISOR)
    prompt = proposal_prompt(name, brief, source_format, backend_mode, phase, feedback, current_spec)
    proposal = await complete_with_schema(supervised_provider, SYSTEM, prompt, proposal_json_schema(), 'forma_appspec')
    try:
        return _validate_proposal(_normalize_proposal(
            proposal, name, source_format, backend_mode, brief, current_spec,
        ))
    except AppSpecError as exc:
        repair = prompt + (
            f'\n\nThe previous valid JSON proposal failed AppSpec validation: {exc}\n'
            f'Previous proposal:\n{json.dumps(proposal, ensure_ascii=False)[:48_000]}\n'
            'Return one complete corrected proposal. Preserve the requested architecture and the one-entity CRUD boundary.'
        )
        if PROPOSAL_REPAIR_ATTEMPTS != 1:
            raise
        corrected = await complete_with_schema(
            supervised_provider, SYSTEM, repair, proposal_json_schema(), 'forma_appspec',
        )
        return _validate_proposal(_normalize_proposal(
            corrected, name, source_format, backend_mode, brief, current_spec,
        ))
