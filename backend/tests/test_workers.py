import asyncio

import pytest

from app.config import Settings, settings
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.spec.service import generate_appspec_package
from app.workers.contracts import (
    SHARED_API_ADAPTER, WorkerPermissionError, WorkerResult, WorkerRole,
    assert_worker_data_safe, merge_worker_results, plan_worker_tasks,
)
from app.workers.credentials import CredentialBroker


def test_worker_plan_scopes_files_data_and_shared_adapter():
    spec = local_default_appspec('Scoped App', 'A scoped worker application.', 'multi-file', 'fastapi')
    tasks = plan_worker_tasks(spec, 1)
    assert [task.role for task in tasks] == [WorkerRole.FRONTEND, WorkerRole.BACKEND, WorkerRole.SUPERVISOR]
    frontend, backend, supervisor = tasks
    assert all(path.startswith('frontend/') for path in frontend.paths)
    assert SHARED_API_ADAPTER not in frontend.paths
    assert 'frontend/package.json' not in frontend.paths
    assert all(path.startswith('backend/') for path in backend.paths)
    assert supervisor.paths == (SHARED_API_ADAPTER,)
    assert 'python' not in frontend.data['dependencies']
    assert 'npm' not in backend.data['dependencies']
    assert 'frontend' not in backend.data
    assert frontend.data['manifest']['files'] == [
        {'path': path, 'owner': 'frontend'} for path in frontend.paths
    ]
    assert supervisor.data['manifest']['files'] == [{'path': SHARED_API_ADAPTER, 'owner': 'supervisor'}]


def test_worker_result_rejects_out_of_scope_and_duplicate_writes():
    spec = local_default_appspec('Scoped App', 'A scoped worker application.', 'multi-file', 'fastapi')
    frontend = next(task for task in plan_worker_tasks(spec, 1) if task.role == WorkerRole.FRONTEND)
    with pytest.raises(WorkerPermissionError, match='out_of_scope'):
        merge_worker_results([WorkerResult(frontend, {'backend/app/api.py': 'forbidden'})])
    valid = {path: 'source' for path in frontend.paths}
    with pytest.raises(WorkerPermissionError, match='Conflicting worker writes'):
        merge_worker_results([WorkerResult(frontend, valid), WorkerResult(frontend, valid)])


def test_worker_data_and_credentials_cannot_cross_role_boundaries():
    with pytest.raises(WorkerPermissionError, match='credential field'):
        assert_worker_data_safe({'api_key': 'secret'})
    with pytest.raises(WorkerPermissionError, match='credential-like content'):
        assert_worker_data_safe({'url': 'https://example.com?token=secret'})
    spec = local_default_appspec('Scoped App', 'A scoped worker application.', 'multi-file', 'fastapi')
    document = spec.model_dump(mode='json', exclude_none=True)
    document['product']['brief'] = 'api_key=super-secret'
    with pytest.raises(WorkerPermissionError, match='credential-like content'):
        plan_worker_tasks(spec.__class__.model_validate(document), 1)

    provider = {'name': 'Provider', 'api_key_encrypted': 'encrypted'}
    broker = CredentialBroker(provider)
    assert broker.for_role(WorkerRole.SUPERVISOR) == provider
    assert broker.for_role(WorkerRole.SUPERVISOR) is not provider
    for role in (WorkerRole.FRONTEND, WorkerRole.BACKEND):
        with pytest.raises(WorkerPermissionError, match='cannot access provider credentials'):
            broker.for_role(role)


def test_single_file_shared_document_is_supervisor_owned():
    spec = local_default_appspec('Scoped App', 'A scoped worker application.', 'single-file', 'fastapi')
    tasks = plan_worker_tasks(spec, 1)
    assert [task.role for task in tasks] == [WorkerRole.BACKEND, WorkerRole.SUPERVISOR]
    assert tasks[0].paths == ('backend/main.py',)
    assert tasks[1].paths == ('index.html',)


def test_supervised_synthesis_is_byte_equivalent_to_sequential_generation():
    for source_format in ('multi-file', 'single-file'):
        spec = local_default_appspec('Scoped App', 'A scoped worker application.', source_format, 'fastapi')
        sequential = compile_package(spec, phase=2, specialist_workers=False)
        supervised = compile_package(spec, phase=2, specialist_workers=True)
        assert supervised.files == sequential.files
        assert supervised.source_hash == sequential.source_hash
        assert supervised.spec_hash == sequential.spec_hash
        assert supervised.manifest['generation']['mode'] == 'supervised-parallel'
        assert sequential.manifest['generation']['mode'] == 'appspec'


def test_feature_flag_selects_supervised_generation_service(monkeypatch):
    monkeypatch.setattr(settings, 'specialist_workers_v1', True)
    project = {
        'name': 'Scoped Service', 'brief': 'Verify supervised service generation.',
        'source_format': 'multi-file', 'backend_mode': 'fastapi',
    }
    compiled = asyncio.run(generate_appspec_package(
        project, None, 1, config=Settings(appspec_v1=True, specialist_workers_v1=True),
    ))
    assert compiled.manifest['generation']['mode'] == 'supervised-parallel'
