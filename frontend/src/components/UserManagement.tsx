import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Clock3, Trash2, XCircle } from 'lucide-react'
import { api } from '../api'
import type { User } from '../types'

function DeleteUserDialog({ user, busy, error, onCancel, onDelete }: {
  user: User; busy: boolean; error: string; onCancel: () => void; onDelete: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])
  return <dialog ref={dialog} className="modal delete-user-dialog" aria-labelledby="delete-user-title" aria-describedby="delete-user-description" onCancel={event => { event.preventDefault(); if (!busy) onCancel() }}>
    <header><h2 id="delete-user-title">Delete user?</h2></header>
    <p id="delete-user-description">Permanently delete <strong>{user.name}</strong> ({user.email || user.phone}), all projects ({user.project_count || 0} total), hosted apps, files, and personal settings. Active work will stop. This cannot be undone.</p>
    <p>The email or mobile number can be used for a new registration, which will require verification and admin approval again.</p>
    {error && <div className="form-error" role="alert">{error}</div>}
    <footer className="modal-actions"><button type="button" className="button ghost" autoFocus disabled={busy} onClick={onCancel}>Cancel</button><button type="button" className="button danger" disabled={busy} onClick={onDelete}>{busy ? 'Deleting…' : 'Delete user and all data'}</button></footer>
  </dialog>
}

export function UserManagement({ users, currentUser, onChanged }: { users: User[]; currentUser: User; onChanged: () => void }) {
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
    <header><div><h2>Workspace members</h2><p>{pending} pending approval. Only verified applicants appear here.</p></div><div className="member-actions"><label className="pending-filter"><input type="checkbox" checked={pendingOnly} onChange={e => setPendingOnly(e.target.checked)} />Pending only</label><button className="button ghost compact" disabled={busy !== null} onClick={onChanged}>Refresh requests</button></div></header>
    {error && !deleting && <div className="form-error" role="alert">{error}</div>}
    {notice && <div className="admin-notice" role="status">{notice}</div>}
    <div className="users-table"><div className="table-head"><span>Member / verified contact</span><span>Role</span><span>Projects</span><span>Status</span><span>Actions</span></div>
      {users.filter(user => !pendingOnly || user.status === 'pending').map(user => <div className="table-row" key={user.id}>
        <span className="member-cell"><i>{user.name[0].toUpperCase()}</i><span><strong>{user.name}</strong><small>{user.email || user.phone}</small>{user.verified_at && <small className="contact-verified">Verified {new Date(user.verified_at.replace(' ', 'T') + 'Z').toLocaleDateString()}</small>}</span></span>
        <span><button className="role-select" disabled={busy !== null || user.id === currentUser.id || user.status !== 'active'} aria-label={`Change role for ${user.name}`} onClick={() => void change(user, { role: user.role === 'admin' ? 'user' : 'admin' })}>{user.role}</button></span>
        <span>{user.project_count || 0}</span><span className={`user-status ${user.status}`}>{user.status === 'active' ? <CheckCircle2 size={13} /> : user.status === 'pending' ? <Clock3 size={13} /> : <XCircle size={13} />}{user.status === 'pending' ? 'Awaiting approval' : user.status}</span>
        <span className="member-actions">{user.status !== 'deleting' && (user.status === 'pending' || user.status === 'rejected' ? <><button className="button primary compact" disabled={busy !== null} onClick={() => void change(user, { status: 'active' })}>Approve</button>{user.status === 'pending' && <button className="button ghost compact" disabled={busy !== null} onClick={() => void change(user, { status: 'rejected' })}>Reject</button>}</> : <button className="button ghost compact" disabled={busy !== null || user.id === currentUser.id} onClick={() => void change(user, { status: user.status === 'active' ? 'disabled' : 'active' })}>{user.status === 'active' ? 'Disable' : 'Enable'}</button>)}<button className="button ghost compact delete-user-button" disabled={busy !== null || user.id === currentUser.id} aria-label={`Delete ${user.name}`} onClick={() => { setDeleting(user); setError(''); setNotice('') }}><Trash2 size={13} />{user.status === 'deleting' ? 'Retry delete' : 'Delete'}</button></span>
      </div>)}
    </div>
    {pendingOnly && !pending && <p className="no-applicants">No registrations awaiting approval.</p>}
    {deleting && <DeleteUserDialog user={deleting} busy={busy !== null} error={error} onCancel={() => { setDeleting(null); setError('') }} onDelete={() => void remove()} />}
  </section>
}
