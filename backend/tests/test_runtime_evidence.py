import asyncio
import errno
import uuid

from fastapi import HTTPException
import pytest

from app.api import get_verification_diagnostic, restart_runtime
from app.database import workspace_db, workspace_for
from app.frontend_builder import version_directory
from app.jobs.file_cleanup import remove_tree
from app.jobs.runner import run_generation_job
from app.verification.report import check_result
from app.verification.review import _prompt
from app.verification.runner import _load_context, verify_package
from test_finalization_cancellation import make_project
from test_verification_runner import dummy_check, enabled, verification_project


def test_failed_check_preserves_full_redacted_diagnostic_and_final_error():
    user_id = 970100
    project_id = verification_project(user_id, [dummy_check('failed')])
    source = '''import unittest

class SecurityTests(unittest.TestCase):
    def test_failed(self):
        print('BEGIN-MARKER' + 'x' * 10000)
        print('api_key=super-secret')
        raise AssertionError('FINAL-CONNECTION-ERROR')

if __name__ == '__main__':
    unittest.main()
'''
    with workspace_db(user_id) as db:
        db.execute('UPDATE artifacts SET content=? WHERE project_id=? AND path=? AND version=1',
                   (source, project_id, 'acceptance/security_tests.py'))
    (version_directory(project_id, 1) / 'acceptance' / 'security_tests.py').write_text(source)

    report = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    result = next(check for check in report['checks'] if check['id'] == 'security.dummy')
    assert result['status'] == 'failed' and 'FINAL-CONNECTION-ERROR' in result['error']
    assert result['diagnostic_ref'].startswith('acceptance/diagnostics/')
    with workspace_db(user_id) as db:
        artifact = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=1',
                              (project_id, result['diagnostic_ref'])).fetchone()
    assert artifact and 'BEGIN-MARKER' in artifact['content']
    assert 'FINAL-CONNECTION-ERROR' in artifact['content']
    assert len(artifact['content']) > 10_000
    assert 'super-secret' not in artifact['content']
    assert report['cleanup'] == {'status': 'passed', 'errors': []}

    response = get_verification_diagnostic(
        project_id, result['diagnostic_ref'], version=1, user={'id': user_id},
    )
    assert response.body.decode() == artifact['content']
    workspace_for(user_id + 1)
    with pytest.raises(HTTPException):
        get_verification_diagnostic(project_id, result['diagnostic_ref'], version=1, user={'id': user_id + 1})
    with pytest.raises(HTTPException):
        get_verification_diagnostic(project_id, '../secrets', version=1, user={'id': user_id})


def test_verification_restart_url_targets_selected_version(monkeypatch):
    class Runtime:
        port = 4567

    async def status(_project, version):
        return {'status': 'running', 'version': version}

    async def ensure(_project, version, *_args):
        assert version == 7
        return Runtime()

    monkeypatch.setattr('app.verification.runner.runtime_manager.status', status)
    monkeypatch.setattr('app.verification.runner.runtime_manager.ensure', ensure)
    from app.verification.runner import _add_runtime_environment
    env = {}
    started = asyncio.run(_add_runtime_environment(
        1, 'project', 7,
        {'files': {}, 'source_format': 'multi-file', 'spec_hash': 'spec'}, env,
    ))
    assert started is False
    assert env['APP_BASE_URL'] == 'http://127.0.0.1:4567'
    assert env['APP_RESTART_URL'].endswith('/runtime/restart?version=7')


def test_restart_api_uses_explicit_version_and_defaults_to_current(monkeypatch):
    calls = []
    monkeypatch.setattr('app.api.owned_project', lambda *_args: {
        'backend_mode': 'fastapi', 'current_version': 2,
    })
    monkeypatch.setattr('app.api.runtime_artifacts', lambda _user, _project, version: (
        'source', 'requirements', 'multi-file', {'version': version},
    ))

    async def restart(_project, version, _source, _requirements, _format, _files):
        calls.append(version)
        return {'version': version, 'healthy': True}

    monkeypatch.setattr('app.api.runtime_manager.restart', restart)
    monkeypatch.setattr('app.api.add_event', lambda *_args: None)
    explicit = asyncio.run(restart_runtime('project', version=4, user={'id': 1}))
    default = asyncio.run(restart_runtime('project', user={'id': 1}))
    assert explicit == {'version': 4, 'healthy': True}
    assert default == {'version': 2, 'healthy': True}
    assert calls == [4, 2]


def test_cleanup_failure_preserves_checks_and_blocks_publish(monkeypatch):
    user_id = 970101
    check = dummy_check()
    check['kind'] = 'persistence'
    project_id = verification_project(user_id, [check])
    original_loader = _load_context

    def fastapi_context(*args):
        context = original_loader(*args)
        context['backend_mode'] = 'fastapi'
        return context

    async def runtime_environment(_user, _project, _version, _context, env):
        env['APP_RESTART_URL'] = 'http://studio.local/restart?version=1'
        return True

    async def passed(_user, _project, _version, _job, _attempt, _context, current, _env,
                     _blocked=None, _failure=None):
        return check_result(current, 'passed', 'fixture-tool-run', 1)

    async def cleanup_failure(*_args, **_kwargs):
        raise OSError(errno.ENOTEMPTY, 'Directory not empty')

    monkeypatch.setattr('app.verification.runner._load_context', fastapi_context)
    monkeypatch.setattr('app.verification.runner._add_runtime_environment', runtime_environment)
    monkeypatch.setattr('app.verification.runner._execute_check', passed)
    monkeypatch.setattr('app.verification.runner.runtime_manager.stop_project', cleanup_failure)
    report = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))

    assert report['status'] == 'passed'
    assert all(result['status'] == 'passed' for result in report['checks'])
    assert report['can_publish'] is False
    assert report['cleanup']['status'] == 'failed'
    assert 'Directory not empty' in report['cleanup']['errors'][0]
    with workspace_db(user_id) as db:
        persisted = db.execute("SELECT content FROM artifacts WHERE project_id=? AND path='acceptance/report.json'",
                               (project_id,)).fetchone()
        event = db.execute("SELECT 1 FROM job_events WHERE event_type='verification_cleanup_failed'").fetchone()
    assert persisted and event


def test_remove_tree_retries_transient_directory_race(monkeypatch):
    root = version_directory(uuid.uuid4().hex, 1)
    (root / 'tmp').mkdir(parents=True)
    (root / 'tmp' / 'cache').write_text('owned cache')
    import app.jobs.file_cleanup as cleanup
    original = cleanup.shutil.rmtree
    calls = []

    def flaky(path):
        calls.append(path)
        if len(calls) == 1:
            raise OSError(errno.ENOTEMPTY, 'Directory not empty')
        original(path)

    monkeypatch.setattr(cleanup.shutil, 'rmtree', flaky)
    monkeypatch.setattr(cleanup.time, 'sleep', lambda _seconds: None)
    remove_tree(root)
    assert len(calls) == 2 and not root.exists()
    remove_tree(root)


def test_snapshot_discard_failure_does_not_replace_job_success(monkeypatch):
    user_id = 940099
    project_id = make_project(user_id)

    async def operation():
        return None

    def failure(_snapshot):
        raise OSError(errno.ENOTEMPTY, 'Directory not empty')

    monkeypatch.setattr('app.jobs.runner.discard_attempt_snapshot', failure)
    result = asyncio.run(run_generation_job(
        user_id, project_id, 'build', 'advance-stage',
        {'project_id': project_id, 'stage': 'build', 'version': 1}, operation,
    ))
    assert result is True
    with workspace_db(user_id) as db:
        job = db.execute('SELECT id,status FROM generation_jobs WHERE project_id=?', (project_id,)).fetchone()
        cleanup = db.execute("SELECT 1 FROM job_events WHERE job_id=? AND event_type='attempt.cleanup_failed'",
                             (job['id'],)).fetchone()
    assert job['status'] == 'succeeded' and cleanup


def test_advisory_review_receives_final_error_and_cleanup_context():
    prompt = _prompt({
        'project_id': 'project', 'version': 1, 'spec_hash': 'spec', 'source_hash': 'source',
        'status': 'failed', 'can_publish': False,
        'cleanup': {'status': 'failed', 'errors': ['cleanup detail']},
        'checks': [{
            'id': 'persistence.restart', 'status': 'failed', 'required': True,
            'error': 'beginning context FINAL-CONNECTION-ERROR',
            'diagnostic_ref': 'acceptance/diagnostics/1-restart.log',
        }],
    })
    assert 'FINAL-CONNECTION-ERROR' in prompt
    assert 'acceptance/diagnostics/1-restart.log' in prompt
    assert 'cleanup detail' in prompt
