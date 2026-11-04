import { afterEach, expect, it, vi } from 'vitest'
import { apiPath, studioPath } from './paths'

afterEach(() => vi.unstubAllEnvs())

it.each(['/', '/forma/'])('keeps navigation, assets, and authenticated API requests under %s', base => {
  vi.stubEnv('BASE_URL', base)
  expect(studioPath('/login')).toBe(`${base}login`)
  expect(studioPath('forma.svg')).toBe(`${base}forma.svg`)
  expect(apiPath('/auth/login')).toBe(`${base}api/auth/login`)
  expect(apiPath('/projects/id/events?follow=true')).toBe(`${base}api/projects/id/events?follow=true`)
  expect(apiPath('/projects/id/package?version=2')).toBe(`${base}api/projects/id/package?version=2`)
  expect(apiPath('/projects/id/verification/evidence?path=report.png')).toBe(`${base}api/projects/id/verification/evidence?path=report.png`)
})
