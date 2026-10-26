import { useState } from 'react'
import { Mic, ShieldCheck } from 'lucide-react'
import type { SessionState } from '../types'

export function ConsentModal({ onAccept, onCancel }: { onAccept: () => void; onCancel: () => void }) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="consent-title">
      <div className="modal">
        <h3 id="consent-title" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Mic size={20} /> Use your voice?
        </h3>
        <p>To talk instead of type, we need your permission to use your microphone.</p>
        <ul>
          <li>Your recording is sent to our AI provider (OpenAI, USA) to turn it into text.</li>
          <li>The recording is deleted straight away and never stored. Only the text appears in this chat.</li>
          <li>You're talking to an AI assistant, and you can ask for a person at any time.</li>
          <li>You can turn voice off whenever you like.</li>
        </ul>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel}>
            Not now
          </button>
          <button className="btn btn-primary" onClick={onAccept} autoFocus>
            <ShieldCheck size={16} /> Allow voice
          </button>
        </div>
      </div>
    </div>
  )
}

export function ContactCard({
  initial,
  onSave,
}: {
  initial: SessionState['contact']
  onSave: (c: SessionState['contact']) => Promise<void>
}) {
  const [form, setForm] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value })

  return (
    <form
      className="contact-card"
      onSubmit={async (e) => {
        e.preventDefault()
        if (!form.email && !form.phone) return setError('Please add an email or a phone number.')
        setSaving(true)
        setError('')
        try {
          await onSave(form)
        } catch (err) {
          setError((err as Error).message)
        } finally {
          setSaving(false)
        }
      }}
    >
      <strong>How can our team reach you?</strong>
      <p className="hint">Only used to follow up on this enquiry.</p>
      <div className="contact-grid">
        <label className="field">
          <span>Name</span>
          <input className="input" value={form.name} onChange={set('name')} autoComplete="name" maxLength={120} />
        </label>
        <label className="field">
          <span>Phone</span>
          <input className="input" value={form.phone} onChange={set('phone')} autoComplete="tel" inputMode="tel" maxLength={40} />
        </label>
        <label className="field" style={{ gridColumn: '1 / -1' }}>
          <span>Email</span>
          <input className="input" type="email" value={form.email} onChange={set('email')} autoComplete="email" />
        </label>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div>
        <button className="btn btn-primary btn-sm" disabled={saving}>
          {saving ? 'Saving…' : 'Share with the team'}
        </button>
      </div>
    </form>
  )
}
