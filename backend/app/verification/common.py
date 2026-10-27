"""Shared acceptance-generation contracts and deterministic values."""

from dataclasses import dataclass, field
import json

from ..spec.contract import EntityContract, entity_contract
from ..spec.schema import AppSpecError
from ..spec.types import AppSpec, EntityFieldSpec


@dataclass(frozen=True)
class AcceptanceContext:
    spec: AppSpec
    source_hash: str
    phase: int
    files: dict[str, str]

    @property
    def contract(self) -> EntityContract | None:
        if len(self.spec.entities) != 1:
            return None
        try:
            return entity_contract(self.spec)
        except AppSpecError:
            return None


@dataclass(frozen=True)
class GeneratedCheck:
    check_id: str
    kind: str
    target: str
    test: str
    file: str
    required: bool = True
    timeout: int = 60
    mutates: bool = False
    environment: tuple[str, ...] = field(default_factory=tuple)

    def document(self) -> dict:
        return {
            'id': self.check_id, 'kind': self.kind, 'target': self.target,
            'test': self.test, 'file': self.file, 'required': self.required,
            'timeout': self.timeout, 'mutates': self.mutates,
            'environment': list(self.environment),
        }


def python_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def javascript_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def create_payload(contract: EntityContract) -> dict:
    payload = {}
    for entity_field in contract.fields:
        if entity_field.kind in {'string', 'text'}:
            payload[entity_field.name] = 'Forma acceptance record'
        elif entity_field.kind == 'integer':
            payload[entity_field.name] = 1
        elif entity_field.kind == 'number':
            payload[entity_field.name] = 1.0
        elif entity_field.kind == 'boolean':
            payload[entity_field.name] = False
        elif entity_field.kind == 'date':
            payload[entity_field.name] = '2026-01-01'
        elif entity_field.kind == 'datetime':
            payload[entity_field.name] = '2026-01-01T00:00:00'
        elif entity_field.kind == 'uuid':
            payload[entity_field.name] = 'acceptance-1'
    return payload


def patch_payload(contract: EntityContract, created: dict) -> dict:
    if contract.boolean_field:
        return {contract.boolean_field: not created[contract.boolean_field]}
    field = next((field for field in contract.fields if field.kind in {'string', 'text'}), None)
    if field:
        return {field.name: f'{created[field.name]} updated'}
    field = next((field for field in contract.fields if field.kind in {'integer', 'number'}), None)
    if field:
        return {field.name: created[field.name] + 1}
    field = contract.fields[0]
    return {field.name: created[field.name]}


def required_string(contract: EntityContract) -> EntityFieldSpec | None:
    return next((field for field in contract.fields
                 if field.required and field.kind in {'string', 'text'}), None)


def detail_script(contract: EntityContract) -> str:
    return (
        f'DETAIL_PATH = {contract.detail_path!r}\n'
        f'def detail_url(record_id):\n'
        f'    return DETAIL_PATH.replace("{{{contract.path_parameter}}}", str(record_id))\n'
    )


HTTP_HELPERS = '''import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(method, path, payload=None, raw_url=None, studio=False):
    if raw_url:
        url = raw_url
    elif studio:
        base = os.environ.get('FORMA_BASE_URL', '').rstrip('/')
        if not base:
            raise RuntimeError('FORMA_BASE_URL is required')
        url = base + path
    else:
        base = os.environ.get('APP_BASE_URL', '').rstrip('/')
        if not base:
            raise RuntimeError('APP_BASE_URL is required')
        url = base + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'}
    token = os.environ.get('FORMA_TOKEN' if studio else 'APP_ACCESS_TOKEN', '')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode()
        try:
            body = json.loads(body) if body else None
        except json.JSONDecodeError:
            pass
        return exc.code, body
'''
