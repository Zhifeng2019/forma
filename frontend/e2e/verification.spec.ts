import { test, expect } from '@playwright/test'

test.use({ trace: 'off' })

test.skip(process.env.ACCEPTANCE_GATE_V1 !== 'true' || process.env.APPSPEC_V1 !== 'true',
  'Verification requires ACCEPTANCE_GATE_V1 and APPSPEC_V1')

test('a user reviews deterministic evidence and publishes a verified app', async ({ page }) => {
  test.setTimeout(120_000)
  const email = `e2e-verification-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Verification Reviewer')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  await expect(page).toHaveURL('/')

  await page.getByRole('button', { name: 'New application' }).click()
  await page.getByLabel('Application name').fill('Verified Contract')
  await page.getByLabel('Tell us about your idea').fill('A personal focus timer with a weekly overview and local progress tracking.')
  await page.locator('.source-format-options label').filter({ hasText: 'Single file' }).click()
  await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
  await page.getByRole('button', { name: 'Start building' }).click()
  await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
  await expect(page.getByText('The product description is ready.', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: 'Approve design' }).click()
  await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
  await page.getByRole('button', { name: 'Start building' }).click()
  await expect(page.getByRole('button', { name: 'Contract', exact: true })).toHaveAttribute('class', 'active')
  await expect(page.locator('.spec-meta')).toContainText('Review draft')
  await page.getByRole('button', { name: 'Build phase 1' }).click()
  await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()

  await page.getByRole('button', { name: 'Verification', exact: true }).click()
  await expect(page.getByText('No verification report yet')).toBeVisible()
  await page.getByRole('button', { name: 'Verify application' }).click()
  await expect(page.locator('.verification-summary')).toContainText('All required checks passed', { timeout: 90_000 })
  await expect(page.locator('.verification-facts')).toContainText('Coverage Complete')
  await expect(page.locator('.verification-checks')).toContainText('build.production')
  await expect(page.locator('.verification-checks')).toContainText('browser.primary-workflow')
  await page.screenshot({ path: 'e2e-artifacts/verification-desktop.png', fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.verification-view')).toBeVisible()
  await page.screenshot({ path: 'e2e-artifacts/verification-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Publish', exact: true }).click()
  await page.getByRole('button', { name: 'Publish application' }).click()
  await expect(page.getByText('Your app is out in the world.')).toBeVisible({ timeout: 90_000 })
  const publicUrl = await page.locator('.copy-field input').inputValue()
  expect(publicUrl).toContain('/apps/')
})
