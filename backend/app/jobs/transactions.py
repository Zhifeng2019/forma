"""Transaction helpers that compose with the studio's workspace connections."""

from contextlib import contextmanager
import sqlite3
import uuid


@contextmanager
def job_transaction(db: sqlite3.Connection):
    """Use a savepoint for nested work or BEGIN IMMEDIATE for a new write transaction."""
    name = f'job_{uuid.uuid4().hex}'
    nested = db.in_transaction
    if nested:
        db.execute(f'SAVEPOINT {name}')
    else:
        db.execute('BEGIN IMMEDIATE')
    try:
        yield name
    except Exception:
        if nested:
            db.execute(f'ROLLBACK TO SAVEPOINT {name}')
            db.execute(f'RELEASE SAVEPOINT {name}')
        else:
            db.rollback()
        raise
    else:
        if nested:
            db.execute(f'RELEASE SAVEPOINT {name}')
        else:
            db.commit()
