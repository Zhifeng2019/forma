"""Persistent, content-safe checkpoints for durable generation jobs."""

import sqlite3

from .service import record_event


def checkpoint(
    db: sqlite3.Connection,
    job_id: str,
    attempt_id: int,
    name: str,
    payload: dict,
) -> None:
    record_event(db, job_id, 'checkpoint', {'name': name, **payload}, f'{attempt_id}:{name}')
