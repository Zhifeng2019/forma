import { LanguageSwitcher } from './LanguageSwitcher'
import { useTranslation } from '../i18n'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Check, Sparkles } from 'lucide-react'
import { LogoMark } from '../App'

export function AuthLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  return <div className="auth-page">
    <section className="auth-story">
      <Link to="/login" className="brand auth-brand"><LogoMark /><span>forma</span></Link>
      <div className="story-copy"><span className="kicker"><Sparkles size={14} />{t("AI-NATIVE PRODUCT STUDIO")}</span><h1>{t("From “what if”")}<br />{t("to")} <em>{t("it works.")}</em></h1><p>{t("A dedicated AI product team to shape, build, refine, and launch your next idea — with you in the loop.")}</p></div>
      <div className="story-steps"><span><i><Check size={12} /></i>{t("Describe your product")}</span><b /><span><i>2</i>{t("Shape it together")}</span><b /><span><i>3</i>{t("Publish with a click")}</span></div>
      <small className="story-foot">{t("BUILT FOR FOUNDERS, MAKERS & CURIOUS MINDS")}</small>
    </section>
    <section className="auth-form-side"><div className="auth-language"><LanguageSwitcher /></div><div className="auth-form-wrap">
      <span className="mobile-brand brand"><LogoMark /><span>forma</span></span>
      {children}
    </div><small className="auth-legal">{t("Build something useful, with a verified account.")}</small></section>
  </div>
}
