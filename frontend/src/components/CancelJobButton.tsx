import { X } from 'lucide-react'

export function CancelJobButton({ cancelling, onCancel }: { cancelling: boolean; onCancel: () => void }) {
  return <button className="button secondary" onClick={onCancel} disabled={cancelling}>
    <X size={14} />{cancelling ? 'Cancelling…' : 'Cancel'}
  </button>
}
