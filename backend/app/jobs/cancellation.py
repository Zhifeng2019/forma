"""Cancellation signals shared by API actions and durable job attempts."""

import asyncio

_events: dict[str, asyncio.Event] = {}


def register_job(job_id: str) -> asyncio.Event:
    return _events.setdefault(job_id, asyncio.Event())


def cancellation_event(job_id: str) -> asyncio.Event | None:
    return _events.get(job_id)


def cancel_job(job_id: str) -> None:
    if event := _events.get(job_id):
        event.set()


def clear_job(job_id: str) -> None:
    _events.pop(job_id, None)
