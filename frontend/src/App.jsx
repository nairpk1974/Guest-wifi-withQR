import { useState } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { ROLE_LABEL } from './api'
import { useAuth } from './auth'
import Login from './pages/Login'
import Setup from './pages/Setup'
import Dashboard from './pages/Dashboard'
import Register from './pages/Register'
import Visitors from './pages/Visitors'
import Sessions from './pages/Sessions'
import Reports from './pages/Reports'
import Users from './pages/Users'
import Locations from './pages/Locations'
import PortalTexts from './pages/PortalTexts'
import { Logo } from './ui'

const NAV = [
  { to: '/', label: 'Dashboard', roles: ['super_admin', 'reception', 'auditor'], end: true },
  { to: '/register', label: 'Register visitor', roles: ['super_admin', 'reception'] },
  { to: '/visitors', label: 'Visitors & approvals', roles: ['super_admin', 'reception', 'auditor'] },
  { to: '/sessions', label: 'Active sessions', roles: ['super_admin', 'reception', 'auditor'] },
  { to: '/reports', label: 'Reports & audit', roles: ['super_admin', 'reception', 'auditor'] },
  { to: '/users', label: 'Administrators', roles: ['super_admin'], section: 'Administration' },
  { to: '/locations', label: 'Locations & firewalls', roles: ['super_admin'] },
  { to: '/portal-texts', label: 'Portal terms & privacy', roles: ['super_admin'] },
]

export default function App() {
  const { loading, user, stage, logout, can } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  if (loading) return <div className="center muted">Loading…</div>
  if (!user) return <Login />
  if (stage !== 'full') return <Setup />

  const items = NAV.filter(n => can(...n.roles))
  return (
    <div className="shell">
      <aside className={`side ${menuOpen ? 'open' : ''}`}>
        <div className="side-brand"><Logo /><div><b>Bessel Systems</b><span>Guest Wi-Fi</span></div></div>
        <nav onClick={() => setMenuOpen(false)}>
          {items.map(n => (
            <div key={n.to}>
              {n.section && <div className="nav-section">{n.section}</div>}
              <NavLink to={n.to} end={n.end}>{n.label}</NavLink>
            </div>
          ))}
        </nav>
        <div className="side-user">
          <div><b>{user.full_name}</b></div>
          <div className="muted small">{ROLE_LABEL[user.role]}{user.location_code ? ` · ${user.location_code}` : ''}</div>
          <button className="btn ghost sm" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn ghost sm menu-btn" onClick={() => setMenuOpen(o => !o)} aria-label="Menu">☰</button>
          <span className="muted small">Signed in as {user.username}</span>
        </header>
        <div className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            {can('super_admin', 'reception') && <Route path="/register" element={<Register />} />}
            <Route path="/visitors" element={<Visitors />} />
            <Route path="/visitors/:id" element={<Visitors />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/reports" element={<Reports />} />
            {can('super_admin') && <Route path="/users" element={<Users />} />}
            {can('super_admin') && <Route path="/locations" element={<Locations />} />}
            {can('super_admin') && <Route path="/portal-texts" element={<PortalTexts />} />}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  )
}
