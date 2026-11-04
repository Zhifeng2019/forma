import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'

export { useTranslation, Trans } from 'react-i18next'
export type Language = 'en' | 'zh-CN'
export const LANGUAGE_KEY = 'forma_language'

export function normalizeLanguage(value: string): Language {
  return /^zh(?:-|$)/i.test(value) ? 'zh-CN' : 'en'
}

function initialLanguage(): Language {
  try {
    const saved = localStorage.getItem(LANGUAGE_KEY)
    if (saved === 'en' || saved === 'zh-CN') return saved
  } catch { /* Storage may be blocked by browser policy. */ }
  return normalizeLanguage(typeof navigator === 'undefined' ? 'en' : navigator.language)
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, 'zh-CN': { translation: zhCN } },
  lng: initialLanguage(), fallbackLng: 'en', supportedLngs: ['en', 'zh-CN'],
  load: 'currentOnly', keySeparator: false, nsSeparator: false,
  interpolation: { escapeValue: false }, // React escapes text and interpolated user values.
  initAsync: false,
})

export const t = i18n.t.bind(i18n)
export const locale = () => i18n.resolvedLanguage === 'zh-CN' ? 'zh-CN' : 'en-US'

function updateDocument() {
  if (typeof document === 'undefined') return
  document.documentElement.lang = i18n.resolvedLanguage || 'en'
  document.title = t('Forma — AI Product Studio')
}
i18n.on('languageChanged', updateDocument)
updateDocument()

export function setLanguage(language: Language) {
  try { localStorage.setItem(LANGUAGE_KEY, language) } catch { /* Switching still works without storage. */ }
  return i18n.changeLanguage(language)
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions) {
  return new Intl.NumberFormat(locale(), options).format(value)
}

export function parseDate(value: string): Date {
  const normalized = value.replace(' ', 'T')
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`)
}

export function formatDateTime(value: string, options?: Intl.DateTimeFormatOptions): string {
  const date = parseDate(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(locale(), options)
}

export function relativeDate(value: string) {
  const date = parseDate(value)
  const elapsed = Math.max(0, Date.now() - date.getTime())
  if (elapsed < 60_000) return t('Just now')
  if (elapsed < 3_600_000) return t('{{count}}m ago', { count: Math.floor(elapsed / 60_000) })
  if (elapsed < 86_400_000) return t('{{count}}h ago', { count: Math.floor(elapsed / 3_600_000) })
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleDateString(locale(), { month: 'short', day: 'numeric' })
}

export default i18n
