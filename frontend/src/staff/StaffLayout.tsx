import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Bot, ClipboardCheck, FileText, Gauge, Headset, LogOut, MessageSquare, Settings } from 'lucide-react'
import { api, ensureCsrf } from '../api'
import type { StaffUser } from '../types'
import { useSocket, type PushEvent } from '../useSocket'
import { Ctx } from './staffContext'

export default function StaffLayout() {
  const [user, setUser] = useState<StaffUser | null | undefined>(undefined)
  const [openCases, setOpenCases] = useState(0)
  const listeners = useRef(new Set<(e: PushEvent) => void>())
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    ensureCsrf()
      .then(() => api<StaffUser>('/staff/me'))
      .then(setUser)
      .catch(() => setUser(null))
  }, [])

  const refreshCounts = useCallback(() => {
    api<{ items: unknown[] }>('/staff/escalations?status=queued')
      .then((r) => setOpenCases(r.items.length))
      .catch(() => undefined)
  }, [])
  useEffect(() => {
    if (user) refreshCounts()
  }, [user, refreshCounts])

  const live = useSocket(user ? '/ws/staff/' : null, (e) => {
    if (e.event.startsWith('escalation.')) refreshCounts()
    if (e.event === 'escalation.new' && 'Notification' in window && Notification.permission === 'granted' && document.hidden) {
      new Notification('New AUBOT case', { body: e.payload.trigger_text || e.payload.reference })
    }
    listeners.current.forEach((fn) => fn(e))
  })

  const subscribe = useCallback((fn: (e: PushEvent) => void) => {
    listeners.current.add(fn)
    return () => {
      listeners.current.delete(fn)
    }
  }, [])

  if (user === undefined) return <div className="empty">Loading…</div>
  if (user === null) return <Navigate to="/staff/login" replace state={{ from: location.pathname }} />

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' }).catch(() => undefined)
    navigate('/staff/login')
  }

  const links = [
    { to: '/staff', label: 'Overview', icon: Gauge, end: true },
    { to: '/staff/cases', label: 'Cases', icon: Headset, badge: openCases },
    { to: '/staff/documents', label: 'Documents', icon: FileText },
    { to: '/staff/evaluation', label: 'Evaluation', icon: ClipboardCheck },
    { to: '/staff/settings', label: 'Settings', icon: Settings },
  ]

  return (
    <Ctx.Provider value={{ user, live, openCases, refreshCounts, subscribe }}>
      <div className="staff">
        <nav className="sidebar" aria-label="Staff navigation">
          <div className="brand">
            <span className="brand-mark">
              <Bot size={18} />
            </span>
            AUBOT Console
          </div>
          {links.map(({ to, label, icon: Icon, end, badge }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              <Icon size={18} /> {label}
              {!!badge && <span className="nav-badge" aria-label={`${badge} waiting`}>{badge}</span>}
            </NavLink>
          ))}
          <a className="nav-link" href="/" target="_blank" rel="noreferrer">
            <MessageSquare size={18} /> Customer chat
          </a>
          <div className="sidebar-foot">
            <span className="live">
              <span className="dot" style={{ background: live ? 'var(--good)' : 'var(--text-3)' }} /> {live ? 'Live updates on' : 'Reconnecting…'}
            </span>
            <span>
              {user.name} {user.is_owner && <span className="chip chip-brand">Owner</span>}
            </span>
            <button className="btn btn-sm" onClick={logout}>
              <LogOut size={15} /> Sign out
            </button>
          </div>
        </nav>
        <div className="main">
          <Outlet />
        </div>
      </div>
    </Ctx.Provider>
  )
}
