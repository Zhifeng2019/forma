"""Durable deterministic verification runner and tool-run persistence."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import quote

from ..config import ROOT, Settings, settings
from ..database import workspace_db
from ..features import FeatureFlag, require_feature
from ..frontend_builder import (
    _node_binaries, deployment_archive, ensure_frontend_build, safe_path, version_directory, write_source_files,
)
from ..jobs.idempotency import canonical_input_hash, job_idempotency_key
from ..jobs.models import JobCancelledError
from ..jobs.processes import run_process
from ..jobs.runner import run_generation_job
from ..jobs.service import record_event
from ..jobs.tool_runs import finish_tool_run, start_tool_run
from ..llm import GenerationError
from ..runtime import runtime_manager
from ..security import create_token
from ..spec.review import appspec_review
from ..spec.schema import APPSPEC_PATH, COMPILER_VERSION
from .report import build_report, check_result, report_json


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_context(user_id: int, project_id: str, version: int) -> dict:
    with workspace_db(user_id) as db:
        project = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project or version < 1:
            raise GenerationError('The application version to verify was not found.')
        spec_row = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                              (project_id, APPSPEC_PATH, version)).fetchone()
        review = appspec_review(spec_row['content'] if spec_row else None)
        if review['appspec_valid'] is not True:
            raise GenerationError(review['appspec_error'] or 'This version has no valid AppSpec to verify.')
        manifest_row = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=?',
                                  (project_id, 'acceptance/manifest.json', version)).fetchone()
        if not manifest_row:
            raise GenerationError('This version has no acceptance manifest. Build it before verification.')
        manifest = json.loads(manifest_row['content'])
        files = {row['path']: row['content'] for row in db.execute(
            "SELECT path,content FROM artifacts WHERE project_id=? AND version=? AND path NOT IN (?,?) AND path NOT LIKE 'acceptance/%'",
            (project_id, version, APPSPEC_PATH, 'build-manifest.json'),
        )}
        version_row = db.execute('SELECT backend_mode,source_format FROM versions WHERE project_id=? AND version=?',
                                 (project_id, version)).fetchone()
    spec = review['appspec']['spec']
    source_hash = canonical_input_hash(files)
    if manifest.get('spec_hash') != review['appspec']['spec_hash'] or manifest.get('source_hash') != source_hash:
        raise GenerationError('The acceptance manifest does not match the current AppSpec or source hash.')
    backend_mode = version_row['backend_mode'] if version_row else project['backend_mode']
    source_format = version_row['source_format'] if version_row else project['source_format']
    checks = manifest.get('checks')
    if not isinstance(checks, list) or not checks:
        raise GenerationError('The acceptance manifest contains no checks.')
    for check in checks:
        if not isinstance(check.get('required'), bool) or not isinstance(check.get('mutates'), bool):
            raise GenerationError('Acceptance check flags are invalid.')
        if not all(isinstance(check.get(key), str) and check[key] for key in ('id', 'kind', 'target', 'test', 'file')):
            raise GenerationError('Acceptance check coordinates are invalid.')
        if not isinstance(check.get('environment'), list) or any(not isinstance(item, str) for item in check['environment']):
            raise GenerationError('Acceptance check environment is invalid.')
        if not isinstance(check.get('timeout'), int) or check['timeout'] <= 0:
            raise GenerationError('Acceptance check timeout is invalid.')
    return {
        'project': dict(project), 'spec': spec, 'manifest': manifest, 'files': files,
        'backend_mode': backend_mode, 'source_format': source_format, 'checks': checks,
        'spec_hash': review['appspec']['spec_hash'], 'source_hash': source_hash,
    }


def latest_verification_report(user_id: int, job_id: str) -> dict | None:
    with workspace_db(user_id) as db:
        row = db.execute("SELECT payload FROM job_events WHERE job_id=? AND event_type='verification_report' ORDER BY id DESC LIMIT 1",
                         (job_id,)).fetchone()
    return json.loads(row['payload']) if row else None


def _base_environment(user_id: int, project_id: str, version: int, context: dict) -> dict:
    root = version_directory(project_id, version)
    token = create_token(user_id)
    studio = settings.studio_base_url.rstrip('/')
    env = {
        'APP_SOURCE_DIR': str(root),
        'APP_PREVIEW_URL': f'{studio}/api/projects/{project_id}/preview?access_token={quote(token)}&version={version}',
        'FORMA_BASE_URL': studio,
        'FORMA_TOKEN': token,
        'PROJECT_ID': project_id,
    }
    return env


def _materialize_acceptance_files(user_id: int, project_id: str, version: int) -> None:
    root = version_directory(project_id, version)
    with workspace_db(user_id) as db:
        artifacts = db.execute('''SELECT path,content FROM artifacts WHERE project_id=? AND version=?
            AND path LIKE 'acceptance/%' AND path NOT IN ('acceptance/report.json', 'acceptance/deployment.zip')''',
            (project_id, version)).fetchall()
    for artifact in artifacts:
        target = safe_path(root, artifact['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(artifact['content'])


def _add_archive_environment(user_id: int, project_id: str, version: int, context: dict, env: dict) -> None:
    if env.get('APP_PACKAGE_ZIP') or not any('APP_PACKAGE_ZIP' in check['environment'] for check in context['checks']):
        return
    archive = deployment_archive(user_id, project_id, version, context['files'], context['backend_mode'])
    target = version_directory(project_id, version) / 'acceptance' / 'deployment.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(archive)
    env['APP_PACKAGE_ZIP'] = str(target)


async def _add_runtime_environment(user_id: int, project_id: str, version: int, context: dict, env: dict) -> bool:
    status = await runtime_manager.status(project_id, version)
    runtime = await runtime_manager.ensure(
        project_id, version, 'preview', context['files'].get('backend/main.py', ''),
        context['files'].get('backend/requirements.txt', ''), context['source_format'], context['files'],
        context['spec_hash'],
    )
    env['APP_BASE_URL'] = f'http://127.0.0.1:{runtime.port}'
    env['APP_RESTART_URL'] = f'{settings.studio_base_url.rstrip("/")}/api/projects/{project_id}/runtime/restart'
    return status['status'] != 'running'


def _process_environment(root: Path, env: dict) -> dict:
    temporary = root / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    cache = settings.data_path / 'cache' / 'npm'
    cache.mkdir(parents=True, exist_ok=True)
    return {
        'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
        'HOME': str(temporary), 'TMPDIR': str(temporary),
        'NO_COLOR': '1', 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1',
        'NPM_CONFIG_REGISTRY': settings.runtime_npm_registry,
        'NPM_CONFIG_CACHE': str(cache), 'NPM_CONFIG_UPDATE_NOTIFIER': 'false',
        'NODE_PATH': str(ROOT.parent / 'frontend' / 'node_modules'),
        'PLAYWRIGHT_BROWSERS_PATH': os.environ.get(
            'PLAYWRIGHT_BROWSERS_PATH', str(Path.home() / '.cache' / 'ms-playwright'),
        ),
        'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
        **({'PLAYWRIGHT_CHANNEL': 'chrome'} if Path('/Applications/Google Chrome.app').exists()
           or Path('/usr/bin/google-chrome').exists() else {}),
        **env,
    }


async def _execute_process(
    command: list[str], cwd: Path, env: dict, timeout: int, tool_run_id: str,
) -> tuple[int, str]:
    result = await run_process(command, cwd, env, timeout, 'execute an acceptance check', tool_run_id=tool_run_id)
    return result.returncode, result.output[-4000:]


def _command_for_check(root: Path, check: dict) -> tuple[list[str], Path]:
    script = safe_path(root, check['file'])
    if check['file'].endswith('.py'):
        classes = {
            'acceptance/api_tests.py': 'AcceptanceTests',
            'acceptance/security_tests.py': 'SecurityTests',
            'acceptance/migration_tests.py': 'MigrationTests',
        }
        class_name = classes.get(check['file'])
        if not class_name:
            raise GenerationError(f'Unsupported acceptance Python file: {check["file"]}')
        return [sys.executable, str(script), f'{class_name}.{check["test"]}'], root
    if check['file'].endswith('.spec.js'):
        _node, npm = _node_binaries()
        config = safe_path(root, 'acceptance/playwright.config.ts')
        return [npm, 'exec', '--', 'playwright', 'test', '--config', str(config), str(script),
                '-g', check['test']], ROOT.parent / 'frontend'
    raise GenerationError(f'Unsupported acceptance tool: {check["file"]}')


async def _run_studio_build(user_id: int, project_id: str, version: int, context: dict) -> None:
    if context['source_format'] == 'multi-file':
        await ensure_frontend_build(user_id, project_id, version, context['files'], context['spec_hash'])
        return
    write_source_files(project_id, version, context['files'])
    index = version_directory(project_id, version) / 'index.html'
    if not index.is_file() or '<html' not in index.read_text().lower():
        raise GenerationError('The single-file production document is missing or invalid.')


async def _execute_check(
    user_id: int,
    project_id: str,
    version: int,
    job_id: str,
    attempt_id: int,
    context: dict,
    check: dict,
    env: dict,
    blocked_reason: str | None = None,
    failure_reason: str | None = None,
) -> dict:
    run = start_tool_run(
        check['file'], COMPILER_VERSION, check,
        provenance={
            'environment': check['environment'], 'required': check['required'],
            'mutates': check['mutates'], 'target': check['target'],
        },
        output_ref=f'{check["file"]}#{check["test"]}',
        spec_hash=context['spec_hash'], source_hash=context['source_hash'],
        user_id=user_id, job_id=job_id, attempt_id=attempt_id,
    )
    if run is None:
        raise RuntimeError('The verification job attempt is unavailable for tool-run persistence')
    started = time.monotonic()
    status = 'passed'
    error = None
    try:
        if failure_reason:
            raise GenerationError(failure_reason)
        if blocked_reason:
            status, error = 'blocked', blocked_reason
        else:
            missing = [name for name in check['environment'] if not env.get(name)]
            if missing:
                status, error = 'blocked', f'Missing required environment: {", ".join(missing)}'
            elif check['file'] == 'studio:frontend-build':
                await _run_studio_build(user_id, project_id, version, context)
            else:
                command, cwd = _command_for_check(version_directory(project_id, version), check)
                returncode, output = await _execute_process(
                    command, cwd, _process_environment(version_directory(project_id, version), env),
                    check['timeout'], run.id,
                )
                if returncode:
                    status = 'failed'
                    error = output or f'Acceptance process exited with status {returncode}.'
    except Exception as exc:
        status = 'failed' if status != 'blocked' else status
        error = f'{type(exc).__name__}: {str(exc)[:1800]}'
    ended_at = utc_now()
    duration_ms = max(0, round((time.monotonic() - started) * 1000))
    result = check_result(check, status, run.id, duration_ms, error)
    finish_tool_run(
        run, status, output_ref=result['output_ref'], error=error,
        ended_at=ended_at, duration_ms=duration_ms,
    )
    return result


async def _run_verification(
    user_id: int,
    project_id: str,
    version: int,
    job_id: str,
    attempt_id: int,
    context: dict,
) -> dict:
    overall_started_at = utc_now()
    overall_started = time.monotonic()
    env = _base_environment(user_id, project_id, version, context)
    results = []
    runtime_started = False
    acceptance_ready = False
    dependent_blocked = None
    checks = sorted(context['checks'], key=lambda check: (
        0 if check['id'] == 'build.production' else 1 if check['id'] == 'api.health' else 2,
        check['id'],
    ))
    try:
        for index, check in enumerate(checks):
            if index > 0 and not acceptance_ready and not dependent_blocked:
                _materialize_acceptance_files(user_id, project_id, version)
                _add_archive_environment(user_id, project_id, version, context, env)
                acceptance_ready = True
            if index > 0 and not runtime_started and context['backend_mode'] == 'fastapi' and not dependent_blocked:
                needs_runtime = any(item['kind'] in {'api', 'browser', 'persistence', 'validation'}
                                    for item in checks[index:] if item['file'] != 'studio:frontend-build')
                if needs_runtime:
                    try:
                        runtime_started = await _add_runtime_environment(user_id, project_id, version, context, env)
                    except Exception as exc:
                        result = await _execute_check(
                            user_id, project_id, version, job_id, attempt_id, context, check, env,
                            failure_reason=f'Runtime startup failed: {exc}',
                        )
                        results.append(result)
                        dependent_blocked = f'Runtime startup failed: {exc}'
                        continue
            result = await _execute_check(
                user_id, project_id, version, job_id, attempt_id, context, check, env, dependent_blocked,
            )
            results.append(result)
            if check['id'] in {'build.production', 'api.health'} and result['status'] != 'passed':
                dependent_blocked = f'{check["id"]} failed; dependent checks were not run.'
        if dependent_blocked:
            for check in checks[len(results):]:
                results.append(await _execute_check(
                    user_id, project_id, version, job_id, attempt_id, context, check, env, dependent_blocked,
                ))
    finally:
        if runtime_started:
            await runtime_manager.stop_project(project_id, channel='preview')
    ended_at = utc_now()
    duration_ms = max(0, round((time.monotonic() - overall_started) * 1000))
    report = build_report(
        project_id, version, job_id, attempt_id, context['spec_hash'], context['source_hash'],
        overall_started_at, ended_at, duration_ms, results, context['complete_coverage'],
    )
    content = report_json(report)
    report_path = version_directory(project_id, version) / 'acceptance' / 'report.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content)
    with workspace_db(user_id) as db:
        db.execute('INSERT OR REPLACE INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                   (project_id, 'verification', 'acceptance/report.json', content, version))
        record_event(db, job_id, 'verification_report', report, f'{attempt_id}:verification_report')
    return report


async def verify_package(
    user_id: int,
    project_id: str,
    version: int,
    force: bool = False,
    include_optional: bool = False,
    selected_check_ids: set[str] | None = None,
    config: Settings | None = None,
) -> dict:
    require_feature(FeatureFlag.ACCEPTANCE_GATE_V1, config)
    context = _load_context(user_id, project_id, version)
    required_ids = {check['id'] for check in context['checks'] if check['required']}
    checks = [check for check in context['checks']
              if (include_optional or check['required']) and (not selected_check_ids or check['id'] in selected_check_ids)]
    if not checks:
        raise GenerationError('No acceptance checks were selected for this verification run.')
    if any(check['id'] != 'build.production' for check in checks) and 'build.production' not in {check['id'] for check in checks}:
        checks.insert(0, next(check for check in context['checks'] if check['id'] == 'build.production'))
    context['complete_coverage'] = required_ids == {check['id'] for check in checks if check['required']}
    context['checks'] = checks
    input_data = {
        'project_id': project_id, 'version': version,
        'spec_hash': context['spec_hash'], 'source_hash': context['source_hash'],
        'include_optional': include_optional,
        'selected_check_ids': sorted(check['id'] for check in checks),
    }
    job_key = job_idempotency_key(project_id, 'verify-package', canonical_input_hash(input_data))
    outcome = {}

    async def operation():
        with workspace_db(user_id) as db:
            job = db.execute('SELECT id FROM generation_jobs WHERE project_id=? AND idempotency_key=?',
                             (project_id, job_key)).fetchone()
            attempt = db.execute('SELECT id FROM job_attempts WHERE job_id=? ORDER BY attempt_number DESC LIMIT 1',
                                 (job['id'],)).fetchone()
        outcome['report'] = await _run_verification(
            user_id, project_id, version, job['id'], attempt['id'], context,
        )

    await run_generation_job(
        user_id, project_id, 'verify', 'verify-package', input_data, operation,
        retry_succeeded=force,
    )
    with workspace_db(user_id) as db:
        job = db.execute('SELECT id,status FROM generation_jobs WHERE project_id=? AND idempotency_key=?',
                         (project_id, job_key)).fetchone()
    if job and job['status'] == 'cancelled':
        raise JobCancelledError('Verification was cancelled. Retry when you are ready.')
    if outcome:
        return outcome['report']
    latest = latest_verification_report(user_id, job['id']) if job else None
    if latest:
        return latest
    raise GenerationError('Verification is already running for this package.')
