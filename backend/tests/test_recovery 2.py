import uuid

from app.database import workspace_db, workspace_for
from app.jobs.leases import finalize_job, heartbeat, lease_next_job
from app.jobs.recovery import RESTART_MESSAGE, recover_interrupted_work
from app.jobs.runner import _prepare_attempt
from app.jobs.service import create_job, get_job
from app.jobs.tool_runs import start_tool_run


def working_project(user_id):
    project_id = uuid.uuid4().hex
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        db.execute("INSERT INTO projects(id,name,brief,status) VALUES(?,?,?,'working')",
                   (project_id, 'Recovery Test', 'Interrupted generation'))
    return project_id


def leased_job(user_id, input_hash=None):
    project_id = working_project(user_id)
    input_hash = input_hash or uuid.uuid4().hex
    with workspace_db(user_id) as db:
        job_id, _ = create_job(db, project_id, 'build', input_hash, 'advance-stage', 'trace-recovery')
        attempt = lease_next_job(db, 'crashed-worker', job_id=job_id)
        db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (job_id,))
    return project_id, job_id, attempt, input_hash


def project_state(user_id, project_id):
    with workspace_db(user_id) as db:
        status = db.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()['status']
        messages = [row['content'] for row in db.execute(
            "SELECT content FROM messages WHERE project_id=? AND kind='error'", (project_id,))]
    return status, messages


def test_startup_releases_unfinished_attempt_and_allows_retry():
    project_id, job_id, attempt, input_hash = leased_job(900301)
    run = start_tool_run('Frontend production build', 'test', {}, user_id=900301,
                         job_id=job_id, attempt_id=attempt['attempt_id'])
    assert recover_interrupted_work(900301, startup=True) == 1
    with workspace_db(900301) as db:
        assert get_job(db, job_id)['status'] == 'recovery_required'
        assert heartbeat(db, attempt['attempt_id']) is False
        assert db.execute('SELECT status FROM tool_runs WHERE id=?', (run.id,)).fetchone()['status'] == 'failed'
    assert project_state(900301, project_id) == ('error', [RESTART_MESSAGE])
    assert recover_interrupted_work(900301, startup=True) == 0
    prepared = _prepare_attempt(900301, project_id, 'build', 'advance-stage', input_hash,
                                'trace-retry', 'new-worker', 60)
    assert prepared is not None and prepared[1]['attempt_number'] == 2
    with workspace_db(900301) as db:
        finalize_job(db, prepared[1], input_hash)
        assert get_job(db, job_id)['status'] == 'succeeded'


def test_runtime_recovery_releases_only_expired_leases():
    live_project, live_job, _live, _ = leased_job(900302)
    dead_project, dead_job, dead, _ = leased_job(900302)
    with workspace_db(900302) as db:
        db.execute("UPDATE job_attempts SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                   (dead['attempt_id'],))
    assert recover_interrupted_work(900302, startup=False) == 1
    with workspace_db(900302) as db:
        assert get_job(db, live_job)['status'] == 'running'
        assert get_job(db, dead_job)['status'] == 'recovery_required'
    assert project_state(900302, live_project)[0] == 'working'
    assert project_state(900302, dead_project)[0] == 'error'


def test_startup_releases_orphaned_queue_entries_and_legacy_projects():
    queued_project = working_project(900303)
    legacy_project = working_project(900303)
    with workspace_db(900303) as db:
        job_id, _ = create_job(db, queued_project, 'build', uuid.uuid4().hex, 'advance-stage', 'trace-orphan')
    assert recover_interrupted_work(900303, startup=True) == 1
    with workspace_db(900303) as db:
        assert get_job(db, job_id)['status'] == 'recovery_required'
    assert project_state(900303, queued_project) == ('error', [RESTART_MESSAGE])
    assert project_state(900303, legacy_project) == ('error', [RESTART_MESSAGE])


def test_interrupted_cancellation_finishes_as_cancelled():
    _project_id, job_id, _attempt, _ = leased_job(900304)
    with workspace_db(900304) as db:
        db.execute("UPDATE generation_jobs SET status='cancelling' WHERE id=?", (job_id,))
    assert recover_interrupted_work(900304, startup=True) == 1
    with workspace_db(900304) as db:
        assert get_job(db, job_id)['status'] == 'cancelled'
