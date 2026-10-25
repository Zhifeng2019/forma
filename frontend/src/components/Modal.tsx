import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export function Modal({ title, eyebrow, children, onClose, className = '' }: { title: string; eyebrow?: string; children: ReactNode; onClose: () => void; className?: string }) {
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><section className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title}><header><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}<h2>{title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close"><X size={19} /></button></header>{children}</section></div>
}
