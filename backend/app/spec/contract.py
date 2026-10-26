"""Validated v1 single-entity CRUD contract used by proposals and compilers."""

from dataclasses import dataclass
import re

from .schema import AppSpecError
from .types import ApiOperationSpec, AppSpec, EntityFieldSpec, EntitySpec


@dataclass(frozen=True)
class EntityContract:
    entity: EntitySpec
    fields: list[EntityFieldSpec]
    collection: str
    collection_path: str
    detail_path: str
    path_parameter: str
    operations: dict[tuple[str, str], ApiOperationSpec]
    boolean_field: str


def _collection_name(entity_name: str) -> str:
    value = re.sub(r'(?<!^)(?=[A-Z])', '_', entity_name).lower()
    if value.endswith('y') and value[-2:-1] not in 'aeiou':
        return value[:-1] + 'ies'
    if value.endswith(('s', 'x', 'ch', 'sh')):
        return value + 'es'
    return value + 's'


def _validate_fields(entity: EntitySpec) -> list[EntityFieldSpec]:
    fields = [field for field in entity.fields if field.name != 'id']
    if not 1 <= len(fields) <= 8:
        raise AppSpecError('AppSpec source generation v1 requires between one and eight non-ID fields.')
    for field in entity.fields:
        if field.name == 'id' and field.kind != 'integer':
            raise AppSpecError('An explicit id field must use the integer kind.')
    for field in fields:
        for key, value in field.constraints.items():
            if key in {'minLength', 'maxLength'}:
                if field.kind not in {'string', 'text'} or not isinstance(value, int) or value < 0:
                    raise AppSpecError(f'{field.name}.{key} requires a non-negative integer on a string field.')
            elif key in {'minimum', 'maximum'}:
                if field.kind not in {'integer', 'number'} or not isinstance(value, (int, float)):
                    raise AppSpecError(f'{field.name}.{key} requires a numeric boundary on a numeric field.')
            else:
                raise AppSpecError(f'Unsupported constraint for AppSpec source generation v1: {field.name}.{key}')
        if ('minLength' in field.constraints and 'maxLength' in field.constraints
                and field.constraints['minLength'] > field.constraints['maxLength']):
            raise AppSpecError(f'{field.name} has inconsistent length constraints.')
        if ('minimum' in field.constraints and 'maximum' in field.constraints
                and field.constraints['minimum'] > field.constraints['maximum']):
            raise AppSpecError(f'{field.name} has inconsistent numeric constraints.')
    return fields


def entity_contract(spec: AppSpec) -> EntityContract:
    if len(spec.entities) != 1:
        raise AppSpecError('AppSpec source generation v1 requires exactly one entity.')
    entity = spec.entities[0]
    if entity.relationships:
        raise AppSpecError('AppSpec source generation v1 does not support entity relationships.')
    fields = _validate_fields(entity)
    operations = {(operation.method, operation.path): operation for operation in spec.api}
    collection = _collection_name(entity.name)
    collection_path = ''
    detail_path = ''
    path_parameter = ''
    if spec.architecture.backend_mode == 'static':
        if spec.api:
            raise AppSpecError('Frontend-only AppSpecs must not declare backend API operations.')
    else:
        health = operations.get(('GET', '/api/health'))
        if not health or health.entity is not None:
            raise AppSpecError('FastAPI AppSpecs require GET /api/health.')
        collections = [operation for (method, path), operation in operations.items()
                       if method == 'GET' and operation.entity == entity.name and '{' not in path]
        if len(collections) != 1:
            raise AppSpecError(f'FastAPI AppSpecs require one collection GET operation for {entity.name}.')
        collection_path = collections[0].path
        match = re.fullmatch(r'/api/([a-z][a-z0-9_-]*)', collection_path)
        if not match:
            raise AppSpecError(f'Unsupported collection path for AppSpec source generation v1: {collection_path}')
        collection = match.group(1).replace('-', '_')
        detail_candidates = {path for method, path in operations if method in {'PATCH', 'DELETE'}}
        if len(detail_candidates) != 1:
            raise AppSpecError('PATCH and DELETE must share one entity detail path.')
        detail_path = detail_candidates.pop()
        detail_match = re.fullmatch(re.escape(collection_path) + r'/\{([a-z][a-z0-9_]*)\}', detail_path)
        if not detail_match:
            raise AppSpecError(f'Unsupported entity detail path: {detail_path}')
        path_parameter = detail_match.group(1)
        required = {
            ('POST', collection_path), ('PATCH', detail_path), ('DELETE', detail_path),
        }
        missing = required - operations.keys()
        if missing:
            raise AppSpecError(f'Missing required CRUD operations: {sorted(missing)}')
        allowed = {
            ('GET', '/api/health'), ('GET', collection_path), ('POST', collection_path),
            ('PATCH', detail_path), ('DELETE', detail_path), ('GET', detail_path),
        }
        unsupported = set(operations) - allowed
        if unsupported:
            raise AppSpecError(f'Unsupported API operations for AppSpec source generation v1: {sorted(unsupported)}')
        for operation in spec.api:
            if operation.path != '/api/health' and operation.entity != entity.name:
                raise AppSpecError(f'API operation {operation.name} must reference {entity.name}.')
    boolean_field = next((field.name for field in fields if field.kind == 'boolean'), '')
    return EntityContract(
        entity, fields, collection, collection_path, detail_path,
        path_parameter, operations, boolean_field,
    )
