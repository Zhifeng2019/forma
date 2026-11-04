import { afterEach, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import i18n, { formatDateTime, formatNumber, normalizeLanguage, t } from './i18n'
import { statusLabel, systemText } from './systemMessages'
import en from './locales/en.json'
import zh from './locales/zh-CN.json'

afterEach(async () => { await i18n.changeLanguage('en') })

it('provides matching nonempty catalogs and preserves interpolation parameters', () => {
  expect(Object.keys(zh).sort()).toEqual(Object.keys(en).sort())
  const parameters = (value: string) => [...value.matchAll(/\{\{([^}]+)\}\}/g)].map(match => match[1]).sort()
  for (const key of Object.keys(en) as (keyof typeof en)[]) {
    expect(zh[key].trim(), key).not.toBe('')
    expect(parameters(zh[key]), key).toEqual(parameters(en[key]))
  }
})

it('selects Simplified Chinese for Chinese locales and falls back to English', () => {
  expect(normalizeLanguage('zh-CN')).toBe('zh-CN')
  expect(normalizeLanguage('zh-Hans')).toBe('zh-CN')
  expect(normalizeLanguage('en-GB')).toBe('en')
  expect(normalizeLanguage('fr-FR')).toBe('en')
})

it('handles plurals in English and Chinese without exposing translation keys', async () => {
  await i18n.changeLanguage('en')
  expect(t('{{count}} application', { count: 1 })).toBe('1 application')
  expect(t('{{count}} application', { count: 2 })).toBe('2 applications')
  expect(t('Each publish includes {{count}} hour of hosting', { count: 2 })).toBe('Each publish includes 2 hours of hosting.')
  await i18n.changeLanguage('zh-CN')
  expect(t('{{count}} application', { count: 2 })).toBe('2 个应用')
  expect(t('Each publish includes {{count}} hour of hosting', { count: 1 })).toBe('每次发布包含 1 小时托管。')
})

it('localizes known server messages and preserves arbitrary diagnostic content', async () => {
  await i18n.changeLanguage('zh-CN')
  expect(systemText('Email, mobile number, or password is incorrect')).toBe('邮箱、手机号或密码不正确')
  expect(systemText('Wait 45 seconds before requesting another code.')).toBe('请等待 45 秒后再次获取验证码。')
  expect(systemText('Value error, Enter an 11-digit mainland China mobile number (+86)')).toContain('11 位中国大陆手机号')
  expect(systemText('String should have at least 8 characters\nThe passwords do not match.')).toBe('请至少输入 8 个字符。\n两次输入的密码不一致。')
  expect(systemText('Phase 2 is implemented and the preview has been updated.')).toBe('第 2 阶段已完成，预览已更新。')
  expect(systemText('Version 3 now uses static. Your phase and published release are unchanged.')).toBe('版本 3 已改用仅前端架构，当前阶段和已发布版本保持不变。')
  expect(statusLabel('pending')).toBe('待审核')
  expect(statusLabel('future_status')).toBe('future_status')
  expect(systemText('UnknownProviderError: model foo-v2')).toBe('UnknownProviderError: model foo-v2')
})

it('keeps interpolated account and project text escaped by React', async () => {
  await i18n.changeLanguage('zh-CN')
  const name = '<img src=x onerror=alert(1)>'
  const html = renderToStaticMarkup(createElement('span', null, t('Delete {{name}}', { name })))
  expect(html).toContain('&lt;img')
  expect(html).not.toContain('<img')
})

it('formats dates and prices using the selected language and handles UTC offsets', async () => {
  await i18n.changeLanguage('en')
  expect(formatNumber(1234.5)).toBe('1,234.5')
  const options: Intl.DateTimeFormatOptions = { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }
  expect(formatDateTime('2026-11-04 08:00:00', options)).toBe('November 4, 2026')
  await i18n.changeLanguage('zh-CN')
  expect(formatDateTime('2026-11-04T16:00:00+08:00', options)).toBe('2026年11月4日')
  expect(formatDateTime('invalid')).toBe('—')
})
