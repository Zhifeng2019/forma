import { createRequire } from 'node:module'
const require = createRequire(process.env.FRONTEND_PACKAGE)
const { chromium, expect, request } = require('@playwright/test')
const config = JSON.parse(process.env.COOKIE_TEST)
const browser = await chromium.launch()
const context = await browser.newContext()
const api = await request.newContext({ baseURL: config.base, extraHTTPHeaders: { Authorization: `Bearer ${config.token}` } })
const failures = []
context.on('requestfailed', request => failures.push(`${new URL(request.url()).origin}: ${request.failure()?.errorText}`))
try {
  const page = await context.newPage()
  // A real local response establishes the parent's network address space. An
  // intercepted synthetic navigation is treated as public by Chromium's LNA checks.
  expect((await page.goto(config.base + '/api/health')).ok()).toBe(true)
  await page.setContent('<html><body><iframe title="Application" sandbox="allow-scripts allow-forms allow-modals allow-same-origin"></iframe></body></html>')
  await page.locator('iframe').evaluate((frame, url) => { frame.src = url }, config.preview)
  const frame = page.frameLocator('iframe')
  await expect(frame.locator('#status')).toBeVisible({ timeout: 15_000 })
  await expect(frame.locator('#status')).toHaveText('Guest', { timeout: 120_000 })
  await frame.getByRole('button', { name: 'Log in', exact: true }).click()
  await expect(frame.locator('#status')).toHaveText('Signed in')
  const privateCookies = (await context.cookies()).filter(cookie => cookie.name === 'app_session')
  expect(privateCookies).toHaveLength(1)
  expect(privateCookies[0]).toMatchObject({ domain: new URL(config.preview).hostname, path: '/', secure: true, httpOnly: true, sameSite: 'None' })
  expect(privateCookies[0].partitionKey).toBe(new URL(config.base).protocol + '//' + new URL(config.base).hostname)
  let renewed
  await expect.poll(async () => {
    renewed = (await (await api.post(`/api/projects/${config.projectId}/preview-session`)).json()).url
    return renewed
  }).not.toBe(config.preview)
  await page.locator('iframe').evaluate((element, url) => { element.src = url }, renewed)
  await expect.poll(() => page.frames().some(item => item.url() === renewed)).toBe(true)
  await expect(frame.locator('#status')).toHaveText('Signed in')
  const previewFrame = page.frames().find(item => item.url() === renewed)
  expect(await previewFrame.evaluate(async () => (await fetch('/api/auth/me')).json())).toEqual({
    role: 'admin', studio_cookie: null, authorization: null,
  })
  expect(await previewFrame.evaluate(async () => (await fetch('/api/auth/touch', {
    method: 'POST', headers: { 'X-CSRFToken': 'fixture-csrf' },
  })).status)).toBe(200)

  const publicPage = await context.newPage()
  await publicPage.goto(config.public)
  await expect(publicPage.locator('#status')).toHaveText('Guest', { timeout: 120_000 })
  await publicPage.getByRole('button', { name: 'Log in', exact: true }).click()
  await expect(publicPage.locator('#status')).toHaveText('Signed in')
  const publicCookies = (await context.cookies()).filter(cookie => cookie.name === 'app_session')
  expect(publicCookies.map(cookie => cookie.domain).sort()).toEqual([
    new URL(config.preview).hostname, new URL(config.public).hostname,
  ].sort())
  await publicPage.getByRole('button', { name: 'Log out', exact: true }).click()
  await expect(publicPage.locator('#status')).toHaveText('Guest')
  expect(await previewFrame.evaluate(async () => (await fetch('/api/auth/me')).status)).toBe(200)
  await frame.getByRole('button', { name: 'Log out', exact: true }).click()
  await expect(frame.locator('#status')).toHaveText('Guest')
  expect((await context.cookies()).filter(cookie => cookie.name === 'app_session')).toHaveLength(0)
  console.log('Cookie login, renewal, CSRF headers, host isolation, and logout passed.')
} catch (error) {
  console.error('Failed requests:', failures)
  throw error
} finally {
  await api.dispose()
  await browser.close()
}
