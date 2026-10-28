import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .config import settings

CONTROL_SCHEMA = '''
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
 name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
 status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS providers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, base_url TEXT NOT NULL,
 model TEXT NOT NULL, api_key_encrypted TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
 input_price_per_million REAL, output_price_per_million REAL, currency TEXT NOT NULL DEFAULT 'USD',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS preferences (
 user_id INTEGER PRIMARY KEY, provider_id INTEGER, auto_mode INTEGER NOT NULL DEFAULT 0,
 theme TEXT NOT NULL DEFAULT 'light', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS deployment_registry (
 project_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, published_version INTEGER NOT NULL,
 backend_mode TEXT NOT NULL, source_format TEXT NOT NULL, runtime_metadata TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_deployment_registry_user ON deployment_registry(user_id);
'''

WORKSPACE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, brief TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 stage TEXT NOT NULL DEFAULT 'discovery', stage_index INTEGER NOT NULL DEFAULT 0,
 phase_index INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ready',
 auto_mode INTEGER NOT NULL DEFAULT 0, backend_mode TEXT NOT NULL DEFAULT 'auto',
 backend_reason TEXT NOT NULL DEFAULT '', source_format TEXT NOT NULL DEFAULT 'single-file',
 published_version INTEGER,
 current_version INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, role TEXT NOT NULL,
 content TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'chat', metadata TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS artifacts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, stage TEXT NOT NULL,
 path TEXT NOT NULL, content TEXT NOT NULL, version INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, path, version)
);
CREATE TABLE IF NOT EXISTS versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, version INTEGER NOT NULL,
 label TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', backend_mode TEXT NOT NULL DEFAULT 'static',
 source_format TEXT NOT NULL DEFAULT 'single-file',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, version)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, message TEXT NOT NULL,
 level TEXT NOT NULL DEFAULT 'info', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS generation_jobs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, stage TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
  'queued','leased','running','waiting_on_tool','finalizing','retry_scheduled',
  'waiting_for_approval','cancel_requested','cancelling','cancelled','succeeded',
  'failed','dead_letter','recovery_required')),
 input_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL,
 current_attempt INTEGER NOT NULL DEFAULT 0, trace_id TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(project_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_project ON generation_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_status ON generation_jobs(status,created_at);
CREATE INDEX IF NOT EXISTS idx_generation_jobs_trace ON generation_jobs(trace_id);
CREATE TABLE IF NOT EXISTS job_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, attempt_number INTEGER NOT NULL,
 worker_id TEXT NOT NULL, lease_expires_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, ended_at TEXT, failure_code TEXT,
 UNIQUE(job_id,attempt_number),
 FOREIGN KEY(job_id) REFERENCES generation_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_job_attempts_lease ON job_attempts(ended_at,lease_expires_at);
CREATE TABLE IF NOT EXISTS job_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, event_type TEXT NOT NULL,
 payload TEXT NOT NULL DEFAULT '{}', dedupe_key TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(job_id,dedupe_key),
 FOREIGN KEY(job_id) REFERENCES generation_jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id,id);
CREATE TABLE IF NOT EXISTS tool_runs (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, attempt_id INTEGER,
 tool_name TEXT NOT NULL, tool_version TEXT NOT NULL, input_hash TEXT NOT NULL,
 output_ref TEXT, status TEXT NOT NULL, retry_count INTEGER NOT NULL DEFAULT 0,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, ended_at TEXT, provenance TEXT NOT NULL DEFAULT '{}',
 FOREIGN KEY(job_id) REFERENCES generation_jobs(id) ON DELETE CASCADE,
 FOREIGN KEY(attempt_id) REFERENCES job_attempts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_runs_job ON tool_runs(job_id,tool_name);
CREATE TABLE IF NOT EXISTS usage_ledger (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, tool_run_id TEXT,
 provider TEXT, model TEXT, input_tokens INTEGER NOT NULL DEFAULT 0,
 output_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost REAL NOT NULL DEFAULT 0,
 latency_ms INTEGER NOT NULL DEFAULT 0, metadata TEXT NOT NULL DEFAULT '{}',
 usage_status TEXT NOT NULL DEFAULT 'unavailable', cost_status TEXT NOT NULL DEFAULT 'unknown',
 total_tokens INTEGER, provider_request_id TEXT, finish_reason TEXT,
 input_price_per_million REAL, output_price_per_million REAL, currency TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(tool_run_id),
 FOREIGN KEY(job_id) REFERENCES generation_jobs(id) ON DELETE CASCADE,
 FOREIGN KEY(tool_run_id) REFERENCES tool_runs(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_job ON usage_ledger(job_id);
'''


def connect(path: Path):
    db = sqlite3.connect(path, timeout=20, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    return db


@contextmanager
def control_db():
    db = connect(settings.data_path / 'control.db')
    try:
        yield db
        db.commit()
    finally:
        db.close()


@contextmanager
def workspace_db(user_id: int):
    db = connect(settings.data_path / 'users' / f'user_{user_id}.db')
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_databases():
    with control_db() as db:
        db.executescript(CONTROL_SCHEMA)
        provider_columns = {row['name'] for row in db.execute('PRAGMA table_info(providers)')}
        for name, definition in {
            'input_price_per_million': 'REAL',
            'output_price_per_million': 'REAL',
            'currency': "TEXT NOT NULL DEFAULT 'USD'",
        }.items():
            if name not in provider_columns:
                db.execute(f'ALTER TABLE providers ADD COLUMN {name} {definition}')
    from .security import hash_password
    with control_db() as db:
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            db.execute('INSERT INTO users(email,name,password_hash,role) VALUES(?,?,?,?)',
                       ('admin@forma.local', 'Studio Admin', hash_password('admin123'), 'admin'))
            db.execute('INSERT INTO preferences(user_id) VALUES(1)')
        user_ids = [row['id'] for row in db.execute('SELECT id FROM users')]
    for user_id in user_ids:
        workspace_for(user_id)
        backfill_deployment_registry(user_id)


def backfill_deployment_registry(user_id: int) -> None:
    from .deployment_registry import upsert_deployment
    with workspace_db(user_id) as workspace:
        project_ids = [row['id'] for row in workspace.execute(
            'SELECT id FROM projects WHERE published_version IS NOT NULL',
        )]
    for project_id in project_ids:
        upsert_deployment(user_id, project_id)


def workspace_for(user_id: int):
    with workspace_db(user_id) as db:
        db.executescript(WORKSPACE_SCHEMA)
        columns = {row['name'] for row in db.execute('PRAGMA table_info(projects)')}
        if 'backend_mode' not in columns:
            # Existing applications remain frontend-only after an in-place upgrade.
            db.execute("ALTER TABLE projects ADD COLUMN backend_mode TEXT NOT NULL DEFAULT 'static'")
        if 'backend_reason' not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN backend_reason TEXT NOT NULL DEFAULT ''")
        if 'source_format' not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN source_format TEXT NOT NULL DEFAULT 'single-file'")
        version_columns = {row['name'] for row in db.execute('PRAGMA table_info(versions)')}
        if 'backend_mode' not in version_columns:
            db.execute("ALTER TABLE versions ADD COLUMN backend_mode TEXT NOT NULL DEFAULT 'static'")
            db.execute('''UPDATE versions SET backend_mode=(
                          SELECT projects.backend_mode FROM projects WHERE projects.id=versions.project_id)''')
        if 'source_format' not in version_columns:
            db.execute("ALTER TABLE versions ADD COLUMN source_format TEXT NOT NULL DEFAULT 'single-file'")
            db.execute('''UPDATE versions SET source_format=(
                          SELECT projects.source_format FROM projects WHERE projects.id=versions.project_id)''')
        usage_columns = {row['name'] for row in db.execute('PRAGMA table_info(usage_ledger)')}
        for name, definition in {
            'usage_status': "TEXT NOT NULL DEFAULT 'unavailable'",
            'cost_status': "TEXT NOT NULL DEFAULT 'unknown'",
            'total_tokens': 'INTEGER',
            'provider_request_id': 'TEXT',
            'finish_reason': 'TEXT',
            'input_price_per_million': 'REAL',
            'output_price_per_million': 'REAL',
            'currency': 'TEXT',
        }.items():
            if name not in usage_columns:
                db.execute(f'ALTER TABLE usage_ledger ADD COLUMN {name} {definition}')


def rows(items):
    return [dict(row) for row in items]
