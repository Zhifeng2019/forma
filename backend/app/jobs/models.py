from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = 'queued'
    LEASED = 'leased'
    RUNNING = 'running'
    WAITING_ON_TOOL = 'waiting_on_tool'
    FINALIZING = 'finalizing'
    RETRY_SCHEDULED = 'retry_scheduled'
    WAITING_FOR_APPROVAL = 'waiting_for_approval'
    CANCEL_REQUESTED = 'cancel_requested'
    CANCELLING = 'cancelling'
    CANCELLED = 'cancelled'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'
    DEAD_LETTER = 'dead_letter'
    RECOVERY_REQUIRED = 'recovery_required'


class JobError(RuntimeError):
    pass


class IdempotencyConflictError(JobError):
    pass


class LeaseLostError(JobError):
    pass


class StaleJobError(JobError):
    pass
