import { systemText, statusLabel } from '../systemMessages'
import { useTranslation, formatDateTime } from '../i18n'
import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Clock3, Trash2, XCircle } from 'lucide-react'
import { api } from '../api'
import type { User } from '../types'

function DeleteUserDialog({ user, busy, error, onCancel, onDelete }: {
  user: User; busy: boolean; error: string; onCancel: () => void; onDelete: () => void
}) {
  const { t } = useTranslation()
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} className="modal delete-user-dialog" aria-labelledby="delete-user-title" aria-describedby="delete-user-description" onCancel={event => { event.preventDefault(); if (!busy) onCancel() }}>
    <header><h2 id="delete-user-title">{t("Delete user?")}</h2></header>
    <p id="delete-user-description">{t("Permanently delete {{name}} ({{contact}}), all projects ({{count}} total), hosted apps, files, and personal settings. Active work will stop. This cannot be undone.", { name: user.name, contact: user.email || user.phone, count: user.project_count || 0 })}</p>
    <p>{t("The email or mobile number can be used for a new registration, which will require verification and admin approval again.")}</p>
    {error && <div className="form-error" role="alert">{systemText(error)}</div>}
    <footer className="modal-actions"><button type="button" className="button ghost" autoFocus disabled={busy} onClick={onCancel}>{t("Cancel")}</button><button type="button" className="button danger" disabled={busy} onClick={onDelete}>{busy ? t("Deleting…") : t("Delete user and all data")}</button></footer>
  </dialog>
}

export function UserManagement({ users, currentUser, onChanged }: { users: User[]; currentUser: User; onChanged: () => void }) {
  const { t } = useTranslation()
  const [pendingOnly, setPendingOnly] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [deleting, setDeleting] = useState<User | null>(null)
  const remove = async () => {
    if (!deleting) return
    setBusy(deleting.id); setError(''); setNotice('')
    try {
      await api(`/admin/users/${deleting.id}`, { method: 'DELETE' })
      setNotice(`${deleting.name} and all their data were deleted. Their contact can be registered again.`)
      setDeleting(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(null); onChanged() }
  }
  const change = async (user: User, values: { status?: User['status']; role?: User['role'] }) => {
    setBusy(user.id); setError(''); setNotice('')
    try {
      await api(`/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify(values) })
      setNotice(values.status === 'active' && ['pending', 'rejected'].includes(user.status || '') ? `${user.name} is approved and can now sign in.` : values.status === 'rejected' ? `${user.name}'s registration was rejected.` : 'Account updated.')
      onChanged()
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(null) }
  }
  const pending = users.filter(user => user.status === 'pending').length
  return <section className="admin-panel user-management">
    <header><div><h2>{t("Workspace members")}</h2><p>{t("{{count}} pending approval. Only verified applicants appear here.", { count: pending })}</p></div><div className="member-actions"><label className="pending-filter"><input type="checkbox" checked={pendingOnly} onChange={e => setPendingOnly(e.target.checked)} />{t("Pending only")}</label><button className="button ghost compact" disabled={busy !== null} onClick={onChanged}>{t("Refresh requests")}</button></div></header>
    {error && !deleting && <div className="form-error" role="alert">{systemText(error)}</div>}
    {notice && <div className="admin-notice" role="status">{systemText(notice)}</div>}
    <div className="users-table"><div className="table-head"><span>{t("Member / verified contact")}</span><span>{t("Role")}</span><span>{t("Projects")}</span><span>{t("Status")}</span><span>{t("Actions")}</span></div>
      {users.filter(user => !pendingOnly || user.status === 'pending').map(user => <div className="table-row" key={user.id}>
        <span className="member-cell"><i>{user.name[0].toUpperCase()}</i><span><strong>{user.name}</strong><small>{user.email || user.phone}</small>{user.verified_at && <small className="contact-verified">{t("Verified {{date}}", { date: formatDateTime(user.verified_at, { year: "numeric", month: "short", day: "numeric" }) })}</small>}</span></span>
        <span><button className="role-select" disabled={busy !== null || user.id === currentUser.id || user.status !== 'active'} aria-label={t("Change role for {{name}}", { name: user.name })} onClick={() => void change(user, { role: user.role === 'admin' ? 'user' : 'admin' })}>{statusLabel(user.role)}</button></span>
        <span>{user.project_count || 0}</span><span className={`user-status ${user.status}`}>{user.status === 'active' ? <CheckCircle2 size={13} /> : user.status === 'pending' ? <Clock3 size={13} /> : <XCircle size={13} />}{user.status === 'pending' ? t("Awaiting approval") : statusLabel(user.status || "")}</span>
        <span className="member-actions">{user.status !== 'deleting' && (user.status === 'pending' || user.status === 'rejected' ? <><button className="button primary compact" disabled={busy !== null} onClick={() => void change(user, { status: 'active' })}>{t("Approve")}</button>{user.status === 'pending' && <button className="button ghost compact" disabled={busy !== null} onClick={() => void change(user, { status: 'rejected' })}>{t("Reject")}</button>}</> : <button className="button ghost compact" disabled={busy !== null || user.id === currentUser.id} onClick={() => void change(user, { status: user.status === 'active' ? 'disabled' : 'active' })}>{user.status === 'active' ? t("Disable") : t("Enable")}</button>)}<button className="button ghost compact delete-user-button" disabled={busy !== null || user.id === currentUser.id} aria-label={t("Delete {{name}}", { name: user.name })} onClick={() => { setDeleting(user); setError(''); setNotice('') }}><Trash2 size={13} />{user.status === 'deleting' ? t("Retry delete") : t("Delete")}</button></span>
      </div>)}
    </div>
    {pendingOnly && !pending && <p className="no-applicants">{t("No registrations awaiting approval.")}</p>}
    {deleting && <DeleteUserDialog user={deleting} busy={busy !== null} error={systemText(error)} onCancel={() => { setDeleting(null); setError('') }} onDelete={() => void remove()} />}
  </section>
}
