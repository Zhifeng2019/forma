import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid
import zipfile

from app.config import settings
from app.frontend_builder import _digest
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.spec.legacy_adapter import legacy_appspec
from app.spec.service import spec_artifacts
from app.source_packages import local_source_package
from app.verification.manifest import acceptance_artifacts


def compiled(backend='fastapi', source_format='multi-file', phase=2):
    return compile_package(local_default_appspec(
        'Acceptance App', 'Verify the complete application contract.', source_format, backend,
    ), phase=phase)


def manifest(artifacts):
    return json.loads(artifacts['acceptance/manifest.json'])


def test_acceptance_generation_is_deterministic_and_provenance_complete():
    package = compiled()
    first = acceptance_artifacts(package)
    second = acceptance_artifacts(package)
    assert first == second
    assert set(first) == {
        'acceptance/api_tests.py', 'acceptance/browser_tests.spec.js',
        'acceptance/security_tests.py', 'acceptance/migration_tests.py', 'acceptance/manifest.json',
        'acceptance/playwright.config.ts',
    }
    document = manifest(first)
    assert document['spec_hash'] == package.spec_hash
    assert document['source_hash'] == package.source_hash
    assert document['generation'] == {'mode': 'appspec', 'phase': 2}
    ids = {check['id'] for check in document['checks']}
    assert {
        'build.production', 'api.health', 'api.crud', 'api.required-validation', 'persistence.restart',
        'browser.primary-workflow', 'browser.required-fields', 'browser.create-refresh-delete',
        'browser.validation-feedback', 'browser.accessibility', 'browser.responsive-layout',
        'browser.interaction-states', 'security.no-embedded-credentials',
        'security.no-host-environment-access', 'security.reviewed-dependencies',
        'security.no-external-frontend-urls', 'security.archive-exclusions',
        'migration.preserves-phase-and-publication', 'migration.republish-preserves-history',
    } <= ids
    checks = {check['id']: check for check in document['checks']}
    assert checks['browser.accessibility']['environment'] == ['APP_PREVIEW_URL', 'APP_EVIDENCE_DIR']
    assert checks['browser.responsive-layout']['environment'] == ['APP_PREVIEW_URL', 'APP_EVIDENCE_DIR']
    assert checks['browser.interaction-states']['environment'] == ['APP_PREVIEW_URL', 'APP_EVIDENCE_DIR']
    assert checks['persistence.restart']['environment'] == ['APP_BASE_URL', 'APP_RESTART_URL']
    assert checks['security.archive-exclusions']['environment'] == ['APP_SOURCE_DIR', 'APP_PACKAGE_ZIP']
    assert checks['migration.preserves-phase-and-publication']['required'] is False
    assert checks['migration.preserves-phase-and-publication']['mutates'] is True
    assert checks['api.crud']['mutates'] is True
    for path in ('acceptance/api_tests.py', 'acceptance/security_tests.py', 'acceptance/migration_tests.py'):
        compile(first[path], path, 'exec')
    browser = first['acceptance/browser_tests.spec.js']
    assert 'APP_PREVIEW_URL' in browser and 'Create item' in browser
    assert 'Refresh data' in browser and 'Delete item' in browser


def test_static_and_legacy_specs_generate_only_applicable_checks():
    static = acceptance_artifacts(compiled(backend='static', source_format='single-file', phase=1))
    document = manifest(static)
    ids = {check['id'] for check in document['checks']}
    assert 'api.health' not in ids and 'api.crud' not in ids
    assert 'browser.phase-one-read-only' in ids
    assert 'browser.accessibility' in ids and 'browser.responsive-layout' in ids
    assert 'browser.create-refresh-delete' not in ids and 'browser.interaction-states' not in ids
    assert 'security.archive-exclusions' not in ids
    assert 'No backend API operations' in static['acceptance/api_tests.py']
    compile(static['acceptance/security_tests.py'], 'acceptance/security_tests.py', 'exec')

    project = {
        'name': 'Legacy Acceptance', 'brief': 'Preserve a legacy package.',
        'backend_mode': 'fastapi', 'source_format': 'multi-file',
    }
    files = local_source_package(project['name'], project['brief'], 1, 'fastapi')
    legacy = compile_package(legacy_appspec(project, files), files)
    artifacts = acceptance_artifacts(legacy)
    legacy_ids = {check['id'] for check in manifest(artifacts)['checks']}
    assert 'api.health' in legacy_ids and 'api.crud' not in legacy_ids
    assert 'browser.primary-workflow' in legacy_ids


def materialize_package():
    package = compiled()
    root = settings.data_path / 'acceptance-generation' / uuid.uuid4().hex
    for relative, content in package.files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    artifacts = acceptance_artifacts(package)
    for relative, content in artifacts.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    archive = root / 'deployment.zip'
    with zipfile.ZipFile(archive, 'w') as package_zip:
        package_zip.writestr('frontend/dist/index.html', '<html></html>')
        package_zip.writestr('backend/main.py', 'from app.api import app\n')
    return root, archive


def run_security(root: Path, archive: Path):
    env = dict(os.environ)
    env.update({'APP_SOURCE_DIR': str(root), 'APP_PACKAGE_ZIP': str(archive)})
    return subprocess.run(
        [sys.executable, str(root / 'acceptance' / 'security_tests.py')],
        env=env, capture_output=True, text=True, timeout=30,
    )


def test_generated_security_suite_executes_and_detects_violations():
    root, archive = materialize_package()
    result = run_security(root, archive)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'OK' in result.stderr
    (root / 'frontend' / 'src' / 'App.jsx').write_text('const key = "sk-abcdefghijklmnop"\n')
    violated = run_security(root, archive)
    assert violated.returncode != 0
    assert 'Potential credential' in violated.stderr


def test_spec_artifacts_include_acceptance_without_changing_build_inputs():
    package = compiled()
    artifacts = spec_artifacts(package)
    assert set(artifacts) == {
        'appspec.json', 'build-manifest.json', 'acceptance/api_tests.py',
        'acceptance/browser_tests.spec.js', 'acceptance/security_tests.py',
        'acceptance/migration_tests.py', 'acceptance/manifest.json', 'acceptance/playwright.config.ts',
    }
    assert _digest(package.files) == _digest({**package.files, **artifacts})


def test_generated_api_suite_runs_health_crud_and_validation_against_live_backend():
    from urllib.request import urlopen

    root, _archive = materialize_package()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    log = (root / 'server.log').open('w')
    process = subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=root / 'backend', stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise AssertionError(f'Generated backend exited early: {(root / "server.log").read_text()[-1500:]}')
            try:
                with urlopen(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AssertionError(f'Generated backend did not start: {(root / "server.log").read_text()[-1500:]}')
                time.sleep(0.1)
        env = dict(os.environ)
        env['APP_BASE_URL'] = f'http://127.0.0.1:{port}'
        result = subprocess.run([
            sys.executable, str(root / 'acceptance' / 'api_tests.py'),
            'AcceptanceTests.test_health', 'AcceptanceTests.test_crud', 'AcceptanceTests.test_required_validation',
        ], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'OK' in result.stderr
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        log.close()
