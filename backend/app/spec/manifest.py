"""Deterministic AppSpec paths, ownership policy, and source manifests."""

import hashlib
from pathlib import PurePosixPath
import re

from ..backend_engine import BACKEND_PATH, REQUIREMENTS_PATH
from ..source_packages import ALLOWED_BACKEND, REQUIRED_BACKEND, REQUIRED_FRONTEND
from .schema import APPSPEC_SCHEMA_VERSION, COMPILER_VERSION, AppSpecError, parse_appspec
from .types import AppSpec

_MULTI_FILE_PATHS = REQUIRED_FRONTEND | REQUIRED_BACKEND | ALLOWED_BACKEND | {
    'frontend/package.json', 'frontend/vite.config.js', REQUIREMENTS_PATH,
}
_SINGLE_FILE_PATHS = {'index.html', BACKEND_PATH, REQUIREMENTS_PATH}


def normalize_path(path: str, source_format: str) -> str:
    value = path.strip().replace('\\', '/')
    while value.startswith('./'):
        value = value[2:]
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or '..' in pure.parts or str(pure) in {'', '.'}:
        raise AppSpecError(f'Invalid AppSpec source path: {path}')
    value = str(pure)
    if source_format == 'multi-file':
        exact = {
            'index.html': 'frontend/index.html',
            'package.json': 'frontend/package.json',
            'vite.config.js': 'frontend/vite.config.js',
            'main.py': BACKEND_PATH,
            'requirements.txt': REQUIREMENTS_PATH,
        }
        value = exact.get(value, value)
        if value.startswith('src/'):
            value = f'frontend/{value}'
        elif value.startswith('app/'):
            value = f'backend/{value}'
    else:
        if value == 'frontend/index.html':
            value = 'index.html'
        elif value == 'main.py':
            value = BACKEND_PATH
        elif value == 'requirements.txt':
            value = REQUIREMENTS_PATH
    return value


def allowed_path(path: str, source_format: str, backend_mode: str) -> bool:
    if backend_mode == 'static' and path.startswith('backend/'):
        return False
    if source_format == 'single-file':
        return path in _SINGLE_FILE_PATHS
    return path in _MULTI_FILE_PATHS or bool(
        re.fullmatch(r'frontend/src/components/[A-Za-z0-9_-]+\.jsx', path),
    )


def normalize_spec_manifest(spec: AppSpec) -> AppSpec:
    source_format = spec.architecture.source_format
    document = spec.model_dump(mode='json', exclude_none=True)
    for item in document['manifest']['files']:
        item['path'] = normalize_path(item['path'], source_format)
    document['manifest']['generation_order'] = [
        normalize_path(path, source_format) for path in spec.manifest.generation_order
    ]
    return parse_appspec(document)


def normalize_source_files(source_files: dict[str, str], source_format: str) -> dict[str, str]:
    normalized = {}
    for path, content in source_files.items():
        target = normalize_path(path, source_format)
        if target in normalized:
            raise AppSpecError(f'Multiple source files normalize to {target}')
        if not isinstance(content, str):
            raise AppSpecError(f'Source file {target} must be text')
        normalized[target] = content
    return normalized


def validate_manifest(spec: AppSpec, source_files: dict[str, str]) -> None:
    architecture = spec.architecture
    declared = {item.path: item for item in spec.manifest.files}
    for path, item in declared.items():
        if not allowed_path(path, architecture.source_format, architecture.backend_mode):
            raise AppSpecError(f'AppSpec manifest contains an unapproved path: {path}')
        expected_area = 'backend' if path.startswith('backend/') else 'frontend'
        if item.owner not in {expected_area, 'supervisor', 'legacy'}:
            raise AppSpecError(f'Manifest owner {item.owner} cannot write {path}')
    for path, content in source_files.items():
        if path not in declared:
            raise AppSpecError(f'Source file is not declared in the AppSpec manifest: {path}')
        if len(content.encode()) > declared[path].max_bytes:
            raise AppSpecError(f'Source file {path} exceeds its AppSpec size limit')


def build_manifest(spec: AppSpec, source_files: dict[str, str], spec_hash: str) -> dict:
    declared = {item.path: item for item in spec.manifest.files}
    files = [{
        'path': path,
        'owner': declared[path].owner,
        'bytes': len(source_files[path].encode()),
        'sha256': hashlib.sha256(source_files[path].encode()).hexdigest(),
    } for path in sorted(source_files)]
    generation_order = [path for path in spec.manifest.generation_order if path in source_files]
    generation_order.extend(path for path in sorted(source_files) if path not in generation_order)
    return {
        'schema_version': APPSPEC_SCHEMA_VERSION,
        'compiler_version': COMPILER_VERSION,
        'spec_hash': spec_hash,
        'files': files,
        'generation_order': generation_order,
        'dependencies': {
            'python': sorted(spec.dependencies.python),
            'npm': sorted(spec.dependencies.npm),
        },
    }
