import { test, expect } from '@playwright/test'

test('a user can shape, build, revise, and publish an application', async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('End To End')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  await expect(page).toHaveURL('/')
  await page.screenshot({ path: 'e2e-artifacts/dashboard.png', fullPage: true })

  await page.getByRole('button', { name: 'New application' }).click()
  await page.getByLabel('Application name').fill('Northstar Notes')
  await page.getByLabel('Tell us about your idea').fill('A calm client portal for independent consultants to organize project priorities, weekly momentum, and next actions.')
  await page.getByRole('button', { name: 'Start building' }).click()
  await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
  await expect(page.getByText('The product description is ready.', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: 'Approve design' }).click()
  await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
  await page.getByRole('button', { name: 'Start building' }).click()
  await page.getByRole('button', { name: 'Build phase 1' }).click()
  await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
  await page.screenshot({ path: 'e2e-artifacts/builder-desktop.png', fullPage: true })

  const frame = page.frameLocator('iframe')
  await expect(frame.getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
  await page.getByRole('button', { name: 'Approve phase 1' }).click()
  await expect(page.getByRole('button', { name: 'Approve phase 2' })).toBeEnabled()
  await page.getByRole('button', { name: 'Approve phase 2' }).click()
  await expect(page.getByRole('button', { name: 'Approve release' })).toBeEnabled()

  await page.getByTitle('Select element to edit').click()
  await frame.getByRole('heading', { name: 'Make good work feel effortless.' }).click()
  await expect(page.locator('.selection-pill')).toBeVisible()
  await page.getByPlaceholder('What should change here?').fill('Keep this headline clear and confident.')
  await page.locator('.send-button').click()
  await expect(page.getByText('Your feedback has been applied in a new version.', { exact: false })).toBeVisible()

  await page.getByRole('button', { name: 'Publish', exact: true }).click()
  await page.getByRole('button', { name: 'Publish application' }).click()
  await expect(page.getByText('Your app is out in the world.')).toBeVisible()
  const publicUrl = await page.locator('.copy-field input').inputValue()
  expect(publicUrl).toContain('/apps/')
  await page.screenshot({ path: 'e2e-artifacts/published.png', fullPage: true })

  await page.getByRole('button', { name: 'Close' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'e2e-artifacts/builder-mobile.png', fullPage: true })
  await expect(page.locator('.work-panel')).toBeVisible()
})
