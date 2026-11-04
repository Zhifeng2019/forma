import { Languages } from 'lucide-react'
import { setLanguage, useTranslation, type Language } from '../i18n'

export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  return <label className="language-switcher">
    <Languages size={16} aria-hidden="true" />
    <span className="sr-only">{t('Language')}</span>
    <select aria-label={t('Language')} value={i18n.resolvedLanguage || 'en'} onChange={event => void setLanguage(event.target.value as Language)}>
      <option value="en" lang="en">English</option>
      <option value="zh-CN" lang="zh-CN">简体中文</option>
    </select>
  </label>
}
