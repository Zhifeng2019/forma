import { registerAccount } from './auth-helpers'
import { test, expect } from '@playwright/test'

test('questions leave the preview intact and a subsequent change creates a new version', async ({ page }) => {
  const account = await registerAccount(page.request, {
    email: `conversation-${Date.now()}@example.com`, name: 'Conversation Owner', password: 'password123',
  })
  const headers = { Authorization: `Bearer ${account.token}` }
  let projectId = ''
  try {
    let response = await page.request.post('/api/projects', { headers, data: {
      name: 'Conversation Preview', brief: 'A personal focus timer with a weekly overview.',
      backend_mode: 'static', source_format: 'single-file', auto_mode: false,
    } })
    expect(response.ok()).toBeTruthy()
    projectId = (await response.json()).id
    for (let step = 0; step < 3; step++) {
      response = await page.request.post(`/api/projects/${projectId}/advance`, { headers, data: {} })
      expect(response.ok()).toBeTruthy()
    }
    const before = await response.json()
    expect(before.current_version).toBe(1)
    await page.goto('/login')
    await page.evaluate(token => localStorage.setItem('forma_token', token), account.token)
    await page.goto(`/projects/${projectId}`)
    const preview = page.frameLocator('iframe')
    await expect(preview.getByRole('heading', { name: 'Make good work feel effortless.' })).toBeVisible()
    const previewUrl = await page.locator('iframe').getAttribute('src')
    await preview.locator('body').evaluate(body => body.setAttribute('data-conversation-test', 'unchanged'))

    // Keep the request pending long enough to inspect the optimistic status text.
    await page.route(`**/api/projects/${projectId}/messages`, async route => {
      await new Promise(resolve => setTimeout(resolve, 500))
      await route.fulfill({ response: await route.fetch() })
    })
    await page.getByPlaceholder('Ask a question or request a change…').fill('What are the admin login credentials?')
    await page.locator('.send-button').click()
    await expect(page.locator('.thinking')).toContainText('Responding to your message…')
    await expect(page.locator('.chat-message.agent').last()).toContainText('No changes were made.')
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
    await expect(page.locator('iframe')).toHaveAttribute('src', previewUrl!)
    await expect(preview.locator('body')).toHaveAttribute('data-conversation-test', 'unchanged')
    const answered = await (await page.request.get(`/api/projects/${projectId}`, { headers })).json()
    expect(answered.current_version).toBe(1)
    expect(answered.phase_index).toBe(before.phase_index)
    expect(answered.artifacts).toEqual(before.artifacts)
    expect(answered.versions).toEqual(before.versions)
    expect(answered.messages.at(-1).kind).toBe('answer')

    await page.unroute(`**/api/projects/${projectId}/messages`)
    await page.getByPlaceholder('Ask a question or request a change…').fill('Make the primary action more prominent.')
    await page.locator('.send-button').click()
    await expect.poll(async () => (await (await page.request.get(`/api/projects/${projectId}`, { headers })).json()).current_version).toBe(2)
    await expect(page.getByRole('button', { name: 'Approve phase 1' })).toBeEnabled()
  } finally {
    if (projectId) await page.request.delete(`/api/projects/${projectId}`, { headers })
  }
})
