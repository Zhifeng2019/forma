import asyncio
import threading

import pytest

from app.jobs.context import JobContext, activate_job_context, reset_job_context
from app.jobs.idempotency import canonical_input_hash
from app.jobs.models import JobCancelledError
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.workers.contracts import WorkerResult, WorkerRole, WorkerTask
from app.workers.supervisor import execute_worker_tasks


def task(role, path):
    return WorkerTask(role, 1, (path,), {})


def test_parallel_tasks_actually_overlap_and_merge_in_plan_order():
    barrier = threading.Barrier(2)
    tasks = [task(WorkerRole.FRONTEND, 'frontend/App.jsx'), task(WorkerRole.BACKEND, 'backend/main.py')]

    def run(current, _cancellation):
        barrier.wait(timeout=2)
        return WorkerResult(current, {current.paths[0]: current.role.value})

    results = execute_worker_tasks(tasks, run, max_workers=2)
    assert [result.task.role for result in results] == [WorkerRole.FRONTEND, WorkerRole.BACKEND]
    assert results[0].files == {'frontend/App.jsx': 'frontend'}
    assert results[1].files == {'backend/main.py': 'backend'}


def test_failure_cancels_other_workers_without_returning_partial_output():
    cancelled = threading.Event()
    started = threading.Event()
    tasks = [task(WorkerRole.FRONTEND, 'frontend/App.jsx'), task(WorkerRole.BACKEND, 'backend/main.py')]

    def run(current, cancellation):
        if current.role == WorkerRole.FRONTEND:
            started.set()
            if cancellation.wait(2):
                cancelled.set()
            raise JobCancelledError('stop slow worker')
        assert started.wait(1)
        raise ValueError('deliberate worker failure')

    with pytest.raises(ValueError, match='deliberate worker failure'):
        execute_worker_tasks(tasks, run, max_workers=2)
    assert cancelled.is_set()


def test_parent_job_cancellation_stops_parallel_execution():
    context = JobContext(1, 'project', 'job', 1, 'trace', asyncio.Event())
    token = activate_job_context(context)
    started = threading.Event()

    def run(current, cancellation):
        started.set()
        context.cancellation.set()
        cancellation.wait(2)
        return WorkerResult(current, {current.paths[0]: 'must not be returned'})

    try:
        with pytest.raises(JobCancelledError):
            execute_worker_tasks([task(WorkerRole.FRONTEND, 'frontend/App.jsx')], run)
        assert started.is_set()
    finally:
        reset_job_context(token)


def test_parallel_manifest_is_deterministic_and_preserves_worker_provenance():
    spec = local_default_appspec('Parallel App', 'A parallel worker application.', 'multi-file', 'fastapi')
    sequential = compile_package(spec, phase=2, specialist_workers=False)
    first = compile_package(spec, phase=2, specialist_workers=True)
    second = compile_package(spec, phase=2, specialist_workers=True)
    assert first.files == sequential.files == second.files
    assert first.source_hash == sequential.source_hash == second.source_hash
    assert first.spec_hash == sequential.spec_hash == second.spec_hash
    assert first.manifest['generation'] == second.manifest['generation']
    generation = first.manifest['generation']
    assert generation['mode'] == 'supervised-parallel'
    assert [worker['role'] for worker in generation['workers']] == ['frontend', 'backend', 'supervisor']
    for worker in generation['workers']:
        files = {path: first.files[path] for path in worker['paths']}
        assert worker['source_hash'] == canonical_input_hash(files)


def test_parallel_single_file_output_remains_byte_equivalent():
    spec = local_default_appspec('Parallel App', 'A parallel worker application.', 'single-file', 'fastapi')
    sequential = compile_package(spec, phase=2, specialist_workers=False)
    parallel = compile_package(spec, phase=2, specialist_workers=True)
    assert parallel.files == sequential.files
    assert parallel.source_hash == sequential.source_hash
    assert parallel.spec_hash == sequential.spec_hash
    assert parallel.manifest['generation']['mode'] == 'supervised-parallel'
    assert [worker['role'] for worker in parallel.manifest['generation']['workers']] == ['backend', 'supervisor']
