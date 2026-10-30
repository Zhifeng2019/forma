"""Generated accessibility, responsive-layout, and interaction-state checks."""

from .common import AcceptanceContext, GeneratedCheck


def generate_ui_quality_tests(context: AcceptanceContext) -> tuple[str, list[GeneratedCheck]]:
    if not context.contract:
        return '', []
    tests = ['''
test('semantic headings labels and keyboard navigation', async ({ page }) => {
  await openApp(page)
  await expect(page.locator('h1')).toHaveCount(1)
  for (const field of FIELDS) {
    const input = page.locator(`[name="${field.name}"]`)
    expect(await input.evaluate(element => Boolean(
      element.labels?.length || element.getAttribute('aria-label') || element.getAttribute('aria-labelledby')
    ))).toBe(true)
  }
  await page.keyboard.press('Tab')
  const focused = await page.evaluate(() => {
    const element = document.activeElement
    if (!element || element === document.body) return null
    return { outline: getComputedStyle(element).outlineStyle }
  })
  expect(focused).not.toBeNull()
  expect(focused.outline).not.toBe('none')
  await page.keyboard.press('Shift+Tab')
  await capture(page, 'browser.accessibility-keyboard')
})
''', '''
test('desktop tablet and mobile layouts do not overflow', async ({ page }) => {
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1000 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await openApp(page)
    await expect(page.getByRole('button', { name: CREATE_LABEL })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await capture(page, `browser.responsive-layout-${viewport.name}`)
  }
})
''']
    checks = [
        GeneratedCheck(
            'browser.accessibility', 'accessibility', 'heading, labels, and keyboard navigation',
            'semantic headings labels and keyboard navigation', 'acceptance/browser_tests.spec.js',
            environment=('APP_PREVIEW_URL', 'APP_EVIDENCE_DIR'),
        ),
        GeneratedCheck(
            'browser.responsive-layout', 'browser', 'desktop, tablet, and mobile overflow',
            'desktop tablet and mobile layouts do not overflow', 'acceptance/browser_tests.spec.js',
            timeout=90, environment=('APP_PREVIEW_URL', 'APP_EVIDENCE_DIR'),
        ),
    ]
    if context.phase >= 2:
        loading = '''
  await page.route('**/*', async route => {
    const request = route.request()
    if (request.method() === 'GET' && new URL(request.url()).pathname.includes(COLLECTION_KEY)) {
      const response = await route.fetch()
      await new Promise(resolve => setTimeout(resolve, 500))
      await route.fulfill({ response })
    } else await route.continue()
  })
  const refreshing = page.getByRole('button', { name: 'Refresh data' }).click()
  await expect(page.locator('.loading-state')).toBeVisible()
  await capture(page, 'browser.interaction-states-loading')
  await refreshing
  await page.unroute('**/*')
''' if context.spec.architecture.backend_mode == 'fastapi' else ''
        error = '''
  await page.route('**/*', async route => {
    const request = route.request()
    if (request.method() === 'GET' && new URL(request.url()).pathname.includes(COLLECTION_KEY)) {
      await route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'Forced UI verification failure' }) })
    } else await route.continue()
  })
''' if context.spec.architecture.backend_mode == 'fastapi' else '''
  await page.evaluate(key => localStorage.setItem(key, '{'), STORAGE_KEY)
'''
        tests.append('''
test('empty populated success loading and error states have evidence', async ({ page }) => {
  await openApp(page)
  for (let index = 0; index < 20 && await page.locator('.item').count(); index++) {
    await page.locator('.item').first().getByRole('button', { name: DELETE_LABEL }).click()
    await expect(page.locator('.alert.success')).toBeVisible()
  }
  await expect(page.locator('.empty-state')).toBeVisible()
  await capture(page, 'browser.interaction-states-empty')
  for (const field of FIELDS) {
    const input = page.locator(`[name="${field.name}"]`)
    if (field.kind === 'boolean') { if (field.value) await input.check(); else await input.uncheck() }
    else await input.fill(String(field.value))
  }
  await page.getByRole('button', { name: CREATE_LABEL }).click()
  await expect(page.locator('.alert.success')).toBeVisible()
  const record = page.locator('.item').filter({ hasText: RECORD_TEXT }).first()
  await expect(record).toBeVisible()
  await capture(page, 'browser.interaction-states-populated')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await capture(page, 'browser.interaction-states-populated-mobile')
__LOADING_CHECK__
  await record.getByRole('button', { name: DELETE_LABEL }).click()
  await expect(page.locator('.alert.success')).toBeVisible()
  await expect(page.locator('.empty-state')).toBeVisible()
__ERROR_SETUP__
  await page.getByRole('button', { name: 'Refresh data' }).click()
  await expect(page.locator('.error')).toBeVisible()
  await capture(page, 'browser.interaction-states-error')
})
'''.replace('__LOADING_CHECK__', loading).replace('__ERROR_SETUP__', error))
        checks.append(GeneratedCheck(
            'browser.interaction-states', 'browser', 'empty, populated, success, loading, and error states',
            'empty populated success loading and error states have evidence', 'acceptance/browser_tests.spec.js',
            timeout=120, mutates=True, environment=('APP_PREVIEW_URL', 'APP_EVIDENCE_DIR'),
        ))
    return '\n'.join(tests), checks
