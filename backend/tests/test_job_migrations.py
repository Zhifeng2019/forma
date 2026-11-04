import uuid

from app.database import control_db, init_databases, workspace_db, workspace_for


def test_existing_version_gains_nullable_context_without_rewriting_history():
    user_id = 975101
    with workspace_db(user_id, create=True) as db:
        db.executescript('''CREATE TABLE versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, version INTEGER NOT NULL,
            label TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', backend_mode TEXT NOT NULL DEFAULT 'static',
            source_format TEXT NOT NULL DEFAULT 'single-file', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, version));''')
        db.execute("INSERT INTO versions(project_id,version,label,note) VALUES('legacy',1,'Published','Keep this release')")
        original = dict(db.execute('SELECT * FROM versions').fetchone())
    workspace_for(user_id)
    workspace_for(user_id)
    with workspace_db(user_id) as db:
        upgraded = dict(db.execute('SELECT * FROM versions').fetchone())
        assert upgraded.pop('generation_context') is None
        assert upgraded == original


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
        provider_columns = {row['name'] for row in control.execute('PRAGMA table_info(providers)')}
        assert {'input_price_per_million', 'output_price_per_million', 'currency'} <= provider_columns
    with workspace_db(user_id) as workspace:
        tables = {row['name'] for row in workspace.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'generation_jobs', 'job_attempts', 'job_events', 'tool_runs', 'usage_ledger'} <= tables
        usage_columns = {row['name'] for row in workspace.execute('PRAGMA table_info(usage_ledger)')}
        assert {'usage_status', 'cost_status', 'total_tokens', 'provider_request_id', 'finish_reason',
                'input_price_per_million', 'output_price_per_million', 'currency'} <= usage_columns
    init_databases()
    with control_db() as control:
        assert control.execute('SELECT COUNT(*) FROM deployment_registry WHERE project_id=?', (project_id,)).fetchone()[0] == 1
