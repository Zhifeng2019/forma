import { expect, type APIRequestContext, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

type Registration = { email?: string; phone?: string; name: string; password: string }

export async function verificationCode(challengeId: string): Promise<string> {
  if (!/^[a-f0-9]{32}$/.test(challengeId) || !process.env.FORMA_TEST_DATA_DIR) throw new Error('Missing isolated test mailbox')
  const mailbox = path.join(process.env.FORMA_TEST_DATA_DIR, 'test-deliveries', `${challengeId}.json`)
  let content = ''
  await expect.poll(async () => {
    try { content = await readFile(mailbox, 'utf8'); return Boolean(content) } catch { return false }
  }, { message: 'Waiting for the isolated verification mailbox' }).toBeTruthy()
  return JSON.parse(content).code
}

export async function adminSession(request: APIRequestContext) {
  const response = await request.post('/api/auth/login', { data: { email: 'admin@forma.local', password: 'admin123' } })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).token as string
}

export async function approveContact(request: APIRequestContext, identifier: string) {
  const headers = { Authorization: `Bearer ${await adminSession(request)}` }
  const users = await (await request.get('/api/admin/users', { headers })).json()
  const user = users.find((candidate: { email?: string; phone?: string }) => candidate.email === identifier || candidate.phone === identifier)
  expect(user).toBeTruthy()
  expect((await request.patch(`/api/admin/users/${user.id}`, { headers, data: { status: 'active' } })).ok()).toBeTruthy()
}

export async function registerAccount(request: APIRequestContext, data: Registration) {
  const started = await request.post('/api/auth/register', { data })
  expect(started.ok()).toBeTruthy()
  const { challenge_id } = await started.json()
  const verified = await request.post('/api/auth/register/verify', { data: { challenge_id, code: await verificationCode(challenge_id) } })
  expect(verified.ok()).toBeTruthy()
  const identifier = data.email || data.phone || ''
  await approveContact(request, identifier)
  const login = await request.post('/api/auth/login', { data: { identifier, password: data.password } })
  expect(login.ok()).toBeTruthy()
  return login.json()
}

// Complete the real verification and approval flow after an existing test fills the signup form.
export async function finishRegistration(page: Page) {
  const identifier = await page.getByLabel('Email address').inputValue()
  const password = await page.getByLabel('Password', { exact: true }).inputValue()
  const response = page.waitForResponse(response => response.url().endsWith('/api/auth/register') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Send verification code' }).click()
  const { challenge_id } = await (await response).json()
  await page.getByLabel('Verification code', { exact: true }).fill(await verificationCode(challenge_id))
  await page.getByRole('button', { name: 'Verify and request approval' }).click()
  await expect(page.getByRole('heading', { name: 'Awaiting approval' })).toBeVisible()
  await approveContact(page.request, identifier)
  await page.getByRole('link', { name: 'Back to sign in' }).click()
  await page.getByLabel('Email or mobile number').fill(identifier)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in to Forma' }).click()
  await expect(page).toHaveURL('/')
}
