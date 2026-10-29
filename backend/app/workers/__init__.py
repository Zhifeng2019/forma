"""Scoped specialist-worker contracts and deterministic supervision."""

from .contracts import WorkerPermissionError, WorkerResult, WorkerRole, WorkerTask, repair_worker_result
from .supervisor import (
    execute_worker_tasks, plan_worker_tasks, repair_worker_tasks,
    synthesize_worker_execution, synthesize_worker_source,
)

__all__ = [
    'WorkerPermissionError', 'WorkerResult', 'WorkerRole', 'WorkerTask',
    'execute_worker_tasks', 'plan_worker_tasks', 'repair_worker_result', 'repair_worker_tasks',
    'synthesize_worker_execution', 'synthesize_worker_source',
]
