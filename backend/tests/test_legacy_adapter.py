import json

import pytest

from app.backend_engine import BACKEND_PATH, REQUIREMENTS_PATH, local_backend_html, local_backend_source, validate_application
from app.config import Settings
from app.features import FeatureDisabledError
from app.local_engine import application_html
from app.source_packages import local_source_package
from app.spec.legacy_adapter import legacy_appspec
from app.spec.service import compile_legacy_package, spec_artifacts


def legacy_package(source_format: str, backend_mode: str) -> tuple[dict, dict[str, str]]:
    project = {
        'name': 'Legacy Workspace',
        'brief': 'Preserve this existing application without regeneration.',
        'backend_mode': backend_mode,
        'source_format': source_format,
    }
    if source_format == 'multi-file':
        return project, local_source_package(project['name'], project['brief'], 1, backend_mode)
    if backend_mode == 'fastapi':
        html, python, requirements = validate_application(
            local_backend_html(project['name'], project['brief'], 1), local_backend_source(project['name']),
        )
        return project, {'index.html': html, BACKEND_PATH: python, REQUIREMENTS_PATH: requirements}
    return project, {'index.html': application_html(project['name'], project['brief'], 1)}


@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
@pytest.mark.parametrize('backend_mode', ['static', 'fastapi'])
def test_legacy_adapter_preserves_source_architecture_and_format(source_format, backend_mode):
    project, files = legacy_package(source_format, backend_mode)
    original = dict(files)
    spec = legacy_appspec(project, files)
    assert spec.architecture.backend_mode == backend_mode
    assert spec.architecture.source_format == source_format
    assert spec.architecture.state_ownership == ('server' if backend_mode == 'fastapi' else 'browser')
    assert spec.entities == []
    assert [operation.path for operation in spec.api] == (['/api/health'] if backend_mode == 'fastapi' else [])
    enabled = Settings(appspec_v1=True)
    compiled = compile_legacy_package(project, files, enabled)
    assert compiled.files == original
    assert files == original
    artifacts = spec_artifacts(compiled)
    assert set(artifacts) == {
        'appspec.json', 'build-manifest.json', 'acceptance/api_tests.py',
        'acceptance/browser_tests.spec.js', 'acceptance/security_tests.py',
        'acceptance/migration_tests.py', 'acceptance/manifest.json',
    }
    document = json.loads(artifacts['appspec.json'])
    manifest = json.loads(artifacts['build-manifest.json'])
    assert document['spec_hash'] == compiled.spec_hash
    assert manifest['source_hash'] == compiled.source_hash
    assert set(manifest['files'][0]) == {'path', 'owner', 'bytes', 'sha256'}


def test_legacy_compilation_requires_the_appspec_flag():
    project, files = legacy_package('single-file', 'static')
    with pytest.raises(FeatureDisabledError, match='appspec_v1'):
        compile_legacy_package(project, files, Settings(appspec_v1=False))
