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

  const feedback = 'Keep Phase 1 and make the primary action calmer.'
  let releaseMessage: () => void = () => {}
  let messagePending = false
  await page.route('**/api/projects/*/messages', async route => {
    messagePending = true
    await new Promise<void>(resolve => { releaseMessage = resolve })
    await route.continue()
  })
  await page.getByPlaceholder('Ask for a change or share feedback…').fill(feedback)
  await page.locator('.send-button').click()
  try {
    await expect(page.locator('.chat-message.user').getByText(feedback, { exact: true })).toBeVisible()
    await expect.poll(() => messagePending).toBe(true)
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeDisabled()
  } finally { releaseMessage() }
  await expect(page.getByText('Your feedback has been applied in a new version.', { exact: false }).last()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Approve phase 2' })).toHaveCount(0)
  await page.unroute('**/api/projects/*/messages')

  await page.getByRole('button', { name: 'Approve phase 1' }).click()
  await expect(page.getByRole('button', { name: 'Approve phase 2' })).toBeEnabled()
  await page.getByRole('button', { name: 'Approve phase 2' }).click()
  await expect(page.getByRole('button', { name: 'Approve release' })).toBeEnabled()

  await page.getByTitle('Select element to edit').click()
  await frame.getByRole('heading', { name: 'Make good work feel effortless.' }).click()
  await expect(page.locator('.selection-pill')).toBeVisible()
  await page.getByPlaceholder('What should change here?').fill('Keep this headline clear and confident.')
  await page.locator('.send-button').click()
  await expect(page.getByText('Your feedback has been applied in a new version.', { exact: false }).last()).toBeVisible()

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

test('a FastAPI app runs, persists data, and works at its public URL', async ({ page }) => {
  test.setTimeout(240_000)
  const email = `e2e-backend-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Backend End To End')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  await expect(page).toHaveURL('/')
  const token = await page.evaluate(() => localStorage.getItem('forma_token'))
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Collective Priorities')
    await page.getByLabel('Tell us about your idea').fill('A shared team workspace with a database for priorities, completion, and live progress.')
    await page.locator('.architecture-options label').filter({ hasText: 'FastAPI backend' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await expect(page.locator('.architecture-label')).toHaveText('FastAPI')

    await page.getByRole('button', { name: 'Approve design' }).click()
    await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
    await page.getByRole('button', { name: 'Start building' }).click()
    await page.getByRole('button', { name: 'Build phase 1' }).click()
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
    const frame = page.frameLocator('iframe')
    await expect(frame.getByText('FastAPI connected')).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: 'Server', exact: true }).click()
    await expect(page.getByText('Healthy', { exact: true })).toBeVisible()
    await expect(page.getByText('Per-app Python + SQLite')).toBeVisible()
    await page.screenshot({ path: 'e2e-artifacts/backend-server.png', fullPage: true })

    await page.getByRole('button', { name: 'Preview', exact: true }).click()
    await page.getByRole('button', { name: 'Approve phase 1' }).click()
    await expect(page.getByRole('button', { name: 'Approve phase 2' })).toBeEnabled()
    await frame.getByLabel('New item title').fill('Browser verification')
    await frame.getByRole('button', { name: 'Add priority' }).click()
    await expect(frame.getByText('Browser verification', { exact: true })).toBeVisible()
    await frame.getByRole('button', { name: 'Refresh from server' }).click()
    await expect(frame.getByText('Browser verification', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: 'Publish', exact: true }).click()
    await page.getByRole('button', { name: 'Publish application' }).click()
    await expect(page.getByText('Your app is out in the world.')).toBeVisible()
    const publicUrl = await page.locator('.copy-field input').inputValue()
    const publicPage = await page.context().newPage()
    await publicPage.goto(publicUrl)
    await expect(publicPage.getByText('FastAPI connected')).toBeVisible({ timeout: 60_000 })
    await expect(publicPage.getByText('Browser verification', { exact: true })).toBeVisible()
    await publicPage.screenshot({ path: 'e2e-artifacts/backend-public.png', fullPage: true })
    await publicPage.close()
  } finally {
    if (projectId && token) await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${token}` } })
  }
})

test('autopilot refreshes the workspace through the final preview', async ({ page }) => {
  const email = `e2e-autopilot-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Autopilot End To End')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  const token = await page.evaluate(() => localStorage.getItem('forma_token'))
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Automatic Focus')
    await page.getByLabel('Tell us about your idea').fill('A personal focus timer with local notes and a calm weekly overview.')
    await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
    await page.locator('.toggle-row').filter({ hasText: 'Autopilot mode' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await expect(page.getByRole('button', { name: 'Approve release' })).toBeEnabled({ timeout: 30_000 })
    await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
    await page.getByRole('button', { name: 'History', exact: true }).click()
    await expect(page.getByText('Version 3 · Phase 3', { exact: true })).toBeVisible()
  } finally {
    if (projectId && token) await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${token}` } })
  }
})

test('an existing app migrates between frontend-only and FastAPI without changing phase', async ({ page }) => {
  test.setTimeout(240_000)
  const email = `e2e-migration-${Date.now()}@example.com`
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Migration End To End')
  await page.getByLabel('Email address').fill(email)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  const token = await page.evaluate(() => localStorage.getItem('forma_token'))
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Migration Studio')
    await page.getByLabel('Tell us about your idea').fill('A personal planning workspace that may later need shared team data.')
    await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await page.getByRole('button', { name: 'Approve design' }).click()
    await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
    await page.getByRole('button', { name: 'Start building' }).click()
    await page.getByRole('button', { name: 'Build phase 1' }).click()
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()

    await page.locator('.architecture-button').click()
    await expect(page.getByRole('heading', { name: 'Add a FastAPI backend?' })).toBeVisible()
    let releaseMigration: () => void = () => {}
    let migrationHandled = false
    await page.route('**/api/projects/*/architecture', async route => {
      await new Promise<void>(resolve => { releaseMigration = resolve })
      await route.continue()
      migrationHandled = true
    })
    await page.getByRole('button', { name: 'Add FastAPI', exact: true }).click()
    try {
      await expect(page.getByRole('heading', { name: 'Add a FastAPI backend?' })).toHaveCount(0)
      await expect(page.locator('.approval-bar').getByText('Migrating to FastAPI…', { exact: true })).toBeVisible()
    } finally { releaseMigration() }
    await expect.poll(() => migrationHandled).toBe(true)
    await page.unroute('**/api/projects/*/architecture')
    const frame = page.frameLocator('iframe')
    await expect(frame.getByText('FastAPI connected')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Approve phase 2' })).toHaveCount(0)

    await page.locator('.architecture-button').click()
    await expect(page.getByRole('heading', { name: 'Move to frontend-only?' })).toBeVisible()
    await page.getByRole('button', { name: 'Switch to frontend only', exact: true }).click()
    await expect(frame.getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Server', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
    await page.getByRole('button', { name: 'History', exact: true }).click()
    await expect(page.getByText('Version 2 · FastAPI migration', { exact: true })).toBeVisible()
    await expect(page.getByText('Version 3 · Frontend-only migration', { exact: true })).toBeVisible()
  } finally {
    if (projectId && token) await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${token}` } })
  }
})
