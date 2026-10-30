import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import threading
import uuid

from fastapi import HTTPException
import pytest

from app.api import get_verification_evidence
from app.database import workspace_for
from app.frontend_builder import ensure_frontend_build, version_directory
from app.spec.compiler import compile_package
from app.verification.manifest import acceptance_artifacts
from app.verification.runner import _evidence_for_check
from test_appspec_frontend_contracts import custom_stress_spec
from test_verification_runner import verification_project


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass


def test_multi_file_ui_quality_checks_generate_screenshot_evidence():
    if not shutil.which('npm'):
        pytest.skip('npm is required for generated Playwright verification')
    user_id = 980100
    project_id = uuid.uuid4().hex
    package = compile_package(custom_stress_spec('multi-file', 'static'), phase=2)
    artifacts = acceptance_artifacts(package)
    asyncio.run(ensure_frontend_build(user_id, project_id, 1, package.files, package.spec_hash))
    root = version_directory(project_id, 1)
    for relative, content in artifacts.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    handler = partial(QuietHandler, directory=str(root / 'frontend' / 'dist'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    frontend = Path(__file__).parents[2] / 'frontend'
    env = dict(os.environ)
    env.update({
        'APP_PREVIEW_URL': f'http://127.0.0.1:{server.server_port}/index.html',
        'APP_EVIDENCE_DIR': str(root / 'acceptance' / 'evidence'),
        'NO_COLOR': '1',
        'NODE_PATH': str(frontend / 'node_modules'),
        'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
    })
    if Path('/Applications/Google Chrome.app').exists() or Path('/usr/bin/google-chrome').exists():
        env['PLAYWRIGHT_CHANNEL'] = 'chrome'
    try:
        result = subprocess.run(
            [
                'npm', 'exec', '--', 'playwright', 'test',
                '--config', str(root / 'acceptance' / 'playwright.config.ts'),
                str(root / 'acceptance' / 'browser_tests.spec.js'),
            ],
            cwd=frontend,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_evidence_for_check(root, {'id': 'browser.accessibility'})) == 1
    assert len(_evidence_for_check(root, {'id': 'browser.responsive-layout'})) == 3
    assert len(_evidence_for_check(root, {'id': 'browser.interaction-states'})) == 4
    screenshots = list((root / 'acceptance' / 'evidence').glob('*.png'))
    assert len(screenshots) == 8
    assert all(path.stat().st_size > 1000 for path in screenshots)


def test_evidence_endpoint_is_owner_scoped_and_rejects_traversal():
    user_id = 980200
    project_id = verification_project(user_id, [])
    root = version_directory(project_id, 1)
    relative = 'acceptance/evidence/browser.accessibility-keyboard.png'
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'\x89PNG\r\n\x1a\nverification-image')

    response = get_verification_evidence(project_id, relative, version=1, user={'id': user_id})
    assert Path(response.path) == target
    workspace_for(user_id + 1)
    with pytest.raises(HTTPException):
        get_verification_evidence(project_id, relative, version=1, user={'id': user_id + 1})
    with pytest.raises(HTTPException):
        get_verification_evidence(project_id, '../secret.png', version=1, user={'id': user_id})
