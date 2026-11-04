import { useEffect } from 'react'
import i18n, { useTranslation } from '../i18n'

// Native browser validation normally follows the browser's own language. Keep
// its feedback consistent with the selected interface language instead.
export function LocaleEffects() {
  const { t } = useTranslation()
  useEffect(() => {
    const isField = (value: EventTarget | null): value is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement =>
      value instanceof HTMLInputElement || value instanceof HTMLTextAreaElement || value instanceof HTMLSelectElement
    const clear = (event: Event) => { if (isField(event.target)) event.target.setCustomValidity('') }
    const invalid = (event: Event) => {
      if (!isField(event.target)) return
      const field = event.target
      field.setCustomValidity('')
      const validity = field.validity
      let message = t('Please check this value.')
      if (validity.valueMissing) message = t('Please fill out this field.')
      else if (validity.typeMismatch) message = t('Please enter a valid email address.')
      else if (validity.patternMismatch) message = t('Please use the requested format.')
      else if (validity.tooShort && 'minLength' in field) message = t('Please enter at least {{count}} characters.', { count: field.minLength })
      else if (validity.tooLong && 'maxLength' in field) message = t('Please enter no more than {{count}} characters.', { count: field.maxLength })
      else if (validity.rangeUnderflow && 'min' in field) message = t('Please enter a value of at least {{value}}.', { value: field.min })
      else if (validity.rangeOverflow && 'max' in field) message = t('Please enter a value no greater than {{value}}.', { value: field.max })
      else if (validity.badInput || validity.stepMismatch) message = t('Please enter a valid number.')
      field.setCustomValidity(message)
    }
    const reset = () => document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>('input, textarea, select').forEach(field => field.setCustomValidity(''))
    document.addEventListener('invalid', invalid, true)
    document.addEventListener('input', clear, true)
    document.addEventListener('change', clear, true)
    i18n.on('languageChanged', reset)
    return () => {
      document.removeEventListener('invalid', invalid, true)
      document.removeEventListener('input', clear, true)
      document.removeEventListener('change', clear, true)
      i18n.off('languageChanged', reset)
    }
  }, [t])
  return null
}
