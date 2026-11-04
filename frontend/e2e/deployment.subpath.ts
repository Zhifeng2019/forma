import { test, expect } from '@playwright/test'
import { registerAccount } from './auth-helpers'

test('production studio works beneath /forma and uses its brand mark as the favicon', async ({ page, playwright }) => {
  const backend = await playwright.request.newContext({ baseURL: `http://127.0.0.1:${process.env.FORMA_TEST_BACKEND_PORT || 8129}` })
  const email = `subpath-${Date.now()}@example.com`
  try {
    await registerAccount(backend, { email, name: 'Subpath Member', password: 'password123' })
    const invalidRootRequests: string[] = []
    page.on('request', request => {
      if (new URL(request.url()).pathname.startsWith('/api/')) invalidRootRequests.push(request.url())
    })
    await page.goto('/forma/forgot-password')
    await expect(page.getByRole('heading', { name: 'Forgot your password?' })).toBeVisible()
    await page.reload()
    await page.getByRole('link', { name: 'Back to sign in' }).click()
    await expect(page).toHaveURL(/\/forma\/login$/)
    const favicon = await page.locator('link[rel="icon"]').getAttribute('href')
    expect(favicon).toBe('/forma/forma.svg')
    await expect(page.locator('.logo-mark').first()).toHaveAttribute('src', favicon!)
    const icon = await page.request.get(favicon!)
    expect(icon.ok()).toBeTruthy()
    expect(icon.headers()['content-type']).toContain('image/svg+xml')
    await page.getByRole('link', { name: 'Create an account' }).click()
    await expect(page).toHaveURL(/\/forma\/register$/)
    await page.getByRole('link', { name: 'Sign in', exact: true }).click()
    await page.screenshot({ path: '/tmp/forma-subpath-login.png', fullPage: true })
    await page.getByLabel('Email or mobile number').fill(email)
    await page.getByLabel('Password', { exact: true }).fill('password123')
    await page.getByRole('button', { name: 'Sign in to Forma' }).click()
    await expect(page).toHaveURL(/\/forma\/$/)
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Prefix Test')
    await page.getByLabel('Tell us about your idea').fill('A simple note list for personal tasks and ideas.')
    await page.locator('.source-format-options label').filter({ hasText: 'Single file' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/forma\/projects\/[a-f0-9]{32}$/)
    await expect(page.getByText('The product description is ready.', { exact: false })).toBeVisible()
    // Keep the next operation pending while checking its real event stream;
    // the local demo otherwise finishes before the first project render.
    let releaseAdvance: () => void = () => {}
    await page.route('**/forma/api/projects/*/advance', async route => {
      await new Promise<void>(resolve => { releaseAdvance = resolve })
      await route.continue()
    })
    const stream = page.waitForResponse(response => response.url().includes('/forma/api/projects/') && response.url().includes('/events?follow=true'), { timeout: 10_000 })
    await page.getByRole('button', { name: 'Approve design' }).click()
    try {
      const response = await stream
      expect(response.ok()).toBeTruthy()
      expect(response.headers()['content-type']).toContain('text/event-stream')
    } finally { releaseAdvance() }
    await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
    await page.unroute('**/forma/api/projects/*/advance')
    await page.reload()
    await expect(page.getByText('The product description is ready.', { exact: false })).toBeVisible()
    await page.goto('/forma/settings')
    await expect(page.locator('.account-card')).toContainText(email)
    await page.evaluate(() => localStorage.setItem('forma_token', 'expired-token'))
    await page.reload()
    await expect(page).toHaveURL(/\/forma\/login$/)
    expect(invalidRootRequests).toEqual([])
  } finally { await backend.dispose() }
})
