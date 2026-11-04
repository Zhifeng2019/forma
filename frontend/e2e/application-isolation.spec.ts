import { finishRegistration } from './auth-helpers'
import { test, expect } from '@playwright/test'

test('generated pages cannot read the studio session or control its document', async ({ page, context }) => {
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Browser Isolation')
  await page.getByLabel('Email address').fill(`isolation-${Date.now()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await finishRegistration(page)
  await expect(page).toHaveURL('/')
  const studioOrigin = new URL(page.url()).origin
  const token = await page.evaluate(() => localStorage.getItem('forma_token'))
  const headers = { Authorization: `Bearer ${token}` }
  const created = await page.request.post('/api/projects', { headers, data: {
    name: 'Browser boundary', brief: 'A personal notes page.',
    auto_mode: false, backend_mode: 'static', source_format: 'single-file',
  } })
  const project = await created.json()
  try {
    for (let step = 0; step < 3; step++) {
      const response = await page.request.post(`/api/projects/${project.id}/advance`, { headers, data: {} })
      expect(response.ok()).toBeTruthy()
    }
    let grants = 0
    await page.route('**/preview-session?version=1', async route => {
      const response = await route.fetch()
      const data = await response.json()
      grants++
      // Shorten the first UI expiry to exercise renewal without waiting 15 minutes.
      if (grants === 1) data.expires_at = Math.floor(Date.now() / 1000) + 4
      await route.fulfill({ response, json: data })
    })
    await page.goto(`/projects/${project.id}`)
    await expect.poll(() => grants).toBeGreaterThan(1)
    const frameElement = page.locator('iframe')
    await expect(frameElement).toBeVisible()
    const previewUrl = await frameElement.getAttribute('src') || ''
    expect(new URL(previewUrl).origin).not.toBe(studioOrigin)
    expect(previewUrl).not.toContain(token)
    expect(previewUrl).not.toContain('access_token')
    const frame = page.frameLocator('iframe')
    await expect(frame.getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
    const previewFrame = page.frames().find(candidate => candidate.url() === previewUrl)!
    const attack = await previewFrame.evaluate(async () => {
      let parentStorageBlocked = false, parentDocumentBlocked = false
      try { void parent.localStorage.getItem('forma_token') } catch { parentStorageBlocked = true }
      try { parent.document.body.dataset.compromised = 'true' } catch { parentDocumentBlocked = true }
      return {
        token: localStorage.getItem('forma_token'), parentStorageBlocked, parentDocumentBlocked,
        controlStatus: (await fetch('/api/me')).status,
      }
    })
    expect(attack).toEqual({ token: null, parentStorageBlocked: true, parentDocumentBlocked: true, controlStatus: 404 })
    expect(await page.locator('body').getAttribute('data-compromised')).toBeNull()

    // A message with the right shape from the wrong window must not select anything.
    await page.getByTitle('Select element to edit').click()
    await page.evaluate(() => window.postMessage({
      type: 'forma-selection', selection: { selector: '#forged', text: 'forged' },
    }, window.location.origin))
    await expect(page.locator('.selection-pill')).toHaveCount(0)
    await frame.getByRole('heading', { name: 'Make good work feel effortless.' }).click()
    await expect(page.locator('.selection-pill')).toBeVisible()
    await expect(page.locator('.selection-pill')).not.toContainText('#forged')

    await page.getByRole('button', { name: 'Publish', exact: true }).click()
    await page.getByRole('button', { name: 'Publish application' }).click()
    const publicUrl = await page.locator('.copy-field input').inputValue()
    expect(new URL(publicUrl).origin).not.toBe(studioOrigin)
    expect(new URL(publicUrl).origin).not.toBe(new URL(previewUrl).origin)
    const publicPagePromise = context.waitForEvent('page')
    await page.getByRole('link', { name: 'Open live app' }).click()
    const publicPage = await publicPagePromise
    await publicPage.waitForLoadState()
    expect(await publicPage.evaluate(() => ({ token: localStorage.getItem('forma_token'), noOpener: window.opener === null })))
      .toEqual({ token: null, noOpener: true })
    expect(await publicPage.evaluate(async () => (await fetch('/api/me')).status)).toBe(404)
    await publicPage.close()

    // A studio URL must redirect before any generated HTML can execute there.
    const oldLink = await page.request.get(`/apps/${project.id}/`, { maxRedirects: 0 })
    expect(oldLink.status()).toBe(307)
    expect(oldLink.headers().location).toBe(publicUrl)
    expect((await context.cookies()).some(cookie => cookie.name.startsWith('forma_preview'))).toBe(false)
  } finally {
    await page.request.delete(`/api/projects/${project.id}`, { headers })
  }
})
