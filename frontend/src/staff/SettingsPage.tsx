import { useEffect, useState } from 'react'
import { ExternalLink, Save } from 'lucide-react'
import { api } from '../api'
import type { ProfileSettings } from '../types'
import { useStaff } from './staffContext'

type Editable = Omit<ProfileSettings, 'tone_choices' | 'voice_choices' | 'updated_at'>

export default function SettingsPage() {
  const { user } = useStaff()
  const [data, setData] = useState<ProfileSettings | null>(null)
  const [form, setForm] = useState<Editable | null>(null)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api<ProfileSettings>('/staff/settings')
      .then((d) => {
        setData(d)
        const { tone_choices: _t, voice_choices: _v, updated_at: _u, ...rest } = d
        setForm(rest)
      })
      .catch((e) => setError(e.message))
  }, [])

  if (!data || !form) return error ? <p className="error-text">{error}</p> : <p className="empty">Loading settings…</p>
  const readOnly = !user.is_owner
  const bind = (k: keyof Editable) => ({
    value: form[k],
    disabled: readOnly,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setForm({ ...form, [k]: e.target.value }),
  })

  return (
    <>
      <div className="page-head">
        <h2>Settings</h2>
        <span className="hint">{readOnly ? 'Only the business owner can change these.' : 'Changes apply to new conversations immediately; no retraining needed.'}</span>
      </div>
      <form
        className="card panel"
        onSubmit={async (e) => {
          e.preventDefault()
          setSaving(true)
          setError('')
          setMsg('')
          try {
            await api('/staff/settings', { method: 'PUT', json: form })
            setMsg('Saved.')
          } catch (err) {
            setError((err as Error).message)
          } finally {
            setSaving(false)
          }
        }}
      >
        <h3>AUBOT Buddy</h3>
        <div className="form-grid">
          <label className="field">
            <span>Assistant name</span>
            <input className="input" maxLength={40} required {...bind('buddy_name')} />
          </label>
          <label className="field">
            <span>Tone</span>
            <select className="select" {...bind('buddy_tone')}>
              {data.tone_choices.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Voice</span>
            <select className="select" {...bind('buddy_voice')}>
              {data.voice_choices.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </label>
          <label className="field full">
            <span>Greeting</span>
            <textarea className="textarea" maxLength={300} required {...bind('buddy_greeting')} />
            <span className="hint">An AI disclosure is always added after the greeting and can't be removed.</span>
          </label>
        </div>

        <h3>Business details</h3>
        <p className="hint">Used in AUBOT's answers (for example opening hours and contact details).</p>
        <div className="form-grid">
          <label className="field"><span>Business name</span><input className="input" required {...bind('business_name')} /></label>
          <label className="field"><span>Tagline</span><input className="input" {...bind('tagline')} /></label>
          <label className="field"><span>Phone</span><input className="input" {...bind('phone')} /></label>
          <label className="field"><span>Email</span><input className="input" type="email" required {...bind('email')} /></label>
          <label className="field full"><span>Address</span><input className="input" {...bind('address')} /></label>
          <label className="field full"><span>Opening hours</span><input className="input" {...bind('opening_hours')} /></label>
        </div>
        {error && <p className="error-text" role="alert">{error}</p>}
        {msg && <p className="chip chip-good" role="status" style={{ justifySelf: 'start' }}>{msg}</p>}
        {!readOnly && (
          <div>
            <button className="btn btn-primary" disabled={saving}>
              <Save size={16} /> {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        )}
      </form>
      {user.is_owner && (
        <section className="card panel">
          <h3>Knowledge base</h3>
          <p className="hint">
            AUBOT only answers unrecognised questions from these FAQ entries. Add or edit them in the admin site; changes apply immediately.
          </p>
          <div>
            <a className="btn btn-sm" href="/admin/core/faqentry/" target="_blank" rel="noreferrer">
              <ExternalLink size={15} /> Manage FAQ entries
            </a>
          </div>
        </section>
      )}
    </>
  )
}
