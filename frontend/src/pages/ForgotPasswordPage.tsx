import { type FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, Eye, EyeOff, Mail, Smartphone } from 'lucide-react'
import { api, clearToken } from '../api'
import { AuthLayout } from '../components/AuthLayout'

type Challenge = { challenge_id: string; channel: 'email' | 'sms'; destination: string; expires_at: number; resend_after: number }
type SavedChallenge = Challenge & { resend_at: number }
type Options = { email_available: boolean; sms_available: boolean }
const STORAGE_KEY = 'forma_password_reset'
const deliveryNotice = 'If this contact has an account, a code will be sent. Check your inbox or messages, including spam.'

function savedChallenge(): SavedChallenge | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
    return value && /^[a-f0-9]{32}$/.test(value.challenge_id) && ['email', 'sms'].includes(value.channel)
      && typeof value.destination === 'string' && Number.isFinite(value.expires_at) && Number.isFinite(value.resend_at)
      && value.expires_at * 1000 + 86400000 > Date.now() ? value : null
  } catch { return null }
}

export function ForgotPasswordPage() {
  const [options, setOptions] = useState<Options | null>(null)
  const [method, setMethod] = useState<'email' | 'sms'>('email')
  const [identity, setIdentity] = useState('')
  const [challenge, setChallenge] = useState(savedChallenge)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [complete, setComplete] = useState(false)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    void api<Options>('/auth/password-reset/options').then(data => {
      setOptions(data)
      if (!data.email_available && data.sms_available) setMethod('sms')
    }).catch(reason => setError(reason.message))
  }, [])
  useEffect(() => {
    if (!challenge) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [challenge])
  const remember = (value: Challenge) => {
    const next = { ...value, resend_at: Date.now() + value.resend_after * 1000 }
    // Store only the public challenge; passwords and codes stay in form state.
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    setChallenge(next); setCode(''); setNow(Date.now())
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setNotice('')
    if (challenge && password !== confirmation) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      if (challenge) {
        await api('/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify({ challenge_id: challenge.challenge_id, code, password }) })
        sessionStorage.removeItem(STORAGE_KEY); clearToken()
        setChallenge(null); setCode(''); setPassword(''); setConfirmation(''); setComplete(true)
      } else {
        remember(await api<Challenge>('/auth/password-reset', { method: 'POST', body: JSON.stringify({ [method === 'email' ? 'email' : 'phone']: identity }) }))
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const resend = async () => {
    if (!challenge) return
    setBusy(true); setError(''); setNotice('')
    try {
      remember(await api<Challenge>('/auth/password-reset/resend', { method: 'POST', body: JSON.stringify({ challenge_id: challenge.challenge_id }) }))
      setNotice(deliveryNotice + ' Use the latest code.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const remaining = challenge ? Math.max(0, Math.ceil((challenge.resend_at - now) / 1000)) : 0
  const expired = Boolean(challenge && now >= challenge.expires_at * 1000)
  const available = Boolean(options && (method === 'email' ? options.email_available : options.sms_available))
  return <AuthLayout>
    <div className="auth-heading"><span>ACCOUNT RECOVERY</span><h2>{complete ? 'Password updated' : challenge ? 'Set a new password' : 'Forgot your password?'}</h2><p>{complete ? 'Your new password is ready. Previous sessions have been signed out.' : challenge ? `Reset request for ${challenge.destination}. ${deliveryNotice}` : 'Enter the email address or mainland China mobile number registered to your account.'}</p></div>
    {complete ? <div className="registration-success" role="status"><CheckCircle2 size={30} /><p>Sign in with your new password. Accounts awaiting approval or disabled by an administrator still need administrator approval or reactivation.</p><Link to="/login" className="button primary">Back to sign in<ArrowRight size={16} /></Link></div> : <form className="auth-form" onSubmit={submit}>
      {!challenge ? <>
        <div className="registration-method" role="group" aria-label="Password reset method">
          <button type="button" className={method === 'email' ? 'active' : ''} aria-pressed={method === 'email'} disabled={busy || !options?.email_available} onClick={() => { setMethod('email'); setIdentity(''); setError('') }}><Mail size={16} />Email</button>
          <button type="button" className={method === 'sms' ? 'active' : ''} aria-pressed={method === 'sms'} disabled={busy || !options?.sms_available} onClick={() => { setMethod('sms'); setIdentity(''); setError('') }}><Smartphone size={16} />Mobile (+86)</button>
        </div>
        <label>{method === 'email' ? 'Email address' : 'Mainland China mobile number'}<input type={method === 'email' ? 'email' : 'tel'} value={identity} onChange={event => setIdentity(event.target.value)} placeholder={method === 'email' ? 'you@company.com' : '+86 138 0013 8000'} autoComplete={method === 'email' ? 'email' : 'tel'} maxLength={method === 'email' ? 320 : 32} required autoFocus disabled={busy} /></label>
        {options && !available && <div className="form-error" role="alert">Password reset is currently unavailable. Please contact the administrator.</div>}
      </> : <>
        <label>Verification code<input value={code} onChange={event => setCode(event.target.value.replace(/[^0-9]/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required autoFocus disabled={busy} /></label>
        <p className="verification-help">{expired ? 'This code has expired. Request a new code below.' : 'The code expires after 10 minutes. Only the latest code works.'}</p>
        <label>New password<div className="password-input"><input type={show ? 'text' : 'password'} value={password} onChange={event => setPassword(event.target.value)} placeholder="At least 8 characters" minLength={8} maxLength={128} autoComplete="new-password" required disabled={busy} /><button type="button" onClick={() => setShow(!show)} aria-label="Toggle password visibility">{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
        <label>Confirm new password<input type={show ? 'text' : 'password'} value={confirmation} onChange={event => setConfirmation(event.target.value)} minLength={8} maxLength={128} autoComplete="new-password" required disabled={busy} /></label>
      </>}
      {error && <div className="form-error" role="alert">{error}</div>}
      {notice && <p className="verification-help" role="status">{notice}</p>}
      <button className="button primary auth-submit" disabled={busy || expired || (!challenge && !available)}>{busy ? <span className="spinner" /> : <>{challenge ? 'Reset password' : 'Send reset code'}<ArrowRight size={17} /></>}</button>
      {challenge && <div className="verification-actions"><button type="button" className="button secondary" disabled={busy || remaining > 0} onClick={resend}>{remaining ? `Resend in ${remaining}s` : 'Resend code'}</button><button type="button" className="button ghost" disabled={busy} onClick={() => { sessionStorage.removeItem(STORAGE_KEY); setChallenge(null); setCode(''); setPassword(''); setConfirmation(''); setError(''); setNotice('') }}>Start over</button></div>}
    </form>}
    {!complete && <p className="auth-switch"><Link to="/login">Back to sign in<ArrowRight size={13} /></Link></p>}
  </AuthLayout>
}
