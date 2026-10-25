import type { ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { Blocks, ChevronDown, CircleUserRound, LayoutGrid, LogOut, Settings, ShieldCheck } from 'lucide-react'
import { clearToken } from '../api'
import type { User } from '../types'
import { LogoMark } from '../App'
import { useState } from 'react'

export function Layout({ user, onUser, children, wide = false }: { user: User; onUser: (user: User | null) => void; children: ReactNode; wide?: boolean }) {
  const [menu, setMenu] = useState(false)
  const navigate = useNavigate()
  const logout = () => { clearToken(); onUser(null); navigate('/login') }
  return <div className="site-shell">
    <header className="site-header">
      <Link to="/" className="brand"><LogoMark /><span>forma</span><em>STUDIO</em></Link>
      <nav className="main-nav">
        <NavLink to="/" end><LayoutGrid size={16} />Projects</NavLink>
        <NavLink to="/settings"><Settings size={16} />Configuration</NavLink>
        {user.role === 'admin' && <NavLink to="/admin"><ShieldCheck size={16} />Admin</NavLink>}
      </nav>
      <div className="account-wrap">
        <button className="account-button" onClick={() => setMenu(!menu)}><span className="avatar">{user.name.slice(0, 1).toUpperCase()}</span><span>{user.name}</span><ChevronDown size={14} /></button>
        {menu && <div className="account-menu"><div><strong>{user.name}</strong><small>{user.email}</small></div><button onClick={() => navigate('/settings')}><CircleUserRound size={16} />Preferences</button><button onClick={logout}><LogOut size={16} />Sign out</button></div>}
      </div>
    </header>
    <main className={wide ? 'site-content wide' : 'site-content'}>{children}</main>
    <footer className="site-footer"><span><Blocks size={13} />Ideas into working products.</span><span>Forma Studio · v1.0</span></footer>
  </div>
}
