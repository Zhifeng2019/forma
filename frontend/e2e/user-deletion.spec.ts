import { test, expect } from '@playwright/test'
import { adminSession, registerAccount, verificationCode } from './auth-helpers'

test('admin confirms user deletion and the contact can register again', async ({ page }) => {
  const email = `delete-${Date.now()}@example.com`
  const details = { email, name: 'Delete Test Member', password: 'delete-user-password' }
  const account = await registerAccount(page.request, details)
  const userHeaders = { Authorization: `Bearer ${account.token}` }
  const projectResponse = await page.request.post('/api/projects', { headers: userHeaders, data: {
    name: 'Private project to delete', brief: 'A simple personal task list.', backend_mode: 'static', defer: false,
  } })
  expect(projectResponse.ok()).toBeTruthy()
  const project = await projectResponse.json()
  const adminToken = await adminSession(page.request)
  const adminHeaders = { Authorization: `Bearer ${adminToken}` }
  await page.addInitScript(token => localStorage.setItem('forma_token', token), adminToken)
  await page.goto('/admin')
  await page.getByRole('button', { name: /User management/ }).click()
  await expect(page.getByRole('button', { name: 'Delete Studio Admin', exact: true })).toBeDisabled()
  const row = page.locator('.table-row').filter({ hasText: email })
  await row.getByRole('button', { name: `Delete ${details.name}`, exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Delete user?' })
  await expect(dialog).toContainText('all projects (1 total)')
  await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect((await page.request.get('/api/me', { headers: userHeaders })).ok()).toBeTruthy()
  await row.getByRole('button', { name: `Delete ${details.name}`, exact: true }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: '/tmp/forma-delete-user-confirmation.png', fullPage: true })
  expect(await dialog.evaluate(element => element.getBoundingClientRect().width <= window.innerWidth)).toBeTruthy()
  const deletion = page.waitForResponse(response => response.url().endsWith(`/api/admin/users/${account.user.id}`) && response.request().method() === 'DELETE')
  await dialog.getByRole('button', { name: 'Delete user and all data', exact: true }).click()
  expect((await deletion).ok()).toBeTruthy()
  await expect(dialog).toHaveCount(0)
  await expect(row).toHaveCount(0)
  await expect(page.locator('.user-management').getByRole('status')).toContainText('all their data were deleted')
  expect((await page.request.get('/api/me', { headers: userHeaders })).status()).toBe(401)
  expect((await page.request.get(`/api/projects/${project.id}`, { headers: userHeaders })).status()).toBe(401)
  const started = await page.request.post('/api/auth/register', { data: details })
  expect(started.ok()).toBeTruthy()
  const { challenge_id } = await started.json()
  const verified = await page.request.post('/api/auth/register/verify', { data: { challenge_id, code: await verificationCode(challenge_id) } })
  expect((await verified.json()).status).toBe('pending_approval')
  const members = await (await page.request.get('/api/admin/users', { headers: adminHeaders })).json()
  const newAccount = members.find((user: { email: string }) => user.email === email)
  expect(newAccount.id).toBeGreaterThan(account.user.id)
  expect(newAccount.status).toBe('pending')
  expect(newAccount.project_count).toBe(0)
})
