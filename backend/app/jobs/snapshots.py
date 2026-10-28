"""Restore only attempt-owned source and project changes when cancellation wins."""

from dataclasses import dataclass
from pathlib import Path
import shutil

from ..database import workspace_db
from ..frontend_builder import staging_directory, version_directory


@dataclass
class AttemptSnapshot:
    user_id: int
    project_id: str
    job_id: str
    attempt_id: int
    action: str
    target_version: int
    project: dict
    version_row: dict | None
    artifacts: list[dict]
    previous_report: str | None
    backup_dir: Path | None


def _remove_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def capture_attempt_snapshot(
    user_id: int, project_id: str, job_id: str, attempt_id: int, action: str, input_data: dict,
) -> AttemptSnapshot:
    target_version = input_data['version'] if action == 'verify-package' else int(input_data.get('version', 0)) + 1
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project:
            raise RuntimeError('Cannot snapshot a missing project')
        version_row = db.execute('SELECT * FROM versions WHERE project_id=? AND version=?',
                                 (project_id, target_version)).fetchone()
        artifacts = db.execute('SELECT * FROM artifacts WHERE project_id=? AND version=?',
                               (project_id, target_version)).fetchall()
        report = db.execute("SELECT content FROM artifacts WHERE project_id=? AND path='acceptance/report.json' AND version=?",
                            (project_id, target_version)).fetchone()
    target = version_directory(project_id, target_version)
    backup = None
    if target.exists():
        backup = target.with_name(f'{target.name}.cancel-backup-{attempt_id}')
        _remove_tree(backup)
        shutil.copytree(target, backup)
    return AttemptSnapshot(
        user_id=user_id, project_id=project_id, job_id=job_id, attempt_id=attempt_id,
        action=action, target_version=target_version, project=dict(project),
        version_row=dict(version_row) if version_row else None,
        artifacts=[dict(row) for row in artifacts],
        previous_report=report['content'] if report else None,
        backup_dir=backup,
    )


def rollback_attempt_snapshot(snapshot: AttemptSnapshot) -> None:
    """Restore the pre-attempt contract without touching an older published release."""
    with workspace_db(snapshot.user_id) as db:
        db.execute('DELETE FROM artifacts WHERE project_id=? AND version=?',
                   (snapshot.project_id, snapshot.target_version))
        db.execute('DELETE FROM versions WHERE project_id=? AND version=?',
                   (snapshot.project_id, snapshot.target_version))
        if snapshot.version_row:
            version = snapshot.version_row
            db.execute('''INSERT INTO versions(
                project_id,version,label,note,backend_mode,source_format,created_at)
                VALUES(?,?,?,?,?,?,?)''', (
                snapshot.project_id, version['version'], version['label'], version['note'],
                version['backend_mode'], version['source_format'], version['created_at'],
            ))
        for artifact in snapshot.artifacts:
            db.execute('''INSERT INTO artifacts(project_id,stage,path,content,version,created_at)
                VALUES(?,?,?,?,?,?)''', (
                snapshot.project_id, artifact['stage'], artifact['path'], artifact['content'],
                artifact['version'], artifact['created_at'],
            ))
        if snapshot.action == 'verify-package':
            if snapshot.previous_report is None:
                db.execute("DELETE FROM artifacts WHERE project_id=? AND path='acceptance/report.json' AND version=?",
                           (snapshot.project_id, snapshot.target_version))
            else:
                db.execute('''INSERT OR REPLACE INTO artifacts(project_id,stage,path,content,version)
                    VALUES(?,?,?,?,?)''', (
                    snapshot.project_id, 'verification', 'acceptance/report.json',
                    snapshot.previous_report, snapshot.target_version,
                ))
        project = snapshot.project
        db.execute('''UPDATE projects SET description=?,stage=?,stage_index=?,phase_index=?,status=?,
            auto_mode=?,backend_mode=?,backend_reason=?,source_format=?,published_version=?,current_version=?
            WHERE id=?''', (
            project['description'], project['stage'], project['stage_index'], project['phase_index'],
            project['status'], project['auto_mode'], project['backend_mode'], project['backend_reason'],
            project['source_format'], project['published_version'], project['current_version'], snapshot.project_id,
        ))
    target = version_directory(snapshot.project_id, snapshot.target_version)
    if snapshot.backup_dir:
        _remove_tree(target)
        snapshot.backup_dir.rename(target)
    elif snapshot.version_row is None:
        _remove_tree(target)
    _remove_tree(staging_directory(snapshot.project_id, snapshot.target_version))
    _remove_tree(target.with_name(f'{target.name}.rejected'))


def discard_attempt_snapshot(snapshot: AttemptSnapshot) -> None:
    if snapshot.backup_dir:
        _remove_tree(snapshot.backup_dir)
