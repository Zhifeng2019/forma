"""Control-plane deployment lookup and write-through synchronization."""

import json

from .database import control_db, workspace_db
from .llm import GenerationError
from .policy import hosting_deadline, studio_policy


def get_deployment(project_id: str) -> dict | None:
    with control_db() as db:
        row = db.execute('''SELECT project_id,user_id,published_version,backend_mode,source_format,runtime_metadata,hosting_expires_at
            FROM deployment_registry WHERE project_id=?''', (project_id,)).fetchone()
    if not row:
        return None
    return {
        'project_id': row['project_id'],
        'user_id': row['user_id'],
        'version': row['published_version'],
        'backend_mode': row['backend_mode'],
        'source_format': row['source_format'],
        'runtime_metadata': json.loads(row['runtime_metadata'] or '{}'),
        'hosting_expires_at': row['hosting_expires_at'],
    }


def upsert_deployment(user_id: int, project_id: str) -> None:
    """Write the current published state, or remove it when no version is published."""
    with control_db() as control:
        hours = studio_policy(control)['hosting_duration_hours']
    with workspace_db(user_id) as workspace:
        # Give pre-policy releases one initial hosting window. Never renew on restart.
        workspace.execute('''UPDATE projects SET hosting_expires_at=? WHERE id=?
            AND published_version IS NOT NULL AND hosting_expires_at IS NULL''',
            (hosting_deadline(hours), project_id))
        project = workspace.execute('''SELECT p.published_version,p.hosting_expires_at,p.backend_mode current_mode,
            p.source_format current_format,v.backend_mode version_mode,v.source_format version_format
            FROM projects p LEFT JOIN versions v ON v.project_id=p.id AND v.version=p.published_version
            WHERE p.id=?''', (project_id,)).fetchone()
    published_version = project['published_version'] if project else None
    with control_db() as control:
        if not published_version:
            control.execute('DELETE FROM deployment_registry WHERE project_id=?', (project_id,))
            return
        backend_mode = project['version_mode'] or project['current_mode']
        source_format = project['version_format'] or project['current_format']
        control.execute('''INSERT INTO deployment_registry(
            project_id,user_id,published_version,backend_mode,source_format,runtime_metadata,hosting_expires_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
                user_id=excluded.user_id,
                published_version=excluded.published_version,
                backend_mode=excluded.backend_mode,
                source_format=excluded.source_format,
                runtime_metadata=excluded.runtime_metadata,
                hosting_expires_at=excluded.hosting_expires_at,
                updated_at=CURRENT_TIMESTAMP''',
            (project_id, user_id, published_version, backend_mode, source_format, '{}', project['hosting_expires_at']))


def delete_deployment(project_id: str) -> None:
    with control_db() as control:
        control.execute('DELETE FROM deployment_registry WHERE project_id=?', (project_id,))


def deployment_artifacts(deployment: dict) -> dict:
    """Read only the registered owner's artifacts; never scan other workspaces."""
    project_id = deployment['project_id']
    with workspace_db(deployment['user_id']) as db:
        if deployment['source_format'] == 'multi-file':
            files = {row['path']: row['content'] for row in db.execute(
                'SELECT path,content FROM artifacts WHERE project_id=? AND version=?',
                (project_id, deployment['version']),
            )}
            if not files:
                raise GenerationError('The published application source is unavailable.')
            return {'files': files, 'html': None}
        artifact = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                              (project_id, 'index.html', deployment['version'])).fetchone()
        if not artifact:
            raise GenerationError('The published application document is unavailable.')
        return {'files': {}, 'html': artifact['content']}
