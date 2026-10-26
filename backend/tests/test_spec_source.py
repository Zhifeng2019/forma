import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.spec.schema import AppSpecError


def generated(backend_mode: str, source_format: str, phase: int = 2):
    spec = local_default_appspec('Synthesized App', 'A generated workflow with persistent records.', source_format, backend_mode)
    return compile_package(spec, phase=phase)


@pytest.mark.parametrize('backend_mode', ['static', 'fastapi'])
@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
def test_appspec_synthesizes_complete_supported_packages(backend_mode, source_format):
    compiled = generated(backend_mode, source_format)
    files = compiled.files
    assert compiled.manifest['generation'] == {'mode': 'appspec', 'phase': 2}
    assert len(compiled.spec_hash) == len(compiled.source_hash) == 64
    assert compiled.manifest['spec_hash'] == compiled.spec_hash
    assert ('backend/main.py' in files) == (backend_mode == 'fastapi')
    frontend = files['frontend/src/App.jsx'] if source_format == 'multi-file' else files['index.html']
    assert 'Synthesized App' in frontend
    assert '__EDIT__' not in frontend and '__COLLECTION__' not in frontend
    if source_format == 'multi-file':
        assert 'true' in files['frontend/src/components/Workspace.jsx']
        assert '__FIELDS_JSON__' not in files['frontend/src/components/Workspace.jsx']
    if backend_mode == 'fastapi':
        backend = '\n'.join(content for path, content in files.items() if path.endswith('.py'))
        assert 'class ItemInput' in backend and 'class ItemPatch' in backend
        assert '/api/health' in backend and 'CREATE TABLE IF NOT EXISTS items' in backend


def test_synthesis_is_deterministic_and_phase_explicit():
    first = generated('fastapi', 'multi-file', phase=1)
    second = generated('fastapi', 'multi-file', phase=1)
    editable = generated('fastapi', 'multi-file', phase=2)
    assert first.files == second.files
    assert first.manifest == second.manifest
    assert first.spec_hash == editable.spec_hash
    assert first.source_hash != editable.source_hash
    assert editable.manifest['generation']['phase'] == 2


def test_custom_entity_drives_models_fields_and_database():
    spec = local_default_appspec('Task App', 'Track focused tasks.', 'multi-file', 'fastapi')
    document = spec.model_dump(mode='json', exclude_none=True)
    document['entities'][0]['name'] = 'Task'
    document['entities'][0]['fields'] = [
        {'name': 'id', 'kind': 'integer', 'required': True},
        {'name': 'title', 'kind': 'string', 'required': True, 'constraints': {'maxLength': 100}},
        {'name': 'estimate', 'kind': 'number', 'required': False, 'constraints': {'minimum': 0, 'maximum': 100}},
    ]
    for operation in document['api']:
        if operation['path'] != '/api/health':
            operation['entity'] = 'Task'
    compiled = compile_package(document, phase=2)
    models = compiled.files['backend/app/models.py']
    database = compiled.files['backend/app/database.py']
    workspace = compiled.files['frontend/src/components/Workspace.jsx']
    assert 'class TaskInput' in models and 'class TaskPatch' in models
    assert 'estimate: float | None' in models
    assert 'estimate REAL' in database
    assert 'Estimate' in workspace


def test_unsupported_multi_entity_synthesis_fails_closed():
    spec = local_default_appspec('Invalid App', 'Too many entities.', 'multi-file', 'fastapi')
    document = spec.model_dump(mode='json', exclude_none=True)
    second = dict(document['entities'][0])
    second['name'] = 'Second'
    document['entities'].append(second)
    with pytest.raises(AppSpecError, match='exactly one entity'):
        compile_package(document, phase=1)


def test_generated_fastapi_executes_crud_validation_and_restart_persistence():
    compiled = generated('fastapi', 'single-file', phase=2)
    database = settings.data_path / 'generated-spec-tests' / uuid.uuid4().hex / 'app.db'
    database.parent.mkdir(parents=True, exist_ok=True)
    source = compiled.files['backend/main.py'].replace('DATABASE = "app.db"', f'DATABASE = {str(database)!r}')
    namespace = {'__name__': 'generated_appspec_application'}
    exec(compile(source, 'backend/main.py', 'exec'), namespace)
    app = namespace['app']
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        initial = client.get('/api/items').json()['items']
        assert len(initial) == 1
        assert client.post('/api/items', json={'title': ' ', 'completed': False}).status_code == 422
        response = client.post('/api/items', json={'title': 'Verify AppSpec', 'completed': False})
        assert response.status_code == 201, response.text
        item = response.json()
        assert client.patch(f'/api/items/{item["id"]}', json={'title': ' '}).status_code == 422
        response = client.patch(f'/api/items/{item["id"]}', json={'completed': True})
        assert response.status_code == 200 and response.json()['completed'] is True
    with TestClient(app) as restarted:
        persisted = restarted.get('/api/items').json()['items']
        restored = next(row for row in persisted if row['id'] == item['id'])
        assert restored['title'] == 'Verify AppSpec' and restored['completed'] == 1
        assert len(persisted) == 2
        assert restarted.delete(f'/api/items/{item["id"]}').status_code == 204
        assert len(restarted.get('/api/items').json()['items']) == 1


def test_static_single_file_has_no_backend_or_server_adapter():
    compiled = generated('static', 'single-file')
    assert set(compiled.files) == {'index.html'}
    html = compiled.files['index.html']
    assert 'localStorage' in html and 'Forma.api' not in html and 'fetch(' not in html
