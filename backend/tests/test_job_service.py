import uuid

import pytest

from app.database import workspace_db, workspace_for
from app.jobs.idempotency import canonical_input_hash, job_idempotency_key
from app.jobs.leases import (
    finalize_job, heartbeat, lease_next_job,
    recover_expired_leases, request_cancellation,
)
from app.jobs.models import IdempotencyConflictError, StaleJobError
from app.jobs.service import create_job, get_job, record_event


def project_and_job(user_id, action='build'):
    project_id = uuid.uuid4().hex
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        db.execute('INSERT INTO projects(id,name,brief) VALUES(?,?,?)',
                   (project_id, 'Job Test', 'A durable workflow test'))
        input_hash = canonical_input_hash({'project_id': project_id, 'version': 1})
        job_id, created = create_job(db, project_id, 'build', input_hash, action, 'trace-test')
    return project_id, job_id, input_hash, created


def test_job_creation_is_idempotent_and_events_dedupe():
    project_id, job_id, input_hash, created = project_and_job(900101)
    assert created is True
    with workspace_db(900101) as db:
        duplicate, created_again = create_job(db, project_id, 'build', input_hash, 'build', 'trace-test')
        assert duplicate == job_id and created_again is False
        assert db.execute('SELECT COUNT(*) FROM generation_jobs WHERE id=?', (job_id,)).fetchone()[0] == 1
        assert record_event(db, job_id, 'started', {'trace': 'trace-test'}, 'start-1') is True
        assert record_event(db, job_id, 'started', {'trace': 'trace-test'}, 'start-1') is False
        assert db.execute('SELECT COUNT(*) FROM job_events WHERE job_id=?', (job_id,)).fetchone()[0] == 1


def test_conflicting_idempotency_key_is_rejected():
    project_id, job_id, input_hash, _created = project_and_job(900102)
    with workspace_db(900102) as db:
        with pytest.raises(IdempotencyConflictError):
            create_job(db, project_id, 'design', input_hash, 'build', 'trace-test')
        assert get_job(db, job_id)['status'] == 'queued'


def test_lease_heartbeat_and_successful_finalization():
    _project_id, job_id, input_hash, _created = project_and_job(900103)
    with workspace_db(900103) as db:
        attempt = lease_next_job(db, 'worker-a')
        assert attempt['attempt_number'] == 1 and attempt['worker_id'] == 'worker-a'
        assert heartbeat(db, attempt['attempt_id']) is True
        finalize_job(db, attempt, input_hash)
        assert get_job(db, job_id)['status'] == 'succeeded'
        assert db.execute('SELECT ended_at FROM job_attempts WHERE id=?', (attempt['attempt_id'],)).fetchone()['ended_at']
        assert lease_next_job(db, 'worker-b') is None


def test_expired_lease_recovers_with_a_new_attempt():
    _project_id, job_id, input_hash, _created = project_and_job(900104)
    with workspace_db(900104) as db:
        first = lease_next_job(db, 'worker-a')
        db.execute("UPDATE job_attempts SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (first['attempt_id'],))
        assert heartbeat(db, first['attempt_id']) is False
        assert recover_expired_leases(db) == 1
        assert recover_expired_leases(db) == 0
        second = lease_next_job(db, 'worker-b')
        assert second['attempt_number'] == 2
        finalize_job(db, second, input_hash)
        assert get_job(db, job_id)['status'] == 'succeeded'


def test_stale_finalization_is_rejected_before_completion():
    _project_id, job_id, input_hash, _created = project_and_job(900105)
    with workspace_db(900105) as db:
        attempt = lease_next_job(db, 'worker-a')
        with pytest.raises(StaleJobError):
            finalize_job(db, attempt, canonical_input_hash({'changed': True}))
        assert get_job(db, job_id)['status'] == 'leased'
        finalize_job(db, attempt, input_hash)
        assert get_job(db, job_id)['status'] == 'succeeded'


def test_cancellation_prevents_a_new_lease():
    _project_id, job_id, _input_hash, _created = project_and_job(900106)
    with workspace_db(900106) as db:
        assert request_cancellation(db, job_id) is True
        assert lease_next_job(db, 'worker-a') is None
        assert get_job(db, job_id)['status'] == 'cancel_requested'
        assert lease_next_job(db, 'worker-b') is None


def test_idempotency_key_is_stable_for_identical_input():
    first = job_idempotency_key('project-a', 'build', 'hash-a')
    second = job_idempotency_key('project-a', 'build', 'hash-a')
    different = job_idempotency_key('project-a', 'build', 'hash-b')
    assert first == second and first != different
