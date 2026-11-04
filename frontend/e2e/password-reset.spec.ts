import { test, expect } from '@playwright/test'
import { DatabaseSync } from 'node:sqlite'
import path from 'node:path'
import { registerAccount, verificationCode } from './auth-helpers'

for (const method of ['email', 'sms'] as const) {
  test(`${method} password reset verifies contact and signs out previous sessions`, async ({ page }) => {
    const identity = method === 'email' ? `reset-${Date.now()}@example.com` : `+86136${String(Date.now()).slice(-8)}`
    const oldPassword = 'old-password-123'
    const newPassword = 'new-password-456'
    const account = await registerAccount(page.request, { name: 'Reset Member', password: oldPassword, [method === 'email' ? 'email' : 'phone']: identity })
    // Fixture accounts represent existing registrations older than the shared send cooldown.
    // This touches only the explicitly isolated Playwright database, never the user's data.
    if (!process.env.FORMA_TEST_DATA_DIR) throw new Error('Missing isolated browser-test database')
    const db = new DatabaseSync(path.join(process.env.FORMA_TEST_DATA_DIR, 'control.db'))
    try { db.prepare('UPDATE auth_rate_events SET created_at=created_at-61').run() } finally { db.close() }
    const oldHeaders = { Authorization: `Bearer ${account.token}` }
    await page.goto('/login')
    await page.getByRole('link', { name: 'Forgot password?' }).click()
    await expect(page.getByRole('heading', { name: 'Forgot your password?' })).toBeVisible()
    if (method === 'sms') {
      await page.setViewportSize({ width: 390, height: 844 })
      await page.getByRole('button', { name: 'Mobile (+86)' }).click()
    }
    await page.getByLabel(method === 'email' ? 'Email address' : 'Mainland China mobile number').fill(identity)
    const sending = page.waitForResponse(response => response.url().endsWith('/api/auth/password-reset') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Send reset code' }).click()
    const response = await sending
    expect(response.ok()).toBeTruthy()
    const { challenge_id } = await response.json()
    const code = await verificationCode(challenge_id)
    await expect(page.getByRole('heading', { name: 'Set a new password' })).toBeVisible()
    await expect(page.getByRole('button', { name: /Resend in/ })).toBeDisabled()
    await page.getByLabel('New password', { exact: true }).fill(newPassword)
    await page.reload()
    await expect(page.getByLabel('Verification code', { exact: true })).toBeVisible()
    await expect(page.getByLabel('New password', { exact: true })).toHaveValue('')
    const stored = await page.evaluate(() => sessionStorage.getItem('forma_password_reset'))
    expect(stored).not.toContain(newPassword)
    await page.getByLabel('Verification code', { exact: true }).fill(String((Number(code) + 1) % 1_000_000).padStart(6, '0'))
    await page.getByLabel('New password', { exact: true }).fill(newPassword)
    await page.getByLabel('Confirm new password', { exact: true }).fill('different-password')
    await page.getByRole('button', { name: 'Reset password', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('do not match')
    await page.getByLabel('Confirm new password', { exact: true }).fill(newPassword)
    await page.getByRole('button', { name: 'Reset password', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('invalid or expired')
    await page.getByLabel('Verification code', { exact: true }).fill(code)
    await page.screenshot({ path: `/tmp/forma-password-reset-${method}.png`, fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.getByRole('button', { name: 'Reset password', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Password updated', exact: true })).toBeVisible()
    expect(await page.evaluate(() => sessionStorage.getItem('forma_password_reset'))).toBeNull()
    expect((await page.request.get('/api/me', { headers: oldHeaders })).status()).toBe(401)
    expect((await page.request.post('/api/auth/login', { data: { identifier: identity, password: oldPassword } })).status()).toBe(401)
    await page.getByRole('link', { name: 'Back to sign in' }).click()
    await page.getByLabel('Email or mobile number').fill(identity)
    await page.getByLabel('Password', { exact: true }).fill(newPassword)
    await page.getByRole('button', { name: 'Sign in to Forma' }).click()
    await expect(page).toHaveURL('/')
  })
}
