import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

import pytest

from fixtures.archived_appspec import archived_package

from app.config import settings
from app.verification.browser_tests import _browser_input_value
from app.verification.manifest import acceptance_artifacts

def test_browser_datetime_adapter_rejects_non_iso_values():
    assert _browser_input_value('datetime', '2026-01-01T00:00:00.123') == '2026-01-01T00:00'
    assert _browser_input_value('date', '2026-01-01') == '2026-01-01'
    with pytest.raises(ValueError, match='Invalid ISO datetime'):
        _browser_input_value('datetime', 'not-a-date')



CUSTOM_PRESENTATION = {
    'headline': 'Bring the community together',
    'entity_label': 'gathering',
    'entity_plural_label': 'gatherings',
    'create_label': 'Add a gathering',
    'empty_title': 'Your calendar is open',
    'empty_message': 'Add your first gathering to start planning.',
}






def test_generated_static_browser_suite_executes_with_datetime_fields():
    if not shutil.which('npm'):
        pytest.skip('npm is required for generated Playwright verification')
    package = archived_package(fixture='single-file-presentation')
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
        '__STORAGE_KEY__', json.dumps(f'forma-appspec:{package.spec.product.name}:events'),
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
        'APP_EVIDENCE_DIR': str(root / 'acceptance' / 'evidence'),
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
