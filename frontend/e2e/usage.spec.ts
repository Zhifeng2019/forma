import { test, expect } from '@playwright/test'

test.use({ trace: 'off' })
test.skip(process.env.DURABLE_JOBS_V1 !== 'true', 'Usage inspection requires durable jobs')

test('Activity shows honest local usage and per-job evidence', async ({ page }) => {
  const email = `e2e-usage-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Usage Activity')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  await expect(page).toHaveURL('/')
  const token = await page.evaluate(() => localStorage.getItem('forma_token'))
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Usage Activity')
    await page.getByLabel('Tell us about your idea').fill('A local planning workspace with a clear daily overview.')
    await page.locator('.source-format-options label').filter({ hasText: 'Single file' }).click()
    await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await expect(page.getByRole('button', { name: 'Approve design' })).toBeEnabled()
    await page.getByRole('button', { name: 'Activity', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Work, measured honestly.' })).toBeVisible()
    await expect(page.locator('.usage-summary')).toContainText('Unknown')
    await expect(page.locator('.usage-job').first()).toContainText('discovery')
    await expect(page.locator('.usage-job').first()).toContainText('No tool runs')
  } finally {
    if (projectId && token) await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${token}` } })
  }
})
