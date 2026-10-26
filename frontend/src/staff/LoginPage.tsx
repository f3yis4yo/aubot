import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Bot, LogIn } from 'lucide-react'
import { api, ensureCsrf } from '../api'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/staff'

  return (
    <div className="login-shell">
      <form
        className="login card"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError('')
          try {
            await ensureCsrf()
            await api('/auth/login', { json: { username, password } })
            if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission().catch(() => undefined)
            navigate(from, { replace: true })
          } catch (err) {
            setError((err as Error).message)
          } finally {
            setBusy(false)
          }
        }}
      >
        <div className="brand" style={{ padding: 0 }}>
          <span className="brand-mark">
            <Bot size={18} />
          </span>
          AUBOT Console
        </div>
        <div>
          <h2 style={{ fontSize: 20 }}>Staff sign in</h2>
          <p className="hint">For specialists and the business owner.</p>
        </div>
        <label className="field">
          <span>Username</span>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus />
        </label>
        <label className="field">
          <span>Password</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        {error && <p className="error-text" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy}>
          <LogIn size={16} /> {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
