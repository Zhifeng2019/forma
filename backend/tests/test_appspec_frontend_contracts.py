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
    assert "getByRole('heading', { name: PRIMARY_HEADING, exact: true, level: 1 })" in browser
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
        assert f'<p className="hero-workflow">{{{json.dumps(PRIMARY_WORKFLOW)}}}</p>' in app
        assert '<h2>{"Events"}</h2>' in workspace
        assert f'<h2>{{{json.dumps(PRIMARY_WORKFLOW)}}}</h2>' not in workspace
    else:
        html = package.files['index.html']
        assert html.count('<h1>') == 1
        assert f'<h1>{PRODUCT_NAME}</h1>' in html
        assert html.count(f'<p class="hero-workflow">{PRIMARY_WORKFLOW}</p>') == 1
        assert f'<h2>{PRIMARY_WORKFLOW}</h2>' not in html


CUSTOM_PRESENTATION = {
    'headline': 'Bring the community together',
    'entity_label': 'gathering',
    'entity_plural_label': 'gatherings',
    'create_label': 'Add a gathering',
    'empty_title': 'Your calendar is open',
    'empty_message': 'Add your first gathering to start planning.',
}


def custom_stress_spec(source_format='single-file', backend_mode='static'):
    document = stress_spec(source_format, backend_mode)
    document['frontend']['presentation'] = dict(CUSTOM_PRESENTATION)
    return document


def test_legacy_spec_receives_defaults_without_serializing_presentation():
    document = stress_spec('multi-file', 'static')
    package = compile_package(document, phase=2)
    assert package.spec.frontend.presentation is None
    assert 'presentation' not in document['frontend']
    workspace = package.files['frontend/src/components/Workspace.jsx']
    assert 'Create event' in workspace and 'Delete event' in workspace
    assert 'No events yet' in workspace
    assert 'Built from AppSpec' not in workspace and 'Phase 1' not in workspace


@pytest.mark.parametrize('source_format', ['single-file', 'multi-file'])
def test_custom_presentation_drives_frontend_and_acceptance_contract(source_format):
    package = compile_package(custom_stress_spec(source_format), phase=2)
    source = '\n'.join(package.files.values())
    for value in CUSTOM_PRESENTATION.values():
        assert value in source
    assert 'Create record' not in source and 'Delete record' not in source
    assert 'Built from AppSpec' not in source and 'Phase 1' not in source
    browser = acceptance_artifacts(package)['acceptance/browser_tests.spec.js']
    assert 'const PRIMARY_HEADING = "Bring the community together"' in browser
    assert 'const CREATE_LABEL = "Add a gathering"' in browser
    assert 'const DELETE_LABEL = "Delete gathering"' in browser
    assert '{ name: CREATE_LABEL }' in browser and '{ name: DELETE_LABEL }' in browser


def test_generated_static_browser_suite_executes_with_datetime_fields():
    if not shutil.which('npm'):
        pytest.skip('npm is required for generated Playwright verification')
    package = compile_package(custom_stress_spec(), phase=2)
    artifacts = acceptance_artifacts(package)
    extra_tests = '''
test('custom presentation, async states, and mobile layout work together', async ({ page }) => {
  await openApp(page)
  await expect(page.locator('.empty-state')).toContainText(__EMPTY_TITLE__)
  for (const field of FIELDS) {
    const input = page.locator(`[name="${field.name}"]`)
    if (field.kind === 'boolean') { if (field.value) await input.check(); else await input.uncheck() }
    else await input.fill(String(field.value))
  }
  await page.getByRole('button', { name: CREATE_LABEL }).click()
  await expect(page.locator('.alert.success')).toHaveText('Gathering created.')
  const record = page.locator('.item').filter({ hasText: RECORD_TEXT }).first()
  await expect(record).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await record.getByRole('button', { name: DELETE_LABEL }).click()
  await expect(page.locator('.alert.success')).toHaveText('Gathering deleted.')
  await expect(page.locator('.empty-state')).toContainText(__EMPTY_TITLE__)
})

test('storage failures show an actionable offline error', async ({ page }) => {
  await openApp(page)
  await page.evaluate(key => localStorage.setItem(key, '{'), __STORAGE_KEY__)
  await page.getByRole('button', { name: 'Refresh data' }).click()
  await expect(page.locator('.alert.error')).toBeVisible()
  await expect(page.locator('#connection')).toHaveClass(/offline/)
})
'''.replace('__EMPTY_TITLE__', json.dumps(CUSTOM_PRESENTATION['empty_title'])).replace(
        '__STORAGE_KEY__', json.dumps(f'forma-appspec:{PRODUCT_NAME}:events'),
    )
    artifacts['acceptance/browser_tests.spec.js'] += extra_tests
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
