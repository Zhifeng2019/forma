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
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS preferences (
 user_id INTEGER PRIMARY KEY, provider_id INTEGER, auto_mode INTEGER NOT NULL DEFAULT 0,
 theme TEXT NOT NULL DEFAULT 'light', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
'''

WORKSPACE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, brief TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 stage TEXT NOT NULL DEFAULT 'discovery', stage_index INTEGER NOT NULL DEFAULT 0,
 phase_index INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'ready',
 auto_mode INTEGER NOT NULL DEFAULT 0, backend_mode TEXT NOT NULL DEFAULT 'auto',
 backend_reason TEXT NOT NULL DEFAULT '', published_version INTEGER,
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
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, version)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, message TEXT NOT NULL,
 level TEXT NOT NULL DEFAULT 'info', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
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
    from .security import hash_password
    with control_db() as db:
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            db.execute('INSERT INTO users(email,name,password_hash,role) VALUES(?,?,?,?)',
                       ('admin@forma.local', 'Studio Admin', hash_password('admin123'), 'admin'))
            db.execute('INSERT INTO preferences(user_id) VALUES(1)')
        user_ids = [row['id'] for row in db.execute('SELECT id FROM users')]
    for user_id in user_ids:
        workspace_for(user_id)


def workspace_for(user_id: int):
    with workspace_db(user_id) as db:
        db.executescript(WORKSPACE_SCHEMA)
        columns = {row['name'] for row in db.execute('PRAGMA table_info(projects)')}
        if 'backend_mode' not in columns:
            # Existing applications remain frontend-only after an in-place upgrade.
            db.execute("ALTER TABLE projects ADD COLUMN backend_mode TEXT NOT NULL DEFAULT 'static'")
        if 'backend_reason' not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN backend_reason TEXT NOT NULL DEFAULT ''")
        version_columns = {row['name'] for row in db.execute('PRAGMA table_info(versions)')}
        if 'backend_mode' not in version_columns:
            db.execute("ALTER TABLE versions ADD COLUMN backend_mode TEXT NOT NULL DEFAULT 'static'")
            db.execute('''UPDATE versions SET backend_mode=(
                          SELECT projects.backend_mode FROM projects WHERE projects.id=versions.project_id)''')


def rows(items):
    return [dict(row) for row in items]
