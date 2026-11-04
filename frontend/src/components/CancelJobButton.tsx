import { useTranslation } from '../i18n'
import { X } from 'lucide-react'

export function CancelJobButton({ cancelling, onCancel }: { cancelling: boolean; onCancel: () => void }) {
  const { t } = useTranslation()
  return <button className="button secondary" onClick={onCancel} disabled={cancelling}>
    <X size={14} />{cancelling ? t("Cancelling…") : t("Cancel")}
  </button>
}
