import copy

import pytest

from app.backend_engine import REQUIREMENTS_PATH
from app.llm import GenerationError
from app.source_packages import frontend_package_json, local_source_package
from app.spec.compiler import compile_package
from app.spec.schema import AppSpecError, parse_appspec
from fixtures.loader import FixturePack


def fixture_document() -> dict:
    return FixturePack().appspec('item-manager')


def source_files() -> dict[str, str]:
    return local_source_package('Item Manager', 'A shared workspace for tracking item priorities.', 2, 'fastapi')


def test_manifest_and_hashes_are_deterministic():
    spec = parse_appspec(fixture_document())
    first = compile_package(spec, source_files())
    second = compile_package(spec, dict(reversed(list(source_files().items()))))
    assert first.manifest == second.manifest
    assert first.spec_hash == second.spec_hash
    assert first.source_hash == second.source_hash
    assert first.manifest['spec_hash'] == first.spec_hash
    assert first.manifest['source_hash'] == first.source_hash
    assert [item['path'] for item in first.manifest['files']] == sorted(first.files)
    assert all(len(item['sha256']) == 64 for item in first.manifest['files'])


def test_common_path_aliases_normalize_to_the_same_package():
    aliases = {
        'frontend/index.html': 'index.html',
        'frontend/src/App.jsx': 'src/App.jsx',
        'backend/main.py': 'main.py',
        'backend/app/api.py': 'app/api.py',
        'backend/requirements.txt': 'requirements.txt',
    }
    document = copy.deepcopy(fixture_document())
    for item in document['manifest']['files']:
        item['path'] = aliases.get(item['path'], item['path'])
    document['manifest']['generation_order'] = [
        aliases.get(path, path) for path in document['manifest']['generation_order']
    ]
    files = {aliases.get(path, path): content for path, content in source_files().items()}
    canonical = compile_package(fixture_document(), source_files())
    aliased = compile_package(document, files)
    assert aliased.files == canonical.files
    assert aliased.manifest == canonical.manifest
    assert aliased.spec_hash == canonical.spec_hash


def test_requirements_and_frontend_manifests_are_studio_generated():
    files = source_files()
    files[REQUIREMENTS_PATH] = 'fastapi==0.0.1\nrequests==1.0\n'
    files['frontend/package.json'] = '{"dependencies":{"react":"0.0.1"}}'
    compiled = compile_package(fixture_document(), files)
    assert '0.0.1' not in compiled.files[REQUIREMENTS_PATH]
    assert 'requests' not in compiled.files[REQUIREMENTS_PATH]
    assert 'fastapi==' in compiled.files[REQUIREMENTS_PATH]
    assert compiled.files['frontend/package.json'] == frontend_package_json()


def test_unapproved_dependency_is_rejected():
    document = fixture_document()
    document['dependencies']['python'] = ['requests']
    with pytest.raises(GenerationError, match='Unsupported Python dependency'):
        compile_package(document, source_files())


def test_unapproved_manifest_path_is_rejected_before_source_validation():
    document = fixture_document()
    document['manifest']['files'].append({'path': 'frontend/src/Exploit.jsx', 'owner': 'frontend'})
    document['manifest']['generation_order'].append('frontend/src/Exploit.jsx')
    files = source_files()
    files['frontend/src/Exploit.jsx'] = 'export default function Exploit() { return null }\n'
    with pytest.raises(AppSpecError, match='unapproved path'):
        compile_package(document, files)


def test_source_must_be_declared_and_within_its_size_limit():
    files = source_files()
    files['frontend/src/components/Extra.jsx'] = 'export default function Extra() { return null }\n'
    with pytest.raises(AppSpecError, match='not declared'):
        compile_package(fixture_document(), files)
    document = fixture_document()
    item = next(item for item in document['manifest']['files'] if item['path'] == 'frontend/src/App.jsx')
    item['max_bytes'] = 10
    with pytest.raises(AppSpecError, match='size limit'):
        compile_package(document, source_files())
