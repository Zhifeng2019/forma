import { test, expect } from '@playwright/test'

test.skip(process.env.APPSPEC_V1 !== 'true', 'AppSpec review requires APPSPEC_V1=true')

test('a user reviews and revises the AppSpec before the first build', async ({ page }) => {
  const email = `e2e-appspec-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('AppSpec Reviewer')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  await expect(page).toHaveURL('/')

  await page.getByRole('button', { name: 'New application' }).click()
  await page.getByLabel('Application name').fill('Calm Contract')
  await page.getByLabel('Tell us about your idea').fill('A personal focus timer with a calm weekly overview and local progress tracking.')
  await page.locator('.source-format-options label').filter({ hasText: 'Single file' }).click()
  await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
  await page.getByRole('button', { name: 'Start building' }).click()
  await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
  await expect(page.getByText('The product description is ready.', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: 'Approve design' }).click()
  await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
  await page.getByRole('button', { name: 'Start building' }).click()

  await expect(page.getByRole('button', { name: 'Contract', exact: true })).toHaveAttribute('class', 'active')
  await expect(page.locator('.spec-heading')).toContainText('Calm Contract')
  await expect(page.locator('.spec-valid')).toContainText('Schema & hash verified')
  await expect(page.locator('.spec-meta')).toContainText('Review draft')
  await expect(page.locator('.spec-entity')).toContainText('Item')
  await expect(page.getByText('No backend operations', { exact: false })).toBeVisible()
  await expect(page.locator('.spec-checks')).toContainText('Primary browser workflow')
  await expect(page.getByRole('button', { name: 'Build phase 1' })).toBeEnabled()
  await page.screenshot({ path: 'e2e-artifacts/spec-review-desktop.png', fullPage: true })

  const feedback = 'Emphasize a calm weekly overview.'
  await page.getByPlaceholder('Ask for a change or share feedback…').fill(feedback)
  await page.locator('.send-button').click()
  await expect(page.locator('.spec-product')).toContainText(feedback)
  await expect(page.getByRole('button', { name: 'Build phase 1' })).toBeEnabled()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.spec-review')).toBeVisible()
  await page.screenshot({ path: 'e2e-artifacts/spec-review-mobile.png', fullPage: true })
  await page.getByRole('button', { name: 'Build phase 1' }).click()
  await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
  await expect(page.locator('iframe')).toBeVisible()
})
