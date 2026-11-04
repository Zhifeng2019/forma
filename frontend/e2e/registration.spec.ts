import { test, expect } from '@playwright/test'
import { adminSession, verificationCode } from './auth-helpers'

for (const method of ['email', 'sms'] as const) {
  test(`${method} registration requires contact verification and admin approval`, async ({ page, browser }) => {
    const contact = method === 'email' ? `registration-${Date.now()}@example.com` : `+86137${String(Date.now()).slice(-8)}`
    const name = method === 'email' ? 'Email Applicant' : 'Mobile Applicant'
    const password = 'verified-password123'
    await page.goto('/register')
    if (method === 'sms') {
      await page.setViewportSize({ width: 390, height: 844 })
      await page.getByRole('button', { name: 'Mobile (+86)' }).click()
    }
    await page.getByLabel('Full name').fill(name)
    await page.getByLabel(method === 'email' ? 'Email address' : 'Mainland China mobile number').fill(contact)
    await page.getByLabel('Password', { exact: true }).fill(password)
    const request = page.waitForResponse(response => response.url().endsWith('/api/auth/register') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Send verification code' }).click()
    const started = await request
    expect(started.ok()).toBeTruthy()
    const { challenge_id } = await started.json()
    const code = await verificationCode(challenge_id)
    await expect(page.getByRole('heading', { name: 'Verify your contact' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Resend in/ })).toBeDisabled()
    await page.reload()
    await expect(page.getByLabel('Verification code', { exact: true })).toBeVisible()
    await page.screenshot({ path: `/tmp/forma-registration-${method}.png`, fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    expect(await page.evaluate(() => localStorage.getItem('forma_token'))).toBeNull()
    const adminToken = await adminSession(page.request)
    const adminHeaders = { Authorization: `Bearer ${adminToken}` }
    const before = await (await page.request.get('/api/admin/users', { headers: adminHeaders })).json()
    expect(before.some((user: { email?: string; phone?: string }) => user.email === contact || user.phone === contact)).toBeFalsy()
    await page.getByLabel('Verification code', { exact: true }).fill(String((Number(code) + 1) % 1_000_000).padStart(6, '0'))
    await page.getByRole('button', { name: 'Verify and request approval' }).click()
    await expect(page.getByRole('alert')).toContainText('incorrect')
    await page.getByLabel('Verification code', { exact: true }).fill(code)
    await page.getByRole('button', { name: 'Verify and request approval' }).click()
    await expect(page.getByRole('heading', { name: 'Awaiting approval' })).toBeVisible()
    await page.getByRole('link', { name: 'Back to sign in' }).click()
    await page.getByLabel('Email or mobile number').fill(contact)
    await page.getByLabel('Password', { exact: true }).fill(password)
    await page.getByRole('button', { name: 'Sign in to Forma' }).click()
    await expect(page.getByRole('alert')).toContainText('awaiting administrator approval')
    expect(await page.evaluate(() => localStorage.getItem('forma_token'))).toBeNull()

    const adminContext = await browser.newContext({ baseURL: new URL(page.url()).origin })
    try {
      await adminContext.addInitScript(token => localStorage.setItem('forma_token', token), adminToken)
      const adminPage = await adminContext.newPage()
      await adminPage.goto('/admin')
      await adminPage.getByRole('button', { name: /User management/ }).click()
      await adminPage.getByLabel('Pending only').check()
      const row = adminPage.locator('.table-row').filter({ hasText: contact })
      await expect(row).toContainText('Awaiting approval')
      await expect(row).toContainText('Verified')
      await adminPage.screenshot({ path: `/tmp/forma-registration-admin-${method}.png`, fullPage: true })
      await row.getByRole('button', { name: 'Approve' }).click()
      await expect(adminPage.locator('.user-management').getByRole('status')).toContainText(`${name} is approved`)
      await expect(row).toHaveCount(0)
    } finally { await adminContext.close() }
    await page.getByRole('button', { name: 'Sign in to Forma' }).click()
    await expect(page).toHaveURL('/')
    await page.goto('/settings')
    await expect(page.locator('.account-card')).toContainText(contact)
  })
}
