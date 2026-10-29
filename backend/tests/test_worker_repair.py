import pytest

from app.jobs.idempotency import canonical_input_hash
from app.spec.defaults import local_default_appspec
from app.workers.contracts import (
    WorkerPermissionError, WorkerResult, WorkerRole, WorkerTask, repair_worker_result,
)
from app.workers.supervisor import repair_worker_tasks, synthesize_worker_execution


def tasks():
    return [
        WorkerTask(WorkerRole.FRONTEND, 1, ('frontend/App.jsx',), {}),
        WorkerTask(WorkerRole.BACKEND, 1, ('backend/main.py',), {}),
    ]


def test_only_failed_worker_is_repaired_and_marked_in_provenance():
    spec = local_default_appspec('Repair App', 'A file repair application.', 'multi-file', 'fastapi')
    calls = {role.value: 0 for role in WorkerRole}

    def flaky(task, _cancellation):
        calls[task.role.value] += 1
        if task.role == WorkerRole.BACKEND and calls['backend'] == 1:
            raise ValueError('transient backend failure')
        return WorkerResult(task, {path: f'{task.role.value}-final' for path in task.paths})

    execution = synthesize_worker_execution(spec, 1, repair_attempts=1, runner=flaky)
    assert calls == {'frontend': 1, 'backend': 2, 'supervisor': 1}
    workers = {worker.role.value: worker for worker in execution.workers}
    assert workers['frontend'].repair_count == 0
    assert workers['backend'].repair_count == 1
    assert workers['supervisor'].repair_count == 0
    assert all(content == 'backend-final' for path, content in execution.files.items() if path.startswith('backend/'))


def test_permanent_failure_returns_no_partial_output_and_zero_means_no_repair():
    calls = {'frontend': 0, 'backend': 0}

    def failing(task, _cancellation):
        calls[task.role.value] += 1
        if task.role == WorkerRole.BACKEND:
            raise ValueError('permanent failure')
        return WorkerResult(task, {path: 'unrelated-success' for path in task.paths})

    with pytest.raises(ValueError, match='permanent failure'):
        repair_worker_tasks(tasks(), failing, repair_attempts=1)
    assert calls == {'frontend': 1, 'backend': 2}
    calls = {'frontend': 0, 'backend': 0}
    with pytest.raises(ValueError, match='permanent failure'):
        repair_worker_tasks(tasks(), failing, repair_attempts=0)
    assert calls == {'frontend': 1, 'backend': 1}


def test_file_repair_preserves_every_unrelated_hash():
    task = WorkerTask(WorkerRole.FRONTEND, 1, ('frontend/App.jsx', 'frontend/Workspace.jsx', 'frontend/styles.css'), {})
    original = WorkerResult(task, {
        'frontend/App.jsx': 'app-original',
        'frontend/Workspace.jsx': 'workspace-original',
        'frontend/styles.css': 'styles-original',
    })
    unrelated_before = canonical_input_hash({
        'frontend/App.jsx': 'app-original', 'frontend/styles.css': 'styles-original',
    })
    repaired = repair_worker_result(
        original, ('frontend/Workspace.jsx',),
        lambda _task, failed: {path: 'workspace-repaired' for path in failed},
    )
    assert repaired.files['frontend/Workspace.jsx'] == 'workspace-repaired'
    assert repaired.files['frontend/App.jsx'] == 'app-original'
    assert repaired.files['frontend/styles.css'] == 'styles-original'
    unrelated_after = canonical_input_hash({
        'frontend/App.jsx': repaired.files['frontend/App.jsx'],
        'frontend/styles.css': repaired.files['frontend/styles.css'],
    })
    assert unrelated_after == unrelated_before


def test_file_repair_rejects_paths_outside_the_failed_scope():
    task = WorkerTask(WorkerRole.FRONTEND, 1, ('frontend/App.jsx', 'frontend/Workspace.jsx'), {})
    original = WorkerResult(task, {'frontend/App.jsx': 'app', 'frontend/Workspace.jsx': 'workspace'})
    with pytest.raises(WorkerPermissionError, match='subset'):
        repair_worker_result(original, ('backend/main.py',), lambda _task, failed: failed)
    with pytest.raises(WorkerPermissionError, match='exactly the failed paths'):
        repair_worker_result(
            original, ('frontend/Workspace.jsx',),
            lambda _task, failed: {**failed, 'frontend/App.jsx': 'changed-unrelated'},
        )
    with pytest.raises(WorkerPermissionError, match='must be text'):
        repair_worker_result(original, ('frontend/Workspace.jsx',), lambda _task, _failed: {'frontend/Workspace.jsx': 42})
