"""Deterministic parallel supervision with cooperative cancellation and safe merge."""

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

    def as_dict(self) -> dict:
        return {'role': self.role.value, 'paths': list(self.paths), 'source_hash': self.source_hash}


@dataclass(frozen=True)
class WorkerExecution:
    files: dict[str, str]
    workers: tuple[WorkerCompletion, ...]


def execute_worker_tasks(tasks: list[WorkerTask], runner, max_workers: int | None = None) -> list[WorkerResult]:
    """Run independent tasks concurrently and return results in plan order."""
    if not tasks:
        return []
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
            failures = [future for future in done if not future.cancelled() and future.exception() is not None]
            if failures or any(future.cancelled() for future in done):
                failures.sort(key=lambda future: tasks.index(futures[future]))
                error = failures[0].exception() if failures else JobCancelledError('Worker execution was cancelled.')
                break
            for future in done:
                completed[future] = future.result()
    except BaseException as exc:
        error = exc
    if error is not None:
        cancellation.set()
        for future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise error
    cancellation.set()
    executor.shutdown(wait=True, cancel_futures=True)
    return [completed[future] for future in futures]


def synthesize_worker_execution(spec: AppSpec, phase: int = 1) -> WorkerExecution:
    """Execute independent tasks in parallel and merge only validated complete output."""
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

    results = execute_worker_tasks(plan_worker_tasks(spec, phase), run)
    files = merge_worker_results(results)
    workers = tuple(
        WorkerCompletion(result.task.role, result.task.paths, canonical_input_hash(result.files))
        for result in results
    )
    return WorkerExecution(files, workers)


def synthesize_worker_source(spec: AppSpec, phase: int = 1) -> dict[str, str]:
    return synthesize_worker_execution(spec, phase).files
