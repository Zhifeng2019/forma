"""Scoped specialist-worker contracts and deterministic supervision."""

from .contracts import WorkerPermissionError, WorkerResult, WorkerRole, WorkerTask
from .supervisor import plan_worker_tasks, synthesize_worker_source

__all__ = [
    'WorkerPermissionError', 'WorkerResult', 'WorkerRole', 'WorkerTask',
    'plan_worker_tasks', 'synthesize_worker_source',
]
