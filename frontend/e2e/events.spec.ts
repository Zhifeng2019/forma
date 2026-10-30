import { test, expect } from '@playwright/test'

test.use({ trace: 'off' })
test.skip(process.env.DURABLE_JOBS_V1 !== 'true', 'Live event delivery requires DURABLE_JOBS_V1')

test('a manual build resumes event delivery from its last cursor', async ({ page }) => {
  const resumedCursors: string[] = []
  page.on('request', request => {
    if (!request.url().includes('/events?')) return
    const cursor = request.headers()['last-event-id']
    if (cursor) resumedCursors.push(cursor)
  })
  let releaseAdvance = () => {}
  const advanceResponseHeld = new Promise<void>(resolve => { releaseAdvance = resolve })

  const email = `e2e-events-${Date.now()}@example.com`
  const token = await page.goto('/register').then(async () => {
    await page.getByLabel('Full name').fill('Event Recovery')
    await page.getByLabel('Email address').fill(email)
    await page.getByLabel('Password', { exact: true }).fill('password123')
    await page.getByRole('button', { name: 'Create my studio' }).click()
    await expect(page).toHaveURL('/')
    return page.evaluate(() => localStorage.getItem('forma_token'))
  })
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Event Recovery')
    await page.getByLabel('Tell us about your idea').fill('A personal focus timer with local notes and a calm weekly overview.')
    await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await expect(page.getByRole('button', { name: 'Approve design' })).toBeEnabled()

    let disconnected = false
    await page.route('**/api/projects/*/events*', async route => {
      if (!disconnected) {
        disconnected = true
        const checkpoint = {
          schema_version: '1.0', id: 1, job_id: projectId, attempt_id: 1,
          type: 'job.progress', timestamp: new Date().toISOString(), payload: {},
        }
        await route.fulfill({
          status: 200,
          headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
          body: `id: 1\nevent: job.progress\ndata: ${JSON.stringify(checkpoint)}\n\n`,
        })
        return
      }
      await route.continue()
    })
    await page.route('**/api/projects/*/advance', async route => {
      const response = await route.fetch()
      await advanceResponseHeld
      await route.fulfill({ response })
    })
    await page.getByRole('button', { name: 'Approve design' }).click()
    await expect.poll(() => resumedCursors.length, { timeout: 15_000 }).toBeGreaterThan(0)
    expect(Number(resumedCursors[0])).toBeGreaterThan(0)
    releaseAdvance()
    await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
  } finally {
    releaseAdvance()
    if (projectId && token) await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${token}` } })
  }
})

test('autopilot reaches the final preview without duplicate versions', async ({ page }) => {
  const email = `e2e-autopilot-events-${Date.now()}@example.com`
  const token = await page.goto('/register').then(async () => {
    await page.getByLabel('Full name').fill('Autopilot Events')
    await page.getByLabel('Email address').fill(email)
    await page.getByLabel('Password', { exact: true }).fill('password123')
    await page.getByRole('button', { name: 'Create my studio' }).click()
    await expect(page).toHaveURL('/')
    return page.evaluate(() => localStorage.getItem('forma_token'))
  })
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Autopilot Events')
    await page.getByLabel('Tell us about your idea').fill('A personal focus timer with local notes and a calm weekly overview.')
    await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
    await page.locator('.toggle-row').filter({ hasText: 'Autopilot mode' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await expect(page.getByRole('button', { name: 'Approve release' })).toBeEnabled({ timeout: 45_000 })
    await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
    await page.getByRole('button', { name: 'History', exact: true }).click()
    await expect(page.getByText('Version 3 · Phase 3', { exact: true })).toBeVisible()
    await expect(page.locator('.versions-menu > button')).toHaveCount(4)
  } finally {
    if (projectId && token) await page.request.delete(`/api/projects/${projectId}`, { headers: { Authorization: `Bearer ${token}` } })
  }
})
