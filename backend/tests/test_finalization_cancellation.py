import asyncio
import uuid

import pytest

from app.database import workspace_db, workspace_for
from app.frontend_builder import staging_directory, version_directory
from app.jobs.leases import finalize_job, lease_next_job, request_cancellation
from app.jobs.models import StaleJobError
from app.jobs.runner import run_generation_job
from app.jobs.service import create_job

def make_project(user_id):
    project_id = uuid.uuid4().hex
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        db.execute('''INSERT INTO projects(
            id,name,brief,stage,stage_index,phase_index,status,backend_mode,source_format,
            published_version,current_version) VALUES(?,?,?,?,?,?,?,?,?,?,?)''', (
            project_id, 'Rollback App', 'Verify cancellation rollback', 'build', 3, 1,
            'ready', 'static', 'single-file', 1, 1,
        ))
        db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                   (project_id, 1, 'Phase 1', 'static', 'single-file'))
        db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                   (project_id, 'build', 'index.html', '<html>Version one</html>', 1))
    root = version_directory(project_id, 1)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'index.html').write_text('<html>Version one</html>')
    return project_id


def cancelled_events(user_id, job_id):
    with workspace_db(user_id) as db:
        return db.execute("SELECT COUNT(*) FROM job_events WHERE job_id=? AND event_type='cancelled'",
                          (job_id,)).fetchone()[0]


def test_cancelled_generation_rolls_back_new_version_and_staging():
    user_id = 940001
    project_id = make_project(user_id)

    async def scenario():
        started = asyncio.Event()

        async def operation():
            with workspace_db(user_id) as db:
                db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (project_id, 'build', 'index.html', '<html>Version two</html>', 2))
                db.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                           (project_id, 2, 'Phase 2', 'static', 'single-file'))
                db.execute("UPDATE projects SET current_version=2,stage='review',stage_index=4 WHERE id=?", (project_id,))
            target = version_directory(project_id, 2)
            target.mkdir(parents=True, exist_ok=True)
            (target / 'index.html').write_text('<html>Version two</html>')
            staging_directory(project_id, 2).mkdir(parents=True, exist_ok=True)
            started.set()
            await asyncio.sleep(30)

        task = asyncio.create_task(run_generation_job(
            user_id, project_id, 'build', 'advance-stage',
            {'project_id': project_id, 'stage': 'build', 'version': 1}, operation,
        ))
        await asyncio.wait_for(started.wait(), timeout=2)
        with workspace_db(user_id) as db:
            job_id = db.execute('SELECT id FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()[0]
            assert request_cancellation(db, job_id)
        assert await asyncio.wait_for(task, timeout=2) is True
        return job_id

    job_id = asyncio.run(scenario())
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        assert project['current_version'] == 1 and project['published_version'] == 1
        assert project['stage'] == 'build' and project['status'] == 'error'
        assert db.execute('SELECT COUNT(*) FROM versions WHERE project_id=? AND version=2', (project_id,)).fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM artifacts WHERE project_id=? AND version=2', (project_id,)).fetchone()[0] == 0
        original = db.execute('SELECT content FROM artifacts WHERE project_id=? AND version=1 AND path=?',
                              (project_id, 'index.html')).fetchone()
        assert original['content'] == '<html>Version one</html>'
    assert not version_directory(project_id, 2).exists()
    assert not staging_directory(project_id, 2).exists()
    assert (version_directory(project_id, 1) / 'index.html').read_text() == '<html>Version one</html>'
    assert cancelled_events(user_id, job_id) == 1


def test_finalization_rejects_wrong_worker_and_cancelled_state():
    user_id = 940003
    project_id = make_project(user_id)
    with workspace_db(user_id) as db:
        job_id, _ = create_job(db, project_id, 'build', 'input-hash', 'advance-stage', uuid.uuid4().hex)
        attempt = lease_next_job(db, 'worker-a', job_id=job_id)
        db.execute("UPDATE generation_jobs SET status='running' WHERE id=?", (job_id,))
        with pytest.raises(StaleJobError, match='no longer owns'):
            finalize_job(db, {**attempt, 'worker_id': 'worker-b'}, attempt['input_hash'])
        assert request_cancellation(db, job_id)
        with pytest.raises(StaleJobError, match='cancelled before finalization'):
            finalize_job(db, attempt, attempt['input_hash'])
        job = db.execute('SELECT status FROM generation_jobs WHERE id=?', (job_id,)).fetchone()
        assert job['status'] == 'cancel_requested'
