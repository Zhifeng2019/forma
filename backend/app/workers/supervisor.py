"""Deterministic sequential supervision of scoped worker tasks."""

from ..spec.contract import entity_contract
from ..spec.source_backend import backend_sources
from ..spec.source_frontend import frontend_sources
from ..spec.types import AppSpec
from .contracts import (
    WorkerResult, WorkerRole, merge_worker_results, plan_worker_tasks,
)


def synthesize_worker_source(spec: AppSpec, phase: int = 1) -> dict[str, str]:
    """Execute role-scoped tasks without parallel scheduling or shared writes."""
    contract = entity_contract(spec)
    results = []
    for task in plan_worker_tasks(spec, phase):
        if task.role == WorkerRole.BACKEND:
            produced = backend_sources(contract, spec.product.name, spec.architecture.source_format)
        else:
            # The supervisor alone selects the shared adapter or composed HTML.
            produced = frontend_sources(spec, contract, phase)
        try:
            files = {path: produced[path] for path in task.paths}
        except KeyError as exc:
            raise RuntimeError(f'{task.role.value} synthesis did not produce {exc.args[0]}') from exc
        results.append(WorkerResult(task, files))
    return merge_worker_results(results)
