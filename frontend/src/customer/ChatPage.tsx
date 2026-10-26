import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, Headset, Info, LogOut, Mic, MicOff, Paperclip, RotateCcw, SendHorizontal, Square, UserRound } from 'lucide-react'
import { api, ApiError } from '../api'
import type { ChatMessage, PublicConfig, SessionState, TurnResponse, VoiceResponse } from '../types'
import { useSocket } from '../useSocket'
import { MessageBubble, Typing } from './MessageList'
import { ConsentModal, ContactCard } from './Panels'
import { useRecorder } from './useRecorder'

const STORAGE_KEY = 'aubot.chat'
const SUGGESTIONS = ['What are your opening hours?', 'How much is a call-out?', 'I need to book a plumber', 'I want to upload a document']

interface Stored {
  id: string
  token: string
}

function loadStored(): Stored | null {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
  } catch {
    return null
  }
}
function saveStored(s: Stored | null) {
  try {
    if (s) localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode: the chat still works, it just won't survive a refresh */
  }
}

function mergeMessages(current: ChatMessage[], incoming: ChatMessage[]) {
  const seen = new Set(current.map((m) => m.id))
  return [...current, ...incoming.filter((m) => !seen.has(m.id))]
}

export default function ChatPage() {
  const [config, setConfig] = useState<PublicConfig | null>(null)
  const [auth, setAuth] = useState<Stored | null>(null)
  const [state, setState] = useState<SessionState | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<null | 'thinking' | 'uploading' | 'listening'>(null)
  const [actions, setActions] = useState<string[]>([])
  const [toast, setToast] = useState('')
  const [askConsent, setAskConsent] = useState(false)
  const [contactSaved, setContactSaved] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const recorder = useRecorder()

  const flash = useCallback((msg: string) => {
    setToast(msg)
    window.setTimeout(() => setToast(''), 4500)
  }, [])

  const startNew = useCallback(async () => {
    const data = await api<SessionState & { token: string }>('/chat/sessions', { method: 'POST' })
    const stored = { id: data.session_id, token: data.token }
    saveStored(stored)
    setAuth(stored)
    setState(data)
    setActions([])
    setContactSaved(false)
  }, [])

  // Boot: load business config, then resume the stored chat or start a new one.
  useEffect(() => {
    api<PublicConfig>('/config').then(setConfig).catch(() => flash('Cannot reach AUBOT right now.'))
    const stored = loadStored()
    if (stored) {
      api<SessionState>(`/chat/sessions/${stored.id}`, { sessionToken: stored.token })
        .then((data) => {
          if (data.status === 'closed') return startNew()
          setAuth(stored)
          setState(data)
          setContactSaved(!!(data.contact.email || data.contact.phone))
        })
        .catch(() => startNew())
    } else {
      startNew().catch(() => flash('Cannot start a chat right now. Please try again shortly.'))
    }
  }, [startNew, flash])

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight })
  }, [state?.messages.length, busy])

  // Live pushes: specialist replies, joins and status changes.
  const live = useSocket(auth ? `/ws/chat/${auth.id}/?token=${encodeURIComponent(auth.token)}` : null, (e) => {
    if (e.event === 'message.new') setState((s) => (s ? { ...s, messages: mergeMessages(s.messages, [e.payload]) } : s))
    if (e.event === 'session.status')
      setState((s) => (s ? { ...s, status: e.payload.status, escalation_reference: e.payload.escalation ?? null } : s))
  })

  const applyTurn = (turn: TurnResponse) => {
    setState((s) =>
      s ? { ...s, status: turn.status, escalation_reference: turn.escalation?.reference ?? s.escalation_reference, messages: mergeMessages(s.messages, turn.messages) } : s,
    )
    setActions(turn.actions ?? [])
  }

  const handleError = (err: unknown) => {
    const e = err as ApiError
    if (e.status === 409) setState((s) => (s ? { ...s, status: 'closed' } : s))
    flash(e.message || 'Something went wrong.')
  }

  const send = async (body: string) => {
    const message = body.trim()
    if (!message || !auth || busy) return
    setText('')
    setBusy('thinking')
    setActions([])
    try {
      applyTurn(await api<TurnResponse>(`/chat/sessions/${auth.id}/messages`, { json: { text: message }, sessionToken: auth.token }))
    } catch (err) {
      setText(message)
      handleError(err)
    } finally {
      setBusy(null)
    }
  }

  const handoff = async () => {
    if (!auth) return
    setBusy('thinking')
    try {
      applyTurn({ ...(await api<TurnResponse>(`/chat/sessions/${auth.id}/handoff`, { method: 'POST', sessionToken: auth.token })), actions: [] })
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(null)
    }
  }

  const upload = async (file: File) => {
    if (!auth || !config) return
    // Instant client-side checks; the server re-validates everything.
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'docx'].includes(ext ?? '')) return flash('Only PDF and Word (.docx) files are accepted.')
    if (file.size === 0) return flash('That file is empty.')
    if (file.size > config.max_upload_mb * 1024 * 1024) return flash(`That file is over the ${config.max_upload_mb} MB limit.`)
    const form = new FormData()
    form.append('file', file)
    setBusy('uploading')
    try {
      const res = await api<{ message: ChatMessage }>(`/chat/sessions/${auth.id}/documents`, { form, sessionToken: auth.token })
      setState((s) => (s ? { ...s, messages: mergeMessages(s.messages, [res.message]) } : s))
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(null)
    }
  }

  const sendVoice = async (blob: Blob | null) => {
    if (!auth) return
    if (!blob || blob.size < 1200) {
      setBusy(null)
      return flash("I didn't catch anything. Tap the mic and speak, then tap again to send.")
    }
    setBusy('thinking')
    const form = new FormData()
    form.append('audio', blob, `voice.${blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm'}`)
    try {
      const res = await api<VoiceResponse>(`/chat/sessions/${auth.id}/voice`, { form, sessionToken: auth.token })
      applyTurn(res)
      if (res.audio_base64) {
        audioRef.current?.pause()
        audioRef.current = new Audio(`data:${res.audio_mime};base64,${res.audio_base64}`)
        audioRef.current.play().catch(() => undefined)
      }
    } catch (err) {
      const e = err as ApiError
      if (e.code === 'consent_required') setState((s) => (s ? { ...s, voice_consent: false } : s))
      handleError(err)
    } finally {
      setBusy(null)
    }
  }

  const toggleMic = async () => {
    if (!state || !auth) return
    if (recorder.recording) return sendVoice(await recorder.stop())
    if (!state.voice_consent) return setAskConsent(true)
    try {
      audioRef.current?.pause()
      await recorder.start(sendVoice)
      setBusy('listening')
    } catch {
      flash('Microphone access was blocked. Allow it in your browser settings, or type instead.')
    }
  }

  const setConsent = async (voice: boolean) => {
    if (!auth) return
    await api(`/chat/sessions/${auth.id}/consent`, { json: { voice }, sessionToken: auth.token })
    setState((s) => (s ? { ...s, voice_consent: voice } : s))
  }

  const endChat = async () => {
    if (!auth) return
    await api(`/chat/sessions/${auth.id}/close`, { method: 'POST', sessionToken: auth.token }).catch(() => undefined)
    setState((s) => (s ? { ...s, status: 'closed' } : s))
  }

  const saveContact = async (contact: SessionState['contact']) => {
    if (!auth) return
    const res = await api<{ message: ChatMessage }>(`/chat/sessions/${auth.id}/contact`, { json: contact, sessionToken: auth.token })
    setState((s) => (s ? { ...s, contact, messages: mergeMessages(s.messages, [res.message]) } : s))
    setContactSaved(true)
  }

  const assistant = config?.buddy_name ?? 'AUBOT'
  const escalated = state?.status === 'escalated'
  const closed = state?.status === 'closed'
  const onlyGreeting = (state?.messages.length ?? 0) <= 1
  const voiceReady = !!config?.voice_available && recorder.supported

  return (
    <div className="chat-shell">
      <main className="chat card" aria-label={`${config?.business_name ?? 'Customer'} chat`}>
        <header className="chat-header">
          <div className="avatar" aria-hidden>
            <Bot size={22} />
          </div>
          <div>
            <h1>{config?.business_name ?? 'AUBOT'}</h1>
            <p>
              {assistant} · AI assistant<span className="tagline">{config ? ` · ${config.tagline}` : ''}</span>
            </p>
          </div>
          <div className="spacer" />
          {!closed && (
            <button className="btn btn-sm" onClick={handoff} disabled={escalated || !!busy} title="Talk to a person from our team">
              <Headset size={16} /> <span className="btn-label">Talk to a human</span>
            </button>
          )}
          {!closed && (
            <button className="btn btn-sm" onClick={endChat} aria-label="End chat" title="End chat">
              <LogOut size={16} />
            </button>
          )}
        </header>

        <div>
          <div className="disclosure">
            <Info size={16} style={{ flex: 'none', marginTop: 2 }} aria-hidden />
            <span>
              <strong>You're chatting with an AI assistant.</strong> It can make mistakes, and you can ask for a person at any time.
            </span>
          </div>
          {escalated && (
            <div className="status-bar" role="status">
              <UserRound size={16} /> Connected to our team{state?.escalation_reference ? ` · case ${state.escalation_reference}` : ''}
              <span className="live" style={{ marginLeft: 'auto' }}>
                <span className="dot" style={{ background: live ? 'var(--good)' : 'var(--text-3)' }} /> {live ? 'live' : 'reconnecting'}
              </span>
            </div>
          )}
        </div>

        <div ref={scroller} className="messages" aria-live="polite">
          {state?.messages.map((m) => <MessageBubble key={m.id} m={m} assistantName={assistant} />)}
          {busy === 'thinking' && <Typing label={`${assistant} is typing`} />}
          {busy === 'uploading' && <div className="msg msg-system"><div className="bubble">Uploading and checking your document…</div></div>}
          {onlyGreeting && !busy && (
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="btn btn-sm" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}
          {actions.length > 0 && !escalated && (
            <div className="actions-row">
              {actions.includes('upload') && (
                <button className="btn btn-sm" onClick={() => fileInput.current?.click()}>
                  <Paperclip size={15} /> Upload a document
                </button>
              )}
              {actions.includes('handoff') && (
                <button className="btn btn-sm" onClick={handoff}>
                  <Headset size={15} /> Talk to a human
                </button>
              )}
            </div>
          )}
          {escalated && !contactSaved && state && <ContactCard initial={state.contact} onSave={saveContact} />}
          {closed && (
            <div className="msg msg-system">
              <div className="bubble">
                This chat has ended.{' '}
                <button className="btn btn-sm" onClick={() => startNew()} style={{ marginLeft: 6 }}>
                  <RotateCcw size={14} /> Start a new chat
                </button>
              </div>
            </div>
          )}
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
        >
          <div className="composer-row">
            <input
              ref={fileInput}
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (f) upload(f)
              }}
            />
            <button
              type="button"
              className="btn icon-btn"
              onClick={() => fileInput.current?.click()}
              disabled={closed || !!busy}
              aria-label="Attach a PDF or Word document"
              title={`Attach a PDF or Word document (max ${config?.max_upload_mb ?? 5} MB)`}
            >
              <Paperclip size={18} />
            </button>
            <label className="sr-only" htmlFor="chat-input">
              Message
            </label>
            <textarea
              id="chat-input"
              rows={1}
              value={text}
              maxLength={2000}
              placeholder={closed ? 'Chat ended' : busy === 'listening' ? 'Listening… tap the square to send' : escalated ? 'Message our team…' : `Message ${assistant}…`}
              disabled={closed || busy === 'listening'}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(text)
                }
              }}
            />
            <button
              type="button"
              className={`btn icon-btn ${recorder.recording ? 'recording' : ''}`}
              onClick={toggleMic}
              disabled={closed || !voiceReady || (!!busy && busy !== 'listening')}
              aria-label={recorder.recording ? 'Stop and send voice message' : 'Speak your message'}
              title={!voiceReady ? 'Voice is not available right now' : recorder.recording ? 'Stop and send' : 'Speak your message'}
            >
              {recorder.recording ? <Square size={16} /> : voiceReady ? <Mic size={18} /> : <MicOff size={18} />}
            </button>
            <button type="submit" className="btn btn-primary icon-btn" disabled={!text.trim() || !!busy || closed} aria-label="Send message">
              <SendHorizontal size={18} />
            </button>
          </div>
          <div className="composer-tools hint">
            <span>
              PDF or DOCX up to {config?.max_upload_mb ?? 5} MB · {config?.opening_hours ?? ''}
            </span>
            {state?.voice_consent && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setConsent(false)}>
                Voice on · turn off
              </button>
            )}
          </div>
        </form>
      </main>

      {askConsent && (
        <ConsentModal
          onCancel={() => setAskConsent(false)}
          onAccept={async () => {
            setAskConsent(false)
            try {
              await setConsent(true)
              await recorder.start(sendVoice)
              setBusy('listening')
            } catch {
              flash('Microphone access was blocked. Allow it in your browser settings, or type instead.')
            }
          }}
        />
      )}
      {toast && (
        <div className="toast" role="alert">
          {toast}
        </div>
      )}
    </div>
  )
}
