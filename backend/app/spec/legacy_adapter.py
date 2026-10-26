"""Represent existing application packages as AppSpecs without regenerating them."""

from ..backend_engine import BACKEND_PATH
from ..source_packages import FRONTEND_DEPENDENCIES
from .manifest import normalize_source_files
from .schema import parse_appspec
from .types import AppSpec


def _python_dependencies(requirements: str) -> list[str]:
    dependencies = []
    for line in requirements.splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            dependencies.append(line.split('==', 1)[0].strip())
    return dependencies


def legacy_appspec(project: dict, source_files: dict[str, str]) -> AppSpec:
    """Describe known legacy contracts while leaving unknown domain semantics empty."""
    project = dict(project)
    source_format = project['source_format']
    backend_mode = project['backend_mode']
    files = normalize_source_files(source_files, source_format)
    brief = project['brief']
    manifest_files = [{
        'path': path,
        'owner': 'legacy',
        'max_bytes': 250_000 if path == 'index.html' else 80_000 if path == BACKEND_PATH else 140_000,
    } for path in sorted(files)]
    acceptance = [{
        'name': 'Existing package validation',
        'kind': 'build',
        'target': 'frontend/dist/index.html' if source_format == 'multi-file' else 'index.html',
    }]
    api = []
    if backend_mode == 'fastapi':
        api.append({'name': 'Runtime health', 'method': 'GET', 'path': '/api/health'})
        acceptance.append({'name': 'Existing runtime health', 'kind': 'api', 'target': '/api/health'})
    requirements = files.get('backend/requirements.txt', '')
    return parse_appspec({
        'schema_version': '1.0',
        'compiler_version': '1.0',
        'product': {
            'name': project['name'],
            'brief': brief,
            'users': [],
            'primary_workflow': brief[:2000],
            'acceptance_goals': ['Preserve existing application behavior'],
        },
        'architecture': {
            'backend_mode': backend_mode,
            'source_format': source_format,
            'state_ownership': 'server' if backend_mode == 'fastapi' else 'browser',
        },
        'entities': [],
        'api': api,
        'frontend': {
            'components': sorted(path for path in files if path.startswith('frontend/src/') and path.endswith('.jsx')),
            'routes': [],
            'state_adapter': 'forma-api' if backend_mode == 'fastapi' else 'browser-local',
            'accessibility': [],
        },
        'dependencies': {
            'python': _python_dependencies(requirements) if backend_mode == 'fastapi' else [],
            'npm': list(FRONTEND_DEPENDENCIES) if source_format == 'multi-file' else [],
        },
        'manifest': {
            'files': manifest_files,
            'generation_order': sorted(files),
        },
        'acceptance': acceptance,
    })
