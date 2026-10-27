import json
import os
from pathlib import Path

import pytest

from app.config import settings
from app.spec.schema import parse_appspec
from fixtures.loader import (
    FIXTURE_ROOT, FixtureError, FixtureManifest, FixturePack, query_one,
)
from scripts.capture_baseline import FIXTURE_PACK_VERSION

TEST_DATA = Path(os.environ['DATA_DIR'])


def test_manifest_is_versioned_and_preserves_existing_appspec():
    pack = FixturePack()
    assert pack.manifest.schema_version == '1.0'
    assert pack.fixture_pack_version == FIXTURE_PACK_VERSION
    spec = parse_appspec(pack.appspec('item-manager'))
    assert spec.product.name == 'Item Manager'
    assert spec.architecture.backend_mode == 'fastapi'
    assert spec.architecture.source_format == 'multi-file'


def test_workspace_materializes_versions_artifacts_and_publication_state():
    workspace = FixturePack().workspace(TEST_DATA / 'project-fixture')
    result = workspace.materialize_project('static-history', user_id=910001)
    assert result.current_version == 2
    assert result.published_version == 1
    assert result.workspace_db.is_file()
    assert result.project_dir.is_relative_to(workspace.data_dir)

    project = query_one(result.workspace_db,
                        'SELECT current_version,published_version FROM projects WHERE id=?',
                        (result.project_id,))
    assert dict(project) == {'current_version': 2, 'published_version': 1}
    versions = query_one(result.workspace_db,
                         'SELECT COUNT(*) AS count FROM versions WHERE project_id=?',
                         (result.project_id,))
    assert versions['count'] == 2
    historical = query_one(result.workspace_db,
                           'SELECT content FROM artifacts WHERE project_id=? AND version=1 AND path=?',
                           (result.project_id, 'index.html'))
    assert 'Fixture version 1' in historical['content']
    current = query_one(result.workspace_db,
                        'SELECT content FROM artifacts WHERE project_id=? AND version=2 AND path=?',
                        (result.project_id, 'index.html'))
    assert 'Fixture version 2' in current['content']
    assert (result.project_dir / 'versions' / 'v1' / 'index.html').read_text(encoding='utf-8') == historical['content']
    assert (result.project_dir / 'versions' / 'v2' / 'index.html').read_text(encoding='utf-8') == current['content']

    deployment = query_one(result.control_db,
                           'SELECT user_id,published_version,backend_mode,source_format '
                           'FROM deployment_registry WHERE project_id=?',
                           (result.project_id,))
    assert dict(deployment) == {
        'user_id': 910001, 'published_version': 1,
        'backend_mode': 'static', 'source_format': 'single-file',
    }
    with pytest.raises(FixtureError, match='already materialized'):
        workspace.materialize_project('static-history', user_id=910001)


def test_provider_response_materializes_inside_fixture_workspace():
    workspace = FixturePack().workspace(TEST_DATA / 'provider-fixture')
    response = workspace.materialize_provider('legacy-package')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.path.is_relative_to(workspace.data_dir)
    assert response.path.read_text(encoding='utf-8') == response.body
    assert json.loads(response.body)['name'] == 'Fixture Item Manager'


def test_workspace_refuses_application_or_unmarked_directories():
    pack = FixturePack()
    with pytest.raises(FixtureError, match='nonempty'):
        pack.workspace(settings.data_path)
    occupied = TEST_DATA / 'occupied-fixture'
    occupied.mkdir()
    preserved = occupied / 'keep.txt'
    preserved.write_text('do not modify', encoding='utf-8')
    with pytest.raises(FixtureError, match='nonempty'):
        pack.workspace(occupied)
    assert preserved.read_text(encoding='utf-8') == 'do not modify'
    with pytest.raises(FixtureError, match='absolute'):
        pack.workspace(Path('relative-fixture'))


def test_manifest_rejects_artifact_traversal():
    document = json.loads((FIXTURE_ROOT / 'manifest.json').read_text(encoding='utf-8'))
    document['projects'][0]['versions'][0]['artifacts'][0]['path'] = '../escape.html'
    with pytest.raises(ValueError, match='canonical relative POSIX paths'):
        FixtureManifest.model_validate(document)


def test_checksum_mismatch_fails_before_workspace_writes():
    pack = FixturePack()
    pack.projects['static-history'].versions[0].artifacts[0].sha256 = '0' * 64
    workspace = pack.workspace(TEST_DATA / 'checksum-fixture')
    with pytest.raises(FixtureError, match='checksum mismatch'):
        workspace.materialize_project('static-history', user_id=910002)
    assert not workspace.control_db.exists()
    assert not workspace.workspace_db(910002).exists()
    assert not (workspace.data_dir / 'projects').exists()
