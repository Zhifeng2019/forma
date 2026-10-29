"""Deterministic parallel supervision with bounded failed-worker repair."""

from concurrent.futures import FIRST_EXCEPTION, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import threading

from ..jobs.context import current_job_context
from ..jobs.idempotency import canonical_input_hash
from ..jobs.models import JobCancelledError
from ..spec.contract import entity_contract
from ..spec.source_backend import backend_sources
from ..spec.source_frontend import frontend_sources
from ..spec.types import AppSpec
from .contracts import (
    WorkerResult, WorkerRole, WorkerTask, merge_worker_results, plan_worker_tasks,
)


@dataclass(frozen=True)
class WorkerCompletion:
    role: WorkerRole
    paths: tuple[str, ...]
    source_hash: str
    repair_count: int = 0

    def as_dict(self) -> dict:
        return {
            'role': self.role.value, 'paths': list(self.paths),
            'source_hash': self.source_hash, 'repair_count': self.repair_count,
        }


@dataclass(frozen=True)
class WorkerExecution:
    files: dict[str, str]
    workers: tuple[WorkerCompletion, ...]


def _execute_worker_tasks(
    tasks: list[WorkerTask], runner, max_workers: int | None = None,
) -> tuple[list[WorkerResult], BaseException | None]:
    if not tasks:
        return [], None
    context = current_job_context()
    if context:
        context.raise_if_cancelled()
    cancellation = threading.Event()
    executor = ThreadPoolExecutor(max_workers=max_workers or len(tasks))
    futures: dict[Future, WorkerTask] = {
        executor.submit(runner, task, cancellation): task for task in tasks
    }
    pending = set(futures)
    completed: dict[Future, WorkerResult] = {}
    error = None
    try:
        while pending:
            if context and context.cancelled:
                error = JobCancelledError('Generation cancelled. Retry this stage.')
                break
            done, pending = wait(pending, timeout=0.05, return_when=FIRST_EXCEPTION)
            for future in done:
                if not future.cancelled() and future.exception() is None:
                    completed[future] = future.result()
            failures = [future for future in done if not future.cancelled() and future.exception() is not None]
            if failures or any(future.cancelled() for future in done):
                failures.sort(key=lambda future: tasks.index(futures[future]))
                error = failures[0].exception() if failures else JobCancelledError('Worker execution was cancelled.')
                break
    except BaseException as exc:
        error = exc
    if error is not None:
        cancellation.set()
        for future in pending:
            future.cancel()
    executor.shutdown(wait=True, cancel_futures=True)
    results = [completed[future] for future in futures if future in completed]
    return results, error


def execute_worker_tasks(tasks: list[WorkerTask], runner, max_workers: int | None = None) -> list[WorkerResult]:
    """Run one attempt without repair and never return partial output."""
    results, error = _execute_worker_tasks(tasks, runner, max_workers)
    if error is not None:
        raise error
    return results


def repair_worker_tasks(
    tasks: list[WorkerTask], runner, repair_attempts: int = 1,
    repair_runner=None, max_workers: int | None = None,
) -> tuple[list[WorkerResult], set[str]]:
    """Retry only failed task IDs while preserving successful worker results."""
    if repair_attempts < 0:
        raise ValueError('repair_attempts must be non-negative')
    results, error = _execute_worker_tasks(tasks, runner, max_workers)
    if error is not None and repair_attempts == 0:
        raise error
    repaired_ids = set()
    for _attempt in range(repair_attempts):
        if error is None:
            break
        failed = [task for task in tasks if task.task_id not in {result.task.task_id for result in results}]
        if not failed:
            break
        retry, error = _execute_worker_tasks(failed, repair_runner or runner, max_workers)
        results.extend(retry)
        repaired_ids.update(task.task_id for task in failed)
    if error is not None:
        raise error
    by_id = {result.task.task_id: result for result in results}
    return [by_id[task.task_id] for task in tasks], repaired_ids


def synthesize_worker_execution(
    spec: AppSpec, phase: int = 1, repair_attempts: int = 1, runner=None, repair_runner=None,
) -> WorkerExecution:
    """Merge complete output after bounded, failed-worker-only repair."""
    contract = entity_contract(spec)

    def run(task: WorkerTask, cancellation: threading.Event) -> WorkerResult:
        if cancellation.is_set():
            raise JobCancelledError('Generation cancelled. Retry this stage.')
        if task.role == WorkerRole.BACKEND:
            produced = backend_sources(contract, spec.product.name, spec.architecture.source_format)
        else:
            # The supervisor alone selects the shared adapter or composed HTML.
            produced = frontend_sources(spec, contract, phase)
        try:
            files = {path: produced[path] for path in task.paths}
        except KeyError as exc:
            raise RuntimeError(f'{task.role.value} synthesis did not produce {exc.args[0]}') from exc
        if cancellation.is_set():
            raise JobCancelledError('Generation cancelled. Retry this stage.')
        return WorkerResult(task, files)

    results, repaired_ids = repair_worker_tasks(
        plan_worker_tasks(spec, phase), runner or run, repair_attempts, repair_runner,
    )
    files = merge_worker_results(results)
    workers = tuple(
        WorkerCompletion(
            result.task.role, result.task.paths, canonical_input_hash(result.files),
            repair_count=1 if result.task.task_id in repaired_ids else 0,
        )
        for result in results
    )
    return WorkerExecution(files, workers)


def synthesize_worker_source(spec: AppSpec, phase: int = 1) -> dict[str, str]:
    return synthesize_worker_execution(spec, phase).files
