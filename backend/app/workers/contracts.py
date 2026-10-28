"""Role-scoped worker tasks, data views, and file-write validation."""

from dataclasses import dataclass
from enum import StrEnum
import re

from ..spec.types import AppSpec

SHARED_API_ADAPTER = 'frontend/src/api.js'
_SENSITIVE_KEYS = {'api_key', 'apikey', 'access_token', 'token', 'secret', 'password', 'authorization'}
_SECRET_TEXT = re.compile(r'(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;]+)|bearer\s+[a-z0-9._~+/=-]+')


class WorkerRole(StrEnum):
    SUPERVISOR = 'supervisor'
    FRONTEND = 'frontend'
    BACKEND = 'backend'


class WorkerPermissionError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerTask:
    role: WorkerRole
    phase: int
    paths: tuple[str, ...]
    data: dict

    @property
    def task_id(self) -> str:
        return f'{self.role.value}:phase-{self.phase}'


@dataclass(frozen=True)
class WorkerResult:
    task: WorkerTask
    files: dict[str, str]


def role_for_path(spec: AppSpec, path: str) -> WorkerRole:
    if path == SHARED_API_ADAPTER or (spec.architecture.source_format == 'single-file' and path == 'index.html'):
        return WorkerRole.SUPERVISOR
    declared = {item.path: item.owner for item in spec.manifest.files}
    owner = declared.get(path, 'supervisor')
    if owner in {role.value for role in WorkerRole}:
        return WorkerRole(owner)
    return WorkerRole.SUPERVISOR


def assert_worker_data_safe(value, path='task') -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace('-', '_')
            if normalized in _SENSITIVE_KEYS or normalized.endswith(
                ('_api_key', '_access_token', '_secret', '_password', '_encrypted'),
            ):
                raise WorkerPermissionError(f'Worker data contains a credential field: {path}.{key}')
            assert_worker_data_safe(item, f'{path}.{key}')
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_worker_data_safe(item, f'{path}[{index}]')
    elif isinstance(value, str) and _SECRET_TEXT.search(value):
        raise WorkerPermissionError(f'Worker data contains credential-like content: {path}')


def worker_data_view(role: WorkerRole, spec: AppSpec, paths: tuple[str, ...]) -> dict:
    document = spec.model_dump(mode='json', exclude_none=True)
    manifest = {
        'files': [{'path': path, 'owner': role_for_path(spec, path).value} for path in paths],
        'generation_order': list(paths),
    }
    if role == WorkerRole.SUPERVISOR:
        data = document
    elif role == WorkerRole.FRONTEND:
        data = {
            'product': document['product'], 'architecture': document['architecture'],
            'entities': document['entities'], 'api': document['api'], 'frontend': document['frontend'],
            'dependencies': {'npm': document['dependencies']['npm']},
        }
    else:
        data = {
            'product': document['product'], 'architecture': document['architecture'],
            'entities': document['entities'], 'api': document['api'],
            'dependencies': {'python': document['dependencies']['python']},
        }
    data['manifest'] = manifest
    assert_worker_data_safe(data)
    return data


def plan_worker_tasks(spec: AppSpec, phase: int) -> list[WorkerTask]:
    if phase not in {1, 2, 3}:
        raise WorkerPermissionError('Worker phase must be 1, 2, or 3')
    ordered = list(spec.manifest.generation_order) or [item.path for item in spec.manifest.files]
    grouped: dict[WorkerRole, list[str]] = {role: [] for role in WorkerRole}
    for path in ordered:
        role = role_for_path(spec, path)
        source_producing = role != WorkerRole.SUPERVISOR or path in {SHARED_API_ADAPTER, 'index.html'}
        if source_producing and path not in grouped[role]:
            grouped[role].append(path)
    tasks = []
    for role in (WorkerRole.FRONTEND, WorkerRole.BACKEND, WorkerRole.SUPERVISOR):
        paths = tuple(grouped[role])
        if paths:
            tasks.append(WorkerTask(role, phase, paths, worker_data_view(role, spec, paths)))
    return tasks


def validate_worker_result(result: WorkerResult) -> None:
    expected = set(result.task.paths)
    actual = set(result.files)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise WorkerPermissionError(
            f'{result.task.role.value} worker file scope mismatch; missing={missing}, out_of_scope={extra}'
        )


def merge_worker_results(results: list[WorkerResult]) -> dict[str, str]:
    merged = {}
    for result in results:
        validate_worker_result(result)
        conflicts = sorted(set(merged) & set(result.files))
        if conflicts:
            raise WorkerPermissionError(f'Conflicting worker writes: {conflicts}')
        merged.update(result.files)
    return merged
