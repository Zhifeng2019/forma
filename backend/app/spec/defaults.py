"""Studio-owned AppSpec defaults for the v1 single-entity workflow."""

from ..source_packages import FRONTEND_DEPENDENCIES
from .schema import parse_appspec
from .types import AppSpec


def default_manifest(source_format: str, backend_mode: str) -> dict:
    if source_format == 'single-file':
        files = [{'path': 'index.html', 'owner': 'frontend', 'max_bytes': 250_000}]
        if backend_mode == 'fastapi':
            files.extend([
                {'path': 'backend/main.py', 'owner': 'backend', 'max_bytes': 80_000},
                {'path': 'backend/requirements.txt', 'owner': 'supervisor'},
            ])
    else:
        files = [
            {'path': path, 'owner': 'frontend'} for path in (
                'frontend/index.html', 'frontend/src/main.jsx', 'frontend/src/App.jsx',
                'frontend/src/api.js', 'frontend/src/components/Workspace.jsx', 'frontend/src/styles.css',
            )
        ]
        files.extend([
            {'path': 'frontend/package.json', 'owner': 'supervisor'},
            {'path': 'frontend/vite.config.js', 'owner': 'supervisor'},
        ])
        if backend_mode == 'fastapi':
            files.extend([
                {'path': path, 'owner': 'backend'} for path in (
                    'backend/main.py', 'backend/app/__init__.py', 'backend/app/api.py',
                    'backend/app/models.py', 'backend/app/database.py',
                )
            ])
            files.append({'path': 'backend/requirements.txt', 'owner': 'supervisor'})
    return {'files': files, 'generation_order': [item['path'] for item in files]}


def default_dependencies(source_format: str) -> dict:
    return {'python': [], 'npm': list(FRONTEND_DEPENDENCIES) if source_format == 'multi-file' else []}


def default_api(backend_mode: str, collection: str = 'items', entity_name: str = 'Item') -> list[dict]:
    if backend_mode == 'static':
        return []
    base = f'/api/{collection}'
    return [
        {'name': 'Runtime health', 'method': 'GET', 'path': '/api/health'},
        {'name': f'List {collection}', 'method': 'GET', 'path': base, 'entity': entity_name},
        {'name': f'Create {collection}', 'method': 'POST', 'path': base, 'entity': entity_name},
        {'name': f'Update {collection}', 'method': 'PATCH', 'path': f'{base}/{{item_id}}', 'entity': entity_name},
        {'name': f'Delete {collection}', 'method': 'DELETE', 'path': f'{base}/{{item_id}}', 'entity': entity_name},
    ]


def default_acceptance(backend_mode: str, source_format: str) -> list[dict]:
    checks = [
        {'name': 'Application source validation', 'kind': 'build',
         'target': 'frontend/dist/index.html' if source_format == 'multi-file' else 'index.html'},
        {'name': 'Primary browser workflow', 'kind': 'browser', 'target': '/'},
        {'name': 'Application data persistence', 'kind': 'persistence',
         'target': 'app.db' if backend_mode == 'fastapi' else 'localStorage'},
    ]
    if backend_mode == 'fastapi':
        checks.append({'name': 'Runtime health', 'kind': 'api', 'target': '/api/health'})
    return checks


def local_default_appspec(name: str, brief: str, source_format: str, backend_mode: str) -> AppSpec:
    return parse_appspec({
        'schema_version': '1.0',
        'compiler_version': '1.0',
        'product': {
            'name': name,
            'brief': brief,
            'users': ['People completing a focused workflow'],
            'primary_workflow': f'Create, update, and review items in {name}.',
            'acceptance_goals': ['Complete the primary workflow with persistent data.'],
        },
        'architecture': {
            'backend_mode': backend_mode,
            'source_format': source_format,
            'state_ownership': 'server' if backend_mode == 'fastapi' else 'browser',
        },
        'entities': [{
            'name': 'Item',
            'fields': [
                {'name': 'id', 'kind': 'integer', 'required': True},
                {'name': 'title', 'kind': 'string', 'required': True, 'constraints': {'maxLength': 160}},
                {'name': 'completed', 'kind': 'boolean', 'required': True},
            ],
            'relationships': [],
        }],
        'api': default_api(backend_mode),
        'frontend': {
            'components': ['App', 'Workspace'],
            'routes': ['/'],
            'state_adapter': 'forma-api' if backend_mode == 'fastapi' else 'browser-local',
            'accessibility': ['keyboard-navigation', 'responsive-layout'],
        },
        'dependencies': default_dependencies(source_format),
        'manifest': default_manifest(source_format, backend_mode),
        'acceptance': default_acceptance(backend_mode, source_format),
    })
