import { test, expect } from '@playwright/test'

test('plan feedback stays in review until the user starts the first build', async ({ page }) => {
  await page.goto('/register')
  await page.getByLabel('Full name').fill('Plan Reviewer')
  await page.getByLabel('Email address').fill(`plan-review-${Date.now()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill('password123')
  await page.getByRole('button', { name: 'Create my studio' }).click()
  await expect(page).toHaveURL('/')
  const token = await page.evaluate(() => localStorage.getItem('forma_token'))
  const headers = { Authorization: `Bearer ${token}` }
  let projectId = ''
  try {
    await page.getByRole('button', { name: 'New application' }).click()
    await page.getByLabel('Application name').fill('Invoice Review')
    await page.getByLabel('Tell us about your idea').fill('A personal invoice list with a clear approval trail.')
    await page.locator('.source-format-options label').filter({ hasText: 'Single file' }).click()
    await page.locator('.architecture-options label').filter({ hasText: 'Frontend only' }).click()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page).toHaveURL(/\/projects\/[a-f0-9]{32}/)
    projectId = page.url().split('/').pop() || ''
    await page.getByRole('button', { name: 'Approve design' }).click()
    await expect(page.getByRole('button', { name: 'Start building' })).toBeEnabled()
    await page.getByRole('button', { name: 'Start building' }).click()
    await expect(page.getByRole('button', { name: 'Build phase 1' })).toBeEnabled()
    await expect(page.locator('.documents-view nav button.selected, .documents-view nav button.active')).toContainText('plan.md')
    await expect(page.locator('.approval-bar')).toContainText('Feedback revises it')
    const feedback = 'Phase 1 must show invoice currency without conversion.'
    await page.getByPlaceholder('Ask a question or request a change…').fill(feedback)
    await page.locator('.send-button').click()
    await expect(page.locator('.markdown-body')).toContainText(feedback)
    await expect(page.getByRole('button', { name: 'Build phase 1' })).toBeEnabled()
    let project = await (await page.request.get(`/api/projects/${projectId}`, { headers })).json()
    expect(project.current_version).toBe(0)
    expect(project.versions).toHaveLength(0)
    await page.getByRole('button', { name: 'Build phase 1' }).click()
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
    await expect(page.frameLocator('iframe').getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
    project = await (await page.request.get(`/api/projects/${projectId}`, { headers })).json()
    expect(project.current_version).toBe(1)
    const recorded = await (await page.request.get(`/api/projects/${projectId}/versions/1/context`, { headers })).json()
    expect(recorded.recorded).toBe(true)
    expect(recorded.context.documents['plan.md'].content).toContain(feedback)
    expect(Object.keys(recorded.context.documents).sort()).toEqual(['design.md', 'plan.md', 'product.md'])
  } finally {
    if (projectId) await page.request.delete(`/api/projects/${projectId}`, { headers })
  }
})
