"""Supervisor-only access to provider credentials."""

from .contracts import WorkerPermissionError, WorkerRole


class CredentialBroker:
    """Keep provider configuration outside worker task payloads."""

    def __init__(self, provider: dict | None):
        self._provider = dict(provider) if provider else None

    def for_role(self, role: WorkerRole) -> dict | None:
        if role != WorkerRole.SUPERVISOR:
            raise WorkerPermissionError(f'{role.value} workers cannot access provider credentials')
        return dict(self._provider) if self._provider else None
