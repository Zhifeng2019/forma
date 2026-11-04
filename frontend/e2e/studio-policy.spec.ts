import { test, expect } from '@playwright/test'

test('administrators control model access, project quotas, and hosting periods', async ({ page, browser }) => {
  const adminResponse = await page.request.post('/api/auth/login', { data: { email: 'admin@forma.local', password: 'admin123' } })
  expect(adminResponse.ok()).toBeTruthy()
  const admin = await adminResponse.json()
  const adminHeaders = { Authorization: `Bearer ${admin.token}` }
  const original = await (await page.request.get('/api/policy', { headers: adminHeaders })).json()
  const registration = await page.request.post('/api/auth/register', { data: { email: `policy-ui-${Date.now()}@example.com`, name: 'Policy Member', password: 'password123' } })
  const user = await registration.json()
  const userHeaders = { Authorization: `Bearer ${user.token}` }
  let projectId = ''
  let privateId: number | null = null
  let sharedId: number | null = null
  let memberContext: Awaited<ReturnType<typeof browser.newContext>> | null = null
  try {
    await page.addInitScript(token => localStorage.setItem('forma_token', token), admin.token)
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: 'Studio policy' })).toBeVisible()
    await page.getByLabel('Projects per user').fill('1')
    await page.getByLabel('Hosting period (hours)').fill('8760')
    await page.getByRole('button', { name: 'Save policy' }).click()
    await expect(page.getByText('Studio policy saved.')).toBeVisible()
    await page.reload()
    await expect(page.getByLabel('Hosting period (hours)')).toHaveValue('8760')
    await expect(page.getByLabel('Projects per user')).toHaveValue('1')
    await page.screenshot({ path: '/tmp/forma-policy-admin.png', fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: '/tmp/forma-policy-admin-mobile.png', fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    await page.setViewportSize({ width: 1440, height: 1000 })

    memberContext = await browser.newContext({ baseURL: new URL(page.url()).origin })
    await memberContext.addInitScript(token => localStorage.setItem('forma_token', token), user.token)
    const member = await memberContext.newPage()
    await member.goto('/settings')
    await member.getByRole('button', { name: 'Add private provider' }).click()
    await member.getByLabel('Provider name').fill('My private engine')
    await member.getByLabel('Base URL').fill('https://private.example/v1')
    await member.getByLabel('Model', { exact: true }).fill('private-model')
    await member.getByLabel('API key').fill('secret-not-returned')
    await member.getByRole('button', { name: 'Connect provider' }).click()
    await expect(member.getByRole('dialog')).toHaveCount(0)
    await member.locator('.engine-options label').filter({ hasText: 'My private engine' }).click()
    await member.getByRole('button', { name: 'Save preferences' }).click()
    await expect(member.getByText('Preferences saved')).toBeVisible()
    privateId = (await (await member.request.get('/api/preferences', { headers: userHeaders })).json()).provider_id
    // Use the offline engine to exercise project and hosting flows without external API calls.
    await member.locator('.engine-options label').filter({ hasText: 'Forma Local' }).click()
    await member.getByRole('button', { name: 'Save preferences' }).click()
    await expect(member.getByText('Preferences saved')).toBeVisible()
    await member.goto('/')
    await expect(member.getByText('0 / 1 applications')).toBeVisible()
    const created = await member.request.post('/api/projects', { headers: userHeaders, data: { name: 'Quota app', brief: 'A static personal checklist for daily tasks.', backend_mode: 'static' } })
    expect(created.ok()).toBeTruthy()
    projectId = (await created.json()).id
    await member.reload()
    await expect(member.getByRole('button', { name: 'New application' })).toBeDisabled()
    await expect(member.getByText('Project limit reached (1). Delete a project before creating another.')).toBeVisible()
    for (let step = 0; step < 3; step++) {
      const advance = await member.request.post(`/api/projects/${projectId}/advance`, { headers: userHeaders, data: {} })
      expect(advance.ok()).toBeTruthy()
    }
    await member.goto(`/projects/${projectId}`)
    await member.getByRole('button', { name: 'Publish', exact: true }).click()
    await expect(member.getByText('Each publish includes 8760 hours of hosting.')).toBeVisible()
    await member.getByRole('button', { name: 'Publish application' }).click()
    await expect(member.getByRole('button', { name: 'Renew hosting' })).toBeVisible()
    await expect(member.locator('.hosting-notice')).toContainText('Hosting expires')
    await member.getByRole('button', { name: 'Renew hosting' }).click()
    await expect(member.getByRole('button', { name: 'Renew hosting' })).toBeEnabled()

    const provider = await page.request.post('/api/providers', { headers: adminHeaders, data: { name: 'Managed engine', base_url: 'https://shared.example/v1', model: 'shared-model', api_key: 'shared-secret' } })
    sharedId = (await provider.json()).id
    await page.reload()
    await page.getByLabel('Global generation engine').selectOption(String(sharedId))
    await page.getByLabel('Allow users to configure and choose models').uncheck()
    await page.getByRole('button', { name: 'Save policy' }).click()
    await expect(page.getByText('Studio policy saved.')).toBeVisible()
    await member.goto('/settings')
    await expect(member.locator('.managed-engine').getByText('Managed engine', { exact: true })).toBeVisible()
    await expect(member.getByRole('button', { name: 'Add private provider' })).toHaveCount(0)
    await expect(member.getByRole('radio')).toHaveCount(0)
    await member.getByRole('button', { name: 'Save preferences' }).click()
    await expect(member.getByText('Preferences saved')).toBeVisible()
    await member.screenshot({ path: '/tmp/forma-policy-managed.png', fullPage: true })
  } finally {
    await page.request.put('/api/admin/policy', { headers: adminHeaders, data: original })
    if (privateId) await page.request.delete(`/api/providers/${privateId}`, { headers: userHeaders })
    if (sharedId) await page.request.delete(`/api/providers/${sharedId}`, { headers: adminHeaders })
    if (projectId) await page.request.delete(`/api/projects/${projectId}`, { headers: userHeaders })
    await memberContext?.close()
  }
})
