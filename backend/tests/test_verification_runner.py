import asyncio
import json
import uuid

import pytest

from app.config import Settings
from app.database import workspace_db, workspace_for
from app.features import FeatureDisabledError
from app.frontend_builder import version_directory
from app.llm import GenerationError
from app.runtime import runtime_manager
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.spec.schema import appspec_document
from app.spec.service import spec_artifacts
from app.verification.runner import verify_package


def build_check():
    return {
        'id': 'build.production', 'kind': 'build', 'target': 'frontend/dist/index.html',
        'test': 'ensure_frontend_build', 'file': 'studio:frontend-build',
        'required': True, 'timeout': 60, 'mutates': False, 'environment': [],
    }


def dummy_check(status='passed', required=True, environment=()):
    return {
        'id': 'security.dummy', 'kind': 'security', 'target': 'dummy',
        'test': f'test_{status}', 'file': 'acceptance/security_tests.py',
        'required': required, 'timeout': 5, 'mutates': False,
        'environment': list(environment),
    }


def dummy_script(status):
    if status == 'passed':
        body = '    def test_passed(self):\n        self.assertTrue(True)\n'
    else:
        body = f'    def test_{status}(self):\n        raise AssertionError("deliberate {status}")\n'
    return f'import unittest\n\nclass SecurityTests(unittest.TestCase):\n{body}\n\nif __name__ == "__main__":\n    unittest.main()\n'


def verification_project(user_id, checks, browser=False):
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    package = compile_package(local_default_appspec(
        'Verifier App', 'Exercise deterministic verification.', 'multi-file', 'static',
    ))
    with workspace_db(user_id) as db:
        db.execute("INSERT INTO projects(id,name,brief,backend_mode,source_format) VALUES(?,?,?,?,?)",
                   (project_id, 'Verifier App', 'Exercise deterministic verification.', 'static', 'multi-file'))
        db.execute("INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)",
                   (project_id, 1, 'Phase 1', 'static', 'multi-file'))
        for path, content in package.files.items():
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'build', path, content, 1))
        db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                   (project_id, 'build', 'appspec.json', appspec_document(package.spec), 1))
        manifest = {
            'spec_hash': package.spec_hash, 'source_hash': package.source_hash,
            'checks': [build_check(), *checks],
        }
        db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                   (project_id, 'build', 'acceptance/manifest.json',
                    json.dumps(manifest, sort_keys=True), 1))
    root = version_directory(project_id, 1)
    for path, content in package.files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (root / 'acceptance').mkdir(parents=True, exist_ok=True)
    for check in checks:
        if check['file'] == 'acceptance/security_tests.py':
            content = dummy_script(check['test'].removeprefix('test_'))
            (root / 'acceptance' / 'security_tests.py').write_text(content)
            with workspace_db(user_id) as db:
                db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (project_id, 'verification', 'acceptance/security_tests.py', content, 1))
        if browser:
            browser_source = (
                "import { test, expect } from '@playwright/test'\n"
                "test('primary workflow renders', async ({ page }) => {\n"
                "  await page.goto('data:text/html,<html><body>Verified</body></html>')\n"
                "  await expect(page.locator('body')).toHaveText('Verified')\n"
                "})\n"
            )
            config = (
                "import { defineConfig } from '@playwright/test'\n"
                "export default defineConfig({ testDir: '.', workers: 1, "
                "use: { channel: process.env.PLAYWRIGHT_CHANNEL || undefined }, reporter: 'line' })\n"
            )
            (root / 'acceptance' / 'browser_tests.spec.js').write_text(browser_source)
            (root / 'acceptance' / 'playwright.config.ts').write_text(config)
            with workspace_db(user_id) as db:
                db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (project_id, 'verification', 'acceptance/browser_tests.spec.js', browser_source, 1))
                db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                           (project_id, 'verification', 'acceptance/playwright.config.ts', config, 1))
    return project_id


def enabled():
    return Settings(acceptance_gate_v1=True)


def test_verification_persists_tool_runs_and_force_retries():
    user_id = 950100
    project_id = verification_project(user_id, [dummy_check()])
    first = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    assert first['status'] == 'passed' and first['can_publish'] is True
    assert first['attempt_id'] == 1 and first['complete_coverage'] is True
    assert all(check['tool_run_id'] for check in first['checks'])
    duplicate = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    assert duplicate['attempt_id'] == first['attempt_id']
    retried = asyncio.run(verify_package(user_id, project_id, 1, force=True, config=enabled()))
    assert retried['attempt_id'] == 2
    with workspace_db(user_id) as db:
        check_runs = db.execute('''SELECT provenance FROM tool_runs WHERE job_id=?
            AND tool_name IN ('studio:frontend-build','acceptance/security_tests.py')''', (first['job_id'],)).fetchall()
        assert len(check_runs) == 4
        assert all({'spec_hash', 'source_hash', 'duration_ms'} <= json.loads(row['provenance']).keys()
                   for row in check_runs)
        assert db.execute('SELECT current_attempt FROM generation_jobs WHERE id=?', (first['job_id'],)).fetchone()[0] == 2
        artifact = db.execute('SELECT content FROM artifacts WHERE project_id=? AND path=? AND version=1',
                              (project_id, 'acceptance/report.json')).fetchone()
        assert json.loads(artifact['content'])['attempt_id'] == 2


def test_failed_acceptance_cannot_publish():
    user_id = 950101
    project_id = verification_project(user_id, [dummy_check('failed')])
    report = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    assert report['status'] == 'failed' and report['can_publish'] is False
    assert report['summary']['required_failures'] == ['security.dummy']
    result = next(check for check in report['checks'] if check['id'] == 'security.dummy')
    assert 'deliberate failed' in result['error']
    with workspace_db(user_id) as db:
        status = db.execute('SELECT status FROM tool_runs WHERE job_id=? AND tool_name=?',
                            (report['job_id'], 'acceptance/security_tests.py')).fetchone()[0]
        assert status == 'failed'


def test_verifier_never_accepts_model_override(monkeypatch):
    user_id = 950101
    project_id = verification_project(user_id, [dummy_check()])

    async def model_output(*_args, **_kwargs):
        return 1, '{"status":"passed","can_publish":true}'

    monkeypatch.setattr('app.verification.runner._execute_process', model_output)
    report = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    assert report['status'] == 'failed' and report['can_publish'] is False
    result = next(check for check in report['checks'] if check['id'] == 'security.dummy')
    assert result['status'] == 'failed' and 'can_publish' in result['error']


def test_missing_environment_is_explicitly_blocked(monkeypatch):
    user_id = 950102
    project_id = verification_project(user_id, [dummy_check(environment=('REQUIRED_ENVIRONMENT',))])

    async def unexpected(*_args):
        raise AssertionError('A blocked check must not start a process')

    monkeypatch.setattr('app.verification.runner._execute_process', unexpected)
    report = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    result = next(check for check in report['checks'] if check['id'] == 'security.dummy')
    assert result['status'] == 'blocked' and 'REQUIRED_ENVIRONMENT' in result['error']
    assert report['can_publish'] is False


def test_partial_coverage_cannot_publish_and_optional_failures_are_warnings():
    user_id = 950103
    partial_project = verification_project(user_id, [dummy_check()])
    partial = asyncio.run(verify_package(
        user_id, partial_project, 1, selected_check_ids={'build.production'}, config=enabled(),
    ))
    assert partial['status'] == 'passed' and partial['can_publish'] is False
    assert partial['complete_coverage'] is False
    optional_project = verification_project(user_id, [dummy_check('failed', required=False)])
    optional = asyncio.run(verify_package(user_id, optional_project, 1, include_optional=True, config=enabled()))
    assert optional['status'] == 'passed_with_warnings' and optional['can_publish'] is True


def test_stale_source_hash_is_rejected_before_execution():
    user_id = 950104
    project_id = verification_project(user_id, [dummy_check()])
    with workspace_db(user_id) as db:
        db.execute('UPDATE artifacts SET content=? WHERE project_id=? AND path=? AND version=1',
                   ('changed', project_id, 'frontend/src/App.jsx'))
    with pytest.raises(GenerationError, match='does not match'):
        asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))


def test_verification_requires_feature_flag():
    user_id = 950105
    project_id = verification_project(user_id, [dummy_check()])
    with pytest.raises(FeatureDisabledError):
        asyncio.run(verify_package(user_id, project_id, 1, config=Settings(acceptance_gate_v1=False)))


def test_browser_check_executes_with_playwright():
    user_id = 950106
    project_id = verification_project(user_id, [{
        'id': 'browser.primary-workflow', 'kind': 'browser', 'target': '/',
        'test': 'primary workflow renders', 'file': 'acceptance/browser_tests.spec.js',
        'required': True, 'timeout': 60, 'mutates': False, 'environment': [],
    }], browser=True)
    report = asyncio.run(verify_package(user_id, project_id, 1, config=enabled()))
    result = next(check for check in report['checks'] if check['id'] == 'browser.primary-workflow')
    assert result['status'] == 'passed', result.get('error')
    assert report['can_publish'] is True


def test_live_package_verification_with_runtime_and_security():
    user_id = 950107
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    package = compile_package(local_default_appspec(
        'Live Verification', 'Verify a real FastAPI and React package.', 'multi-file', 'fastapi',
    ), phase=2)
    provenance = spec_artifacts(package)
    with workspace_db(user_id) as db:
        db.execute("INSERT INTO projects(id,name,brief,backend_mode,source_format) VALUES(?,?,?,?,?)",
                   (project_id, 'Live Verification', 'Verify a real FastAPI and React package.', 'fastapi', 'multi-file'))
        db.execute("INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)",
                   (project_id, 1, 'Phase 2', 'fastapi', 'multi-file'))
        for path, content in {**package.files, **provenance}.items():
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'build', path, content, 1))
    selected = {
        'build.production', 'api.health', 'api.crud', 'api.required-validation',
        'security.no-embedded-credentials', 'security.no-host-environment-access',
        'security.reviewed-dependencies', 'security.no-external-frontend-urls', 'security.archive-exclusions',
    }
    report = asyncio.run(verify_package(
        user_id, project_id, 1, selected_check_ids=selected, config=enabled(),
    ))
    assert report['status'] == 'passed', report['summary']
    assert all(check['status'] == 'passed' for check in report['checks'])
    assert report['complete_coverage'] is False and report['can_publish'] is False
    assert report['spec_hash'] == package.spec_hash and report['source_hash'] == package.source_hash
    assert asyncio.run(runtime_manager.status(project_id, 1))['status'] == 'stopped'
    with workspace_db(user_id) as db:
        runtime_runs = db.execute('''SELECT tool_name,status,provenance FROM tool_runs WHERE job_id=?
            AND tool_name IN ('runtime.launch','runtime.health') ORDER BY rowid''', (report['job_id'],)).fetchall()
        environment_run = db.execute('''SELECT provenance FROM tool_runs WHERE job_id=?
            AND tool_name='runtime.environment' ''', (report['job_id'],)).fetchone()
    assert [(row['tool_name'], row['status']) for row in runtime_runs] == [
        ('runtime.launch', 'succeeded'), ('runtime.health', 'succeeded'),
    ]
    for row in runtime_runs:
        provenance = json.loads(row['provenance'])
        assert provenance['spec_hash'] == package.spec_hash and provenance['source_hash'] == package.source_hash
        assert provenance['package_hash'] and provenance['python_version']
    environment = json.loads(environment_run['provenance'])
    assert environment['spec_hash'] == package.spec_hash and environment['source_hash'] == package.source_hash
    assert environment['requirements_hash'] and isinstance(environment['cache_hit'], bool)


def test_single_file_verification_materializes_source_before_build():
    user_id = 950108
    workspace_for(user_id)
    project_id = uuid.uuid4().hex
    package = compile_package(local_default_appspec(
        'Single File Verification', 'Verify a single-file static application.', 'single-file', 'static',
    ), phase=1)
    provenance = spec_artifacts(package)
    with workspace_db(user_id) as db:
        db.execute("INSERT INTO projects(id,name,brief,backend_mode,source_format) VALUES(?,?,?,?,?)",
                   (project_id, 'Single File Verification', 'Verify a single-file static application.', 'static', 'single-file'))
        db.execute("INSERT INTO versions(project_id,version,label,backend_mode,source_format) VALUES(?,?,?,?,?)",
                   (project_id, 1, 'Phase 1', 'static', 'single-file'))
        for path, content in {**package.files, **provenance}.items():
            db.execute('INSERT INTO artifacts(project_id,stage,path,content,version) VALUES(?,?,?,?,?)',
                       (project_id, 'build', path, content, 1))
    selected = {'build.production', 'security.no-embedded-credentials', 'security.no-external-frontend-urls'}
    report = asyncio.run(verify_package(user_id, project_id, 1, selected_check_ids=selected, config=enabled()))
    assert report['status'] == 'passed', report['summary']
    assert all(check['status'] == 'passed' for check in report['checks'])
    assert (version_directory(project_id, 1) / 'index.html').is_file()
