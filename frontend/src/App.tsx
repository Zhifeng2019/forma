import { useTranslation } from './i18n'
import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken } from './api'
import { studioPath } from './paths'
import type { User } from './types'
import { AuthPage } from './pages/AuthPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { Dashboard } from './pages/Dashboard'
import { Builder } from './pages/Builder'
import { SettingsPage } from './pages/SettingsPage'
import { AdminPage } from './pages/AdminPage'

export default function App() {
  const { t } = useTranslation()
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(Boolean(getToken()))
  useEffect(() => {
    if (!getToken()) return
    api<User>('/me').then(setUser).catch(() => undefined).finally(() => setLoading(false))
  }, [])
  if (loading) return <div className="app-loading"><LogoMark /><span>{t("Opening your studio…")}</span></div>
  return <Routes>
    <Route path="/login" element={user ? <Navigate to="/" /> : <AuthPage key="login" onAuth={setUser} /> } />
    <Route path="/register" element={user ? <Navigate to="/" /> : <AuthPage key="register" register onAuth={setUser} />} />
    <Route path="/forgot-password" element={user ? <Navigate to="/" /> : <ForgotPasswordPage />} />
    <Route path="/" element={user ? <Dashboard user={user} onUser={setUser} /> : <Navigate to="/login" />} />
    <Route path="/projects/:id" element={user ? <Builder user={user} onUser={setUser} /> : <Navigate to="/login" />} />
    <Route path="/settings" element={user ? <SettingsPage user={user} onUser={setUser} /> : <Navigate to="/login" />} />
    <Route path="/admin" element={user?.role === 'admin' ? <AdminPage user={user} onUser={setUser} /> : <Navigate to="/" />} />
    <Route path="*" element={<Navigate to="/" />} />
  </Routes>
}

export function LogoMark() {
  return <img className="logo-mark" src={studioPath('forma.svg')} alt="" aria-hidden="true" />
}
