import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Check, Sparkles } from 'lucide-react'
import { LogoMark } from '../App'

export function AuthLayout({ children }: { children: ReactNode }) {
  return <div className="auth-page">
    <section className="auth-story">
      <Link to="/login" className="brand auth-brand"><LogoMark /><span>forma</span></Link>
      <div className="story-copy"><span className="kicker"><Sparkles size={14} />AI-NATIVE PRODUCT STUDIO</span><h1>From “what if”<br />to <em>it works.</em></h1><p>A dedicated AI product team to shape, build, refine, and launch your next idea — with you in the loop.</p></div>
      <div className="story-steps"><span><i><Check size={12} /></i>Describe your product</span><b /><span><i>2</i>Shape it together</span><b /><span><i>3</i>Publish with a click</span></div>
      <small className="story-foot">BUILT FOR FOUNDERS, MAKERS & CURIOUS MINDS</small>
    </section>
    <section className="auth-form-side"><div className="auth-form-wrap">
      <span className="mobile-brand brand"><LogoMark /><span>forma</span></span>
      {children}
    </div><small className="auth-legal">Build something useful, with a verified account.</small></section>
  </div>
}
