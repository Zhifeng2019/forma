import uuid

from app.database import control_db, init_databases, workspace_db, workspace_for


def test_additive_job_schema_and_published_registry_backfill():
    init_databases()
    user_id = 900001
    project_id = uuid.uuid4().hex
    with control_db() as control:
        control.execute('INSERT INTO users(id,email,name,password_hash) VALUES(?,?,?,?)',
                        (user_id, f'{user_id}@example.com', 'Migration Test', 'not-a-real-hash'))
    workspace_for(user_id)
    with workspace_db(user_id) as workspace:
        workspace.execute('INSERT INTO projects(id,name,brief,backend_mode,source_format,published_version) VALUES(?,?,?,?,?,?)',
                          (project_id, 'Registry Test', 'A published migration fixture', 'fastapi', 'multi-file', 2))
        workspace.execute('INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)',
                          (project_id, 2, 'Phase 2', 'fastapi', 'multi-file'))
    init_databases()
    with control_db() as control:
        registry = control.execute('SELECT * FROM deployment_registry WHERE project_id=?', (project_id,)).fetchone()
        assert registry['user_id'] == user_id
        assert registry['published_version'] == 2
        assert registry['backend_mode'] == 'fastapi'
        assert registry['source_format'] == 'multi-file'
        tables = {row['name'] for row in control.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'deployment_registry' in tables
    with workspace_db(user_id) as workspace:
        tables = {row['name'] for row in workspace.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'generation_jobs', 'job_attempts', 'job_events', 'tool_runs', 'usage_ledger'} <= tables
    init_databases()
    with control_db() as control:
        assert control.execute('SELECT COUNT(*) FROM deployment_registry WHERE project_id=?', (project_id,)).fetchone()[0] == 1
