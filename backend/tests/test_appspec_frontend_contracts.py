import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import pytest

from app.config import settings
from app.spec.compiler import compile_package
from app.spec.defaults import local_default_appspec
from app.verification.browser_tests import _browser_input_value
from app.verification.manifest import acceptance_artifacts

PRODUCT_NAME = 'Community Operations With A Deliberately Long Product Name'
PRIMARY_WORKFLOW = (
    'A registered member reviews upcoming community operations, filters them by date, '
    'opens an operation to inspect its details, and records attendance while seeing '
    'useful validation and confirmation feedback throughout the complete primary workflow.'
)


def stress_spec(source_format='single-file', backend_mode='static'):
    spec = local_default_appspec(
        PRODUCT_NAME,
        'Coordinate community operations with clear schedules and reliable attendance records.',
        source_format,
        backend_mode,
    )
    document = spec.model_dump(mode='json', exclude_none=True)
    document['product']['primary_workflow'] = PRIMARY_WORKFLOW
    document['entities'][0]['name'] = 'Event'
    document['entities'][0]['fields'] = [
        {'name': 'title', 'kind': 'string', 'required': True, 'constraints': {'maxLength': 160}},
        {'name': 'details', 'kind': 'text', 'required': False, 'constraints': {}},
        {'name': 'attendee_count', 'kind': 'integer', 'required': True, 'constraints': {'minimum': 0}},
        {'name': 'rating', 'kind': 'number', 'required': False, 'constraints': {}},
        {'name': 'published', 'kind': 'boolean', 'required': True, 'constraints': {}},
        {'name': 'available_on', 'kind': 'date', 'required': True, 'constraints': {}},
        {'name': 'created_at', 'kind': 'datetime', 'required': True, 'constraints': {}},
        {'name': 'external_id', 'kind': 'uuid', 'required': False, 'constraints': {}},
    ]
    for operation in document['api']:
        if operation['path'] != '/api/health':
            operation['entity'] = 'Event'
    return document


def test_browser_datetime_adapter_does_not_change_api_contract():
    package = compile_package(stress_spec('multi-file', 'fastapi'), phase=2)
    artifacts = acceptance_artifacts(package)
    browser = artifacts['acceptance/browser_tests.spec.js']
    fields = json.loads(re.search(r'^const FIELDS = (.+)$', browser, re.MULTILINE).group(1))
    by_name = {field['name']: field for field in fields}

    assert by_name['created_at']['value'] == '2026-01-01T00:00'
    assert by_name['available_on']['value'] == '2026-01-01'
    assert by_name['attendee_count']['value'] == 1
    assert by_name['rating']['value'] == 1.0
    assert by_name['published']['value'] is False
    assert "'created_at': '2026-01-01T00:00:00'" in artifacts['acceptance/api_tests.py']
    assert "getByRole('heading', { name: PRODUCT_NAME, exact: true, level: 1 })" in browser
    assert 'getByText(PRIMARY_WORKFLOW, { exact: true })' in browser


def test_browser_datetime_adapter_rejects_non_iso_values():
    assert _browser_input_value('datetime', '2026-01-01T00:00:00.123') == '2026-01-01T00:00'
    assert _browser_input_value('date', '2026-01-01') == '2026-01-01'
    with pytest.raises(ValueError, match='Invalid ISO datetime'):
        _browser_input_value('datetime', 'not-a-date')


@pytest.mark.parametrize('backend_mode', ['static', 'fastapi'])
@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
def test_every_frontend_uses_one_product_heading_and_supporting_workflow(source_format, backend_mode):
    package = compile_package(stress_spec(source_format, backend_mode), phase=2)
    if source_format == 'multi-file':
        app = package.files['frontend/src/App.jsx']
        workspace = package.files['frontend/src/components/Workspace.jsx']
        assert app.count('<h1>') == 1
        assert f'<h1>{{{json.dumps(PRODUCT_NAME)}}}</h1>' in app
        assert f'<p>{{{json.dumps(PRIMARY_WORKFLOW)}}}</p>' in app
        assert '<h2>Primary workflow</h2>' in workspace
        assert f'<h2>{{{json.dumps(PRIMARY_WORKFLOW)}}}</h2>' not in workspace
    else:
        html = package.files['index.html']
        assert html.count('<h1>') == 1
        assert f'<h1>{PRODUCT_NAME}</h1>' in html
        assert html.count(f'<p>{PRIMARY_WORKFLOW}</p>') == 1
        assert f'<h2>{PRIMARY_WORKFLOW}</h2>' not in html


def test_generated_static_browser_suite_executes_with_datetime_fields():
    if not shutil.which('npm'):
        pytest.skip('npm is required for generated Playwright verification')
    package = compile_package(stress_spec(), phase=2)
    artifacts = acceptance_artifacts(package)
    root = settings.data_path / 'appspec-frontend-contracts' / uuid.uuid4().hex
    for relative, content in {**package.files, **artifacts}.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    frontend = Path(__file__).parents[2] / 'frontend'
    env = dict(os.environ)
    env.update({
        'APP_PREVIEW_URL': (root / 'index.html').as_uri(),
        'NO_COLOR': '1',
        'NODE_PATH': str(frontend / 'node_modules'),
        'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
    })
    if Path('/Applications/Google Chrome.app').exists() or Path('/usr/bin/google-chrome').exists():
        env['PLAYWRIGHT_CHANNEL'] = 'chrome'
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
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
