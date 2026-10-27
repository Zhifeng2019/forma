"""Generate Playwright workflow and validation checks from AppSpec."""

from .common import (
    AcceptanceContext, GeneratedCheck, create_payload, javascript_json, required_string,
)


def generate_browser_tests(context: AcceptanceContext) -> tuple[dict[str, str], list[GeneratedCheck]]:
    spec = context.spec
    contract = context.contract
    fields = []
    if contract:
        values = create_payload(contract)
        fields = [{'name': field.name, 'kind': field.kind, 'required': field.required,
                   'value': values[field.name]} for field in contract.fields]
    record_text = next((field['value'] for field in fields if field['kind'] in {'string', 'text'}),
                       str(fields[0]['value']) if fields else '')
    header = f'''import {{ test, expect }} from '@playwright/test'

const PREVIEW_URL = process.env.APP_PREVIEW_URL || ''
const PRODUCT_NAME = {javascript_json(spec.product.name)}
const PRIMARY_WORKFLOW = {javascript_json(spec.product.primary_workflow)}
const FIELDS = {javascript_json(fields)}
const RECORD_TEXT = {javascript_json(record_text)}
const COLLECTION_KEY = {javascript_json(contract.collection if contract else '')}

const openApp = async page => {{
  if (!PREVIEW_URL) throw new Error('APP_PREVIEW_URL is required')
  await page.goto(PREVIEW_URL)
  await expect(page.locator('main')).toBeVisible()
}}
'''
    tests = ['''
test('primary workflow renders', async ({ page }) => {
  await openApp(page)
  await expect(page.locator('body')).not.toContainText('Build failed')
  __PRIMARY_HEADING_CHECK__
})
'''.replace('__PRIMARY_HEADING_CHECK__',
               "await expect(page.getByRole('heading', { name: PRIMARY_WORKFLOW })).toBeVisible()" if contract else '')]
    checks = [GeneratedCheck('browser.primary-workflow', 'browser', '/', 'primary workflow renders',
                             'acceptance/browser_tests.spec.js', environment=('APP_PREVIEW_URL',))]
    if contract:
        tests.append('''
test('required fields and phase controls match the contract', async ({ page }) => {
  await openApp(page)
  for (const field of FIELDS.filter(item => item.required && item.kind !== 'boolean')) {
    await expect(page.locator(`[name="${field.name}"]`)).toHaveAttribute('required', '')
  }
})
''')
        checks.append(GeneratedCheck('browser.required-fields', 'validation', 'required form fields',
                                     'required fields and phase controls match the contract',
                                     'acceptance/browser_tests.spec.js', environment=('APP_PREVIEW_URL',)))
        if context.phase == 1:
            tests.append('''
test('phase one keeps editing disabled', async ({ page }) => {
  await openApp(page)
  await expect(page.getByRole('button', { name: 'Create record' })).toBeDisabled()
})
''')
            checks.append(GeneratedCheck('browser.phase-one-read-only', 'browser', 'phase 1 read-only',
                                         'phase one keeps editing disabled', 'acceptance/browser_tests.spec.js',
                                         environment=('APP_PREVIEW_URL',)))
        else:
            tests.append('''
test('create, refresh, and delete completes the primary workflow', async ({ page }) => {
  await openApp(page)
  for (const field of FIELDS) {
    const input = page.locator(`[name="${field.name}"]`)
    if (field.kind === 'boolean') {
      if (field.value) await input.check()
      else await input.uncheck()
    } else {
      await input.fill(String(field.value))
    }
  }
  await page.getByRole('button', { name: 'Create record' }).click()
  const record = page.locator('.item').filter({ hasText: RECORD_TEXT }).first()
  await expect(record).toBeVisible()
  await page.getByRole('button', { name: 'Refresh data' }).click()
  await expect(record).toBeVisible()
  await record.getByRole('button', { name: 'Delete record' }).click()
  await expect(page.locator('.item').filter({ hasText: RECORD_TEXT })).toHaveCount(0)
})
''')
            checks.append(GeneratedCheck('browser.create-refresh-delete', 'browser', 'primary CRUD workflow',
                                         'create, refresh, and delete completes the primary workflow',
                                         'acceptance/browser_tests.spec.js', timeout=90, mutates=True,
                                         environment=('APP_PREVIEW_URL',)))
            required = required_string(contract)
            if required and spec.architecture.backend_mode == 'fastapi':
                tests.append(f'''
test('invalid input returns an error without creating a record', async ({{ page }}) => {{
  await openApp(page)
  const before = await page.locator('.item').count()
  for (const field of FIELDS) {{
    const input = page.locator(`[name="${{field.name}}"]`)
    const value = field.name === {javascript_json(required.name)} ? ' ' : String(field.value)
    if (field.kind === 'boolean') {{ if (field.value) await input.check() }}
    else await input.fill(value)
  }}
  const responsePromise = page.waitForResponse(response =>
    response.url().includes('/' + COLLECTION_KEY) && response.request().method() === 'POST'
  )
  await page.getByRole('button', {{ name: 'Create record' }}).click()
  const response = await responsePromise
  expect([400, 422]).toContain(response.status())
  await expect(page.locator('.item')).toHaveCount(before)
  {"await expect(page.locator('.error')).toBeVisible()" if spec.architecture.source_format == 'multi-file' else ''}
}})
''')
                checks.append(GeneratedCheck('browser.validation-feedback', 'validation', required.name,
                                             'invalid input returns an error without creating a record',
                                             'acceptance/browser_tests.spec.js', mutates=True,
                                             environment=('APP_PREVIEW_URL',)))
    config = (
        "import { defineConfig } from '@playwright/test'\n\n"
        "export default defineConfig({ testDir: '.', workers: 1, timeout: 90000, "
        "use: { viewport: { width: 1440, height: 1000 }, channel: process.env.PLAYWRIGHT_CHANNEL || undefined }, "
        "reporter: 'line' })\n"
    )
    return {
        'acceptance/browser_tests.spec.js': header + '\n'.join(tests),
        'acceptance/playwright.config.ts': config,
    }, checks
