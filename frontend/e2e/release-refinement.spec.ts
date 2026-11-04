import { registerAccount } from './auth-helpers'
import { test, expect } from '@playwright/test'

test('a published app can be refined and reviewed before explicitly republishing', async ({ page }) => {
  const account = await registerAccount(page.request, {
    email: `release-${Date.now()}@example.com`, name: 'Release Owner', password: 'password123',
  })
  const headers = { Authorization: `Bearer ${account.token}` }
  let projectId = ''
  try {
    const created = await page.request.post('/api/projects', { headers, data: {
      name: 'Release Preview', brief: 'A personal focus timer with a weekly overview.',
      backend_mode: 'static', source_format: 'single-file', auto_mode: false,
    } })
    expect(created.ok()).toBeTruthy()
    projectId = (await created.json()).id
    for (let step = 0; step < 6; step++) {
      expect((await page.request.post(`/api/projects/${projectId}/advance`, { headers, data: {} })).ok()).toBeTruthy()
    }
    const published = await (await page.request.post(`/api/projects/${projectId}/publish`, { headers, data: {} })).json()
    expect(published.current_version).toBe(3)
    const liveBefore = await (await page.request.get(published.published_url)).text()

    // These direct visits and refreshes also exercise FastAPI's production SPA routes.
    await page.goto('/login')
    await expect(page.getByLabel('Email or mobile number')).toBeVisible()
    await page.evaluate(token => localStorage.setItem('forma_token', token), account.token)
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: 'Configuration', exact: true })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('heading', { name: 'Configuration', exact: true })).toBeVisible()
    await page.goto(`/projects/${projectId}`)
    await page.reload()
    await expect(page.getByRole('button', { name: 'Published', exact: true })).toBeVisible()
    await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()

    await page.getByPlaceholder('Ask a question or request a change…').fill('Make the primary action blue.')
    await page.locator('.send-button').click()
    await expect(page.getByRole('button', { name: 'Approve release', exact: true })).toBeEnabled()
    const revised = await (await page.request.get(`/api/projects/${projectId}`, { headers })).json()
    expect(revised.current_version).toBe(4)
    expect(revised.phase_index).toBe(3)
    expect(revised.published_version).toBe(3)
    expect(await (await page.request.get(published.published_url)).text()).toBe(liveBefore)

    await page.getByRole('button', { name: 'Approve release', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Published', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Manage release', exact: true }).click()
    await expect(page.getByText('Version 3 is live and ready to share.', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Publish latest v4', exact: true }).click()
    await expect(page.getByText('Version 4 is live and ready to share.', { exact: true })).toBeVisible()
    const final = await (await page.request.get(`/api/projects/${projectId}`, { headers })).json()
    expect(final.current_version).toBe(4)
    expect(final.published_version).toBe(4)
    expect(final.versions.slice(1)).toEqual(published.versions)
  } finally {
    if (projectId) await page.request.delete(`/api/projects/${projectId}`, { headers })
  }
})
