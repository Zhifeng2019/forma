import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CheckCircle2, Eye, EyeOff, Mail, Smartphone } from 'lucide-react'
import { api, setToken } from '../api'
import type { User } from '../types'
import { AuthLayout } from '../components/AuthLayout'

type Challenge = { challenge_id: string; channel: 'email' | 'sms'; destination: string; expires_at: number; resend_after: number }
type Options = { email_available: boolean; sms_available: boolean }
const PENDING_KEY = 'forma_registration'

function pendingRegistration(): (Challenge & { resend_at: number }) | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(PENDING_KEY) || 'null')
    return value && /^[a-f0-9]{32}$/.test(value.challenge_id) && ['email', 'sms'].includes(value.channel)
      && typeof value.destination === 'string' && Number.isFinite(value.expires_at) && Number.isFinite(value.resend_at) ? value : null
  } catch { return null }
}

export function AuthPage({ register = false, onAuth }: { register?: boolean; onAuth: (user: User) => void }) {
  const [name, setName] = useState('')
  const [identity, setIdentity] = useState('')
  const [method, setMethod] = useState<'email' | 'sms'>('email')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [options, setOptions] = useState<Options | null>(null)
  const [challenge, setChallenge] = useState(() => register ? pendingRegistration() : null)
  const [code, setCode] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!register) return
    void api<Options>('/auth/registration-options').then(data => {
      setOptions(data)
      if (!data.email_available && data.sms_available) setMethod('sms')
    }).catch(reason => setError(reason.message))
  }, [register])
  useEffect(() => {
    if (!challenge) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [challenge])
  const remember = (value: Challenge) => {
    const next = { ...value, resend_at: Date.now() + value.resend_after * 1000 }
    sessionStorage.setItem(PENDING_KEY, JSON.stringify(next)); setChallenge(next); setCode(''); setNow(Date.now())
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      if (!register) {
        const result = await api<{ token: string; user: User }>('/auth/login', { method: 'POST', body: JSON.stringify({ identifier: identity, password }) })
        setToken(result.token); onAuth(result.user)
      } else if (challenge) {
        await api('/auth/register/verify', { method: 'POST', body: JSON.stringify({ challenge_id: challenge.challenge_id, code }) })
        sessionStorage.removeItem(PENDING_KEY); setChallenge(null); setCode(''); setSubmitted(true)
      } else {
        const result = await api<Challenge>('/auth/register', { method: 'POST', body: JSON.stringify({ name, password, [method === 'email' ? 'email' : 'phone']: identity }) })
        remember(result); setPassword('')
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const resend = async () => {
    if (!challenge) return
    setBusy(true); setError(''); setNotice('')
    try {
      remember(await api<Challenge>('/auth/register/resend', { method: 'POST', body: JSON.stringify({ challenge_id: challenge.challenge_id }) }))
      setNotice('A new verification code was sent. Use the latest code.')
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }
  const remaining = challenge ? Math.max(0, Math.ceil((challenge.resend_at - now) / 1000)) : 0
  const available = Boolean(options && (method === 'email' ? options.email_available : options.sms_available))
  return <AuthLayout>
      <div className="auth-heading"><span>{register ? 'YOUR STUDIO AWAITS' : 'WELCOME BACK'}</span><h2>{submitted ? 'Awaiting approval' : challenge ? 'Verify your contact' : register ? 'Create your account' : 'Make something great.'}</h2><p>{submitted ? 'Your contact is verified. Your request is now with the administrator.' : challenge ? `Enter the six-digit code sent to ${challenge.destination}.` : register ? 'Verify your email or mobile number, then request administrator approval.' : 'Sign in with your email address or mainland China mobile number.'}</p></div>
      {register && <ol className="registration-steps" aria-label="Registration progress"><li className="complete">1 · Account</li><li className={challenge || submitted ? 'complete' : ''}>2 · Verify</li><li className={submitted ? 'complete' : ''}>3 · Approval</li></ol>}
      {submitted ? <div className="registration-success" role="status"><CheckCircle2 size={30} /><p>You can sign in once an administrator approves your account. Your projects will be available after approval.</p><Link className="button primary" to="/login">Back to sign in<ArrowRight size={16} /></Link></div> : <form onSubmit={submit} className="auth-form">
        {register && !challenge && <div className="registration-method" role="group" aria-label="Registration method"><button type="button" className={method === 'email' ? 'active' : ''} aria-pressed={method === 'email'} disabled={busy || !options?.email_available} onClick={() => { setMethod('email'); setIdentity(''); setError('') }}><Mail size={16} />Email</button><button type="button" className={method === 'sms' ? 'active' : ''} aria-pressed={method === 'sms'} disabled={busy || !options?.sms_available} onClick={() => { setMethod('sms'); setIdentity(''); setError('') }}><Smartphone size={16} />Mobile (+86)</button></div>}
        {challenge ? <>
          <label>Verification code<input value={code} onChange={e => setCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required autoFocus disabled={busy} /></label>
          <p className="verification-help">{now >= challenge.expires_at * 1000 ? 'This code has expired. Request a new code below.' : 'The code expires after 10 minutes. Only the latest code works.'}</p>
        </> : <>
          {register && <label>Full name<input value={name} onChange={e => setName(e.target.value)} placeholder="Alex Morgan" required minLength={2} maxLength={80} autoComplete="name" autoFocus disabled={busy} /></label>}
          <label>{!register ? 'Email or mobile number' : method === 'email' ? 'Email address' : 'Mainland China mobile number'}<input type={register && method === 'email' ? 'email' : 'text'} inputMode={register && method === 'sms' ? 'tel' : 'email'} value={identity} onChange={e => setIdentity(e.target.value)} placeholder={register && method === 'sms' ? '+86 138 0013 8000' : !register ? 'Email or +86 mobile number' : 'you@company.com'} required maxLength={register && method === 'sms' ? 32 : 320} autoComplete={register ? method === 'sms' ? 'tel' : 'email' : 'username'} autoFocus={!register} disabled={busy} /></label>
          <label>Password<div className="password-input"><input type={show ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" required minLength={register ? 8 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} disabled={busy} /><button type="button" onClick={() => setShow(!show)} aria-label="Toggle password visibility">{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
        </>}
        {register && !challenge && options && !available && <div className="form-error">Registration verification is currently unavailable. Please contact the administrator.</div>}
        {error && <div className="form-error" role="alert">{error}</div>}
        {notice && <p className="verification-help" role="status">{notice}</p>}
        <button className="button primary auth-submit" disabled={busy || (register && !challenge && !available)}>{busy ? <span className="spinner" /> : <>{!register ? 'Sign in to Forma' : challenge ? 'Verify and request approval' : 'Send verification code'}<ArrowRight size={17} /></>}</button>
        {challenge && <div className="verification-actions"><button type="button" className="button secondary" disabled={busy || remaining > 0} onClick={resend}>{remaining ? `Resend in ${remaining}s` : 'Resend code'}</button><button type="button" className="button ghost" disabled={busy} onClick={() => { sessionStorage.removeItem(PENDING_KEY); setChallenge(null); setCode(''); setError(''); setNotice('') }}>Use different contact details</button></div>}
      </form>}
      {!register && <p className="auth-switch"><Link to="/forgot-password">Forgot password?</Link></p>}
      {!submitted && <p className="auth-switch">{register ? 'Already have an account?' : 'New to Forma?'} <Link to={register ? '/login' : '/register'}>{register ? 'Sign in' : 'Create an account'}<ArrowRight size={13} /></Link></p>}
  </AuthLayout>
}
