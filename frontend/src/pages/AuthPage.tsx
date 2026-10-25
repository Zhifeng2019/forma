import { FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Check, Eye, EyeOff, Sparkles } from 'lucide-react'
import { api, setToken } from '../api'
import type { User } from '../types'
import { LogoMark } from '../App'

export function AuthPage({ register = false, onAuth }: { register?: boolean; onAuth: (user: User) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState(register ? '' : 'admin@forma.local')
  const [password, setPassword] = useState(register ? '' : 'admin123')
  const [show, setShow] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = await api<{ token: string; user: User }>(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify({ name, email, password }) })
      setToken(result.token); onAuth(result.user)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) } finally { setBusy(false) }
  }
  return <div className="auth-page">
    <section className="auth-story">
      <Link to="/login" className="brand auth-brand"><LogoMark /><span>forma</span></Link>
      <div className="story-copy"><span className="kicker"><Sparkles size={14} />AI-NATIVE PRODUCT STUDIO</span><h1>From “what if”<br />to <em>it works.</em></h1><p>A dedicated AI product team to shape, build, refine, and launch your next idea — with you in the loop.</p></div>
      <div className="story-steps"><span><i><Check size={12} /></i>Describe your product</span><b /><span><i>2</i>Shape it together</span><b /><span><i>3</i>Publish with a click</span></div>
      <small className="story-foot">BUILT FOR FOUNDERS, MAKERS & CURIOUS MINDS</small>
    </section>
    <section className="auth-form-side"><div className="auth-form-wrap">
      <span className="mobile-brand brand"><LogoMark /><span>forma</span></span>
      <div className="auth-heading"><span>{register ? 'YOUR STUDIO AWAITS' : 'WELCOME BACK'}</span><h2>{register ? 'Create your account' : 'Make something great.'}</h2><p>{register ? 'Start turning your ideas into real products.' : 'Sign in to continue building.'}</p></div>
      <form onSubmit={submit} className="auth-form">
        {register && <label>Full name<input value={name} onChange={e => setName(e.target.value)} placeholder="Alex Morgan" required minLength={2} autoFocus /></label>}
        <label>Email address<input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@company.com" required autoFocus={!register} /></label>
        <label>Password<div className="password-input"><input type={show ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" required minLength={register ? 8 : 1} /><button type="button" onClick={() => setShow(!show)} aria-label="Toggle password visibility">{show ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button primary auth-submit" disabled={busy}>{busy ? <span className="spinner" /> : <>{register ? 'Create my studio' : 'Sign in to Forma'}<ArrowRight size={17} /></>}</button>
      </form>
      <p className="auth-switch">{register ? 'Already have an account?' : 'New to Forma?'} <Link to={register ? '/login' : '/register'}>{register ? 'Sign in' : 'Create an account'}<ArrowRight size={13} /></Link></p>
      {!register && <div className="demo-note"><strong>Local demo account</strong><span>admin@forma.local · admin123</span></div>}
    </div><small className="auth-legal">By continuing, you agree to build something useful.</small></section>
  </div>
}
