"""Attempt-scoped cancellation, trace, and tool ownership propagated through async tasks."""

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from .models import JobCancelledError


@dataclass(frozen=True)
class ToolOwnership:
    tool_run_id: str
    process_group_id: int | None = None


@dataclass
class JobContext:
    user_id: int
    project_id: str
    job_id: str
    attempt_id: int
    trace_id: str
    cancellation: asyncio.Event
    _tools: dict[str, ToolOwnership] = field(default_factory=dict)

    @property
    def cancelled(self) -> bool:
        return self.cancellation.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise JobCancelledError('Generation cancelled. Retry this stage.')

    @property
    def tool_owners(self) -> dict[str, ToolOwnership]:
        return dict(self._tools)

    def own_tool(self, tool_run_id: str, process_group_id: int | None = None) -> ToolOwnership:
        if not tool_run_id:
            raise ValueError('tool_run_id is required')
        if process_group_id is not None and process_group_id <= 0:
            raise ValueError('process_group_id must be positive')
        ownership = ToolOwnership(tool_run_id, process_group_id)
        existing = self._tools.get(tool_run_id)
        if existing and existing != ownership:
            raise ValueError(f'Tool {tool_run_id} already has a different owner')
        self._tools[tool_run_id] = ownership
        return ownership

    def owns_tool(self, tool_run_id: str, process_group_id: int | None = None) -> bool:
        return self._tools.get(tool_run_id) == ToolOwnership(tool_run_id, process_group_id)

    def release_tool(self, tool_run_id: str) -> ToolOwnership | None:
        return self._tools.pop(tool_run_id, None)


_JOB_CONTEXT: ContextVar[JobContext | None] = ContextVar('forma_job_context', default=None)


def activate_job_context(context: JobContext) -> Token:
    return _JOB_CONTEXT.set(context)


def reset_job_context(token: Token) -> None:
    _JOB_CONTEXT.reset(token)


def current_job_context() -> JobContext | None:
    return _JOB_CONTEXT.get()
