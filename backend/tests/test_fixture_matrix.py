import json
import os
from pathlib import Path

import pytest

from app.source_packages import validate_source_package
from app.spec.schema import AppSpecError, parse_appspec
from fixtures.loader import FIXTURE_ROOT, FixtureError, FixtureManifest, FixturePack, query_one
from scripts.capture_baseline import FIXTURE_PACK_VERSION

TEST_DATA = Path(os.environ['DATA_DIR'])
PACKAGE_KEYS = {'static-single', 'fastapi-single', 'static-multi', 'fastapi-multi'}
STATES = {'current', 'historical'}
PUBLICATION_STATES = {'published', 'unpublished'}


def test_manifest_covers_architecture_history_and_publication_matrix():
    pack = FixturePack()
    assert pack.fixture_pack_version == FIXTURE_PACK_VERSION == '1.0'
    assert set(pack.manifest.packages) == PACKAGE_KEYS
    variants = pack.manifest.variants
    assert len(variants) == 16
    assert {(variant.package, variant.history, variant.publication) for variant in variants} == {
        (package, history, publication)
        for package in PACKAGE_KEYS for history in STATES for publication in PUBLICATION_STATES
    }
    for variant in variants:
        project = pack.projects[variant.key]
        expected_version = 2 if variant.history == 'historical' else 1
        assert project.current_version == expected_version
        assert project.published_version == (1 if variant.publication == 'published' else None)
        assert [version.version for version in project.versions] == list(range(1, expected_version + 1))
        expected_paths = [artifact.path for artifact in pack.package_artifacts(variant.package)]
        assert all([artifact.path for artifact in version.artifacts] == expected_paths
                   for version in project.versions)


def test_package_source_and_appspec_hashes_are_stable():
    pack = FixturePack()
    for key in PACKAGE_KEYS:
        expected = pack.manifest.packages[key].source_hash
        assert pack.source_hash(key) == expected
        assert FixturePack().source_hash(key) == expected
    assert pack.manifest.packages['fastapi-multi'].extends == 'static-multi'
    shared = [(artifact.path, artifact.source, artifact.sha256)
              for artifact in pack.manifest.packages['static-multi'].artifacts
              if artifact.path != 'frontend/src/api.js']
    inherited = [(artifact.path, artifact.source, artifact.sha256)
                 for artifact in pack.package_artifacts('fastapi-multi')
                 if artifact.path != 'frontend/src/api.js']
    assert inherited[:len(shared)] == shared
    adapter = next(artifact for artifact in pack.package_artifacts('fastapi-multi')
                   if artifact.path == 'frontend/src/api.js')
    assert adapter.source.endswith('api.fastapi.js')
    for key in ('static-multi', 'fastapi-multi'):
        package = pack.manifest.packages[key]
        normalized = validate_source_package(pack.package_files(key), package.backend_mode)
        assert normalized['frontend/src/api.js']
    document = pack.appspec('item-manager')
    assert document == FixturePack().appspec('item-manager')
    assert parse_appspec(document).product.name == 'Item Manager'


def test_provider_corpus_matches_declared_expected_outcomes():
    pack = FixturePack()
    expected = {
        'legacy-package': ('valid-package', 'accept'),
        'truncated-model-output': ('truncated-model-output', 'repair-once'),
        'invalid-json': ('invalid-json', 'repair-once'),
        'invalid-package-structure': ('invalid-package-structure', 'repair-once'),
        'missing-requirements': ('missing-requirements', 'normalize'),
        'empty-python-init': ('empty-python-init', 'accept'),
        'native-fetch-adapter': ('native-fetch-adapter', 'accept'),
        'invalid-appspec-contract': ('invalid-appspec-contract', 'reject'),
        'partial-package-overlay': ('partial-package-overlay', 'overlay'),
    }
    assert set(pack.manifest.providers) == set(expected)
    documents = {}
    for key, (category, handling) in expected.items():
        provider = pack.manifest.providers[key]
        assert (provider.expected.category, provider.expected.handling) == (category, handling)
        body = pack.read_resource(provider)
        if provider.content_type == 'application/json':
            documents[key] = json.loads(body)
    for key in ('truncated-model-output', 'invalid-json'):
        with pytest.raises(json.JSONDecodeError):
            json.loads(pack.read_resource(pack.manifest.providers[key]))
    with pytest.raises(AppSpecError):
        parse_appspec(documents['invalid-appspec-contract'])
    assert documents['empty-python-init']['files']['backend/app/__init__.py'] == ''
    assert "fetch('/api/health')" in documents['native-fetch-adapter']['files']['index.html']
    assert 'uvicorn' not in documents['missing-requirements']['files']['requirements.txt']
    assert list(documents['partial-package-overlay']['files']) == ['frontend/src/components/Workspace.jsx']
    assert 'index.html' in documents['legacy-package']['files']


def test_every_variant_materializes_with_expected_history_and_registry_state():
    pack = FixturePack()
    for variant in pack.manifest.variants:
        workspace = pack.workspace(TEST_DATA / f'matrix-{variant.key}')
        result = workspace.materialize_project(variant.key)
        project = pack.projects[variant.key]
        row = query_one(result.workspace_db,
                        'SELECT current_version,published_version FROM projects WHERE id=?',
                        (result.project_id,))
        assert dict(row) == {
            'current_version': project.current_version,
            'published_version': project.published_version,
        }
        versions = query_one(result.workspace_db,
                             'SELECT COUNT(*) AS count FROM versions WHERE project_id=?',
                             (result.project_id,))
        assert versions['count'] == len(project.versions)
        registry = query_one(result.control_db,
                             'SELECT COUNT(*) AS count FROM deployment_registry WHERE project_id=?',
                             (result.project_id,))
        assert registry['count'] == int(variant.publication == 'published')
        for version in project.versions:
            for artifact in version.artifacts:
                target = result.project_dir / 'versions' / f'v{version.version}' / artifact.path
                assert target.read_text(encoding='utf-8') == pack.read_resource(artifact)


def test_manifest_rejects_unknown_packages_and_inheritance_cycles():
    document = json.loads((FIXTURE_ROOT / 'manifest.json').read_text(encoding='utf-8'))
    document['variants'][0]['package'] = 'unknown-package'
    with pytest.raises(ValueError, match='unknown package'):
        FixtureManifest.model_validate(document)

    pack = FixturePack()
    pack.manifest.packages['fastapi-multi'].extends = 'fastapi-multi'
    with pytest.raises(FixtureError, match='cycle'):
        pack.package_artifacts('fastapi-multi')
