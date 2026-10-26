import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CheckCheck, Clock, FileText, Hand, SendHorizontal } from 'lucide-react'
import { api } from '../api'
import type { CaseDetail, CaseRow, ChatMessage } from '../types'
import { useStaff, useStaffEvents } from './staffContext'

function ago(iso: string) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.round(mins / 60)
  return h < 24 ? `${h} h ago` : new Date(iso).toLocaleDateString()
}

const STATUS_CHIP: Record<string, string> = { queued: 'chip-warn', active: 'chip-brand', resolved: 'chip-good' }
const STATUS_LABEL: Record<string, string> = { queued: 'Waiting', active: 'In progress', resolved: 'Resolved' }

function Line({ m }: { m: ChatMessage }) {
  const who = m.role === 'customer' ? 'Customer' : m.role === 'bot' ? 'AUBOT' : m.role === 'specialist' ? m.author ?? 'Staff' : 'System'
  return (
    <div className={`msg msg-${m.role === 'customer' ? 'bot' : m.role === 'specialist' ? 'customer' : m.role}`}>
      {m.role !== 'system' && (
        <div className="msg-meta">
          <strong>{who}</strong>
          {m.role === 'bot' && <span className="ai-tag">AI</span>}
          {m.channel === 'voice' && <span className="chip">voice</span>}
          {m.intent && (
            <span className="chip" title="Detected intent and confidence">
              {m.intent} {m.confidence !== null ? `${Math.round(m.confidence * 100)}%` : ''}
            </span>
          )}
          {m.sentiment_label && m.role === 'customer' && (
            <span className={`chip sentiment ${m.sentiment_label === 'negative' ? 'chip-bad' : m.sentiment_label === 'positive' ? 'chip-good' : ''}`} title="Sentiment (logged only)">
              {m.sentiment_label}
            </span>
          )}
          <span>{new Date(m.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>
        </div>
      )}
      <div className="bubble">{m.text}</div>
    </div>
  )
}

export default function CasesPage() {
  const { refreshCounts } = useStaff()
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<'open' | 'resolved'>('open')
  const [items, setItems] = useState<CaseRow[]>([])
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [reply, setReply] = useState('')
  const [note, setNote] = useState('')
  const [resolving, setResolving] = useState(false)
  const [error, setError] = useState('')
  const bodyRef = useRef<HTMLDivElement>(null)
  const selected = Number(params.get('case')) || null

  const loadList = useCallback(() => {
    api<{ items: CaseRow[] }>(`/staff/escalations?status=${tab}`).then((r) => setItems(r.items)).catch((e) => setError(e.message))
  }, [tab])
  const loadDetail = useCallback(() => {
    if (!selected) return setDetail(null)
    api<CaseDetail>(`/staff/escalations/${selected}`).then(setDetail).catch((e) => setError(e.message))
  }, [selected])

  useEffect(loadList, [loadList])
  useEffect(loadDetail, [loadDetail])
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [detail?.messages.length])

  useStaffEvents((e) => {
    if (e.event.startsWith('escalation.')) {
      loadList()
      if (e.payload.id === selected) loadDetail()
    }
    if ((e.event === 'message.new' || e.event === 'session.updated') && detail && e.payload.session_id === detail.session_id) {
      if (e.event === 'session.updated') return loadDetail()
      setDetail((d) => (d && !d.messages.some((m) => m.id === e.payload.message.id) ? { ...d, messages: [...d.messages, e.payload.message] } : d))
    }
    if (e.event === 'document.new' && detail && e.payload.session_id === detail.session_id) loadDetail()
  })

  const act = async (path: string, json?: unknown) => {
    if (!detail) return
    setError('')
    try {
      await api(`/staff/escalations/${detail.id}/${path}`, { method: 'POST', json })
      loadDetail()
      loadList()
      refreshCounts()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const sendReply = async () => {
    const text = reply.trim()
    if (!text || !detail) return
    setReply('')
    try {
      const msg = await api<ChatMessage>(`/staff/escalations/${detail.id}/reply`, { json: { text } })
      setDetail((d) => (d && !d.messages.some((m) => m.id === msg.id) ? { ...d, status: 'active', messages: [...d.messages, msg] } : d))
      if (detail.status === 'queued') {
        loadList()
        refreshCounts()
      }
    } catch (e) {
      setReply(text)
      setError((e as Error).message)
    }
  }

  const handedOffAt = detail?.transcript.length ?? 0

  return (
    <>
      <div className="page-head">
        <h2>Cases</h2>
        <span className="hint">Chats AUBOT handed to a person, with the full conversation attached</span>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="cases">
        <section className="card queue" aria-label="Case queue">
          <div className="queue-tabs" role="tablist">
            {(['open', 'resolved'] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={`btn btn-sm ${tab === t ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setTab(t)}>
                {t === 'open' ? 'Open' : 'Resolved'}
              </button>
            ))}
          </div>
          <div className="queue-list">
            {items.length === 0 && <p className="empty">{tab === 'open' ? 'No customers waiting. 🎉' : 'No resolved cases yet.'}</p>}
            {items.map((c) => (
              <button key={c.id} className={`queue-item ${c.id === selected ? 'selected' : ''}`} onClick={() => setParams({ case: String(c.id) })}>
                <div className="row">
                  <span className="ref">{c.reference}</span>
                  <span className={`chip ${STATUS_CHIP[c.status]}`}>{STATUS_LABEL[c.status]}</span>
                </div>
                <span className="snippet">{c.trigger_text || '—'}</span>
                <div className="row hint">
                  <span>{c.customer.name || 'Anonymous customer'}</span>
                  <span>
                    <Clock size={12} style={{ verticalAlign: -1 }} /> {ago(c.created_at)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="card case-detail" aria-label="Case detail">
          {!detail ? (
            <p className="empty" style={{ gridRow: '1 / -1', alignSelf: 'center' }}>
              Select a case to see the conversation.
            </p>
          ) : (
            <>
              <div className="case-head">
                <div className="row">
                  <h3 style={{ fontSize: 18 }}>{detail.reference}</h3>
                  <span className={`chip ${STATUS_CHIP[detail.status]}`}>{STATUS_LABEL[detail.status]}</span>
                  <span className="chip">{detail.reason_label}</span>
                  {detail.session_status === 'closed' && <span className="chip">Customer left the chat</span>}
                  <span style={{ flex: 1 }} />
                  {detail.status === 'queued' && (
                    <button className="btn btn-primary btn-sm" onClick={() => act('accept')}>
                      <Hand size={15} /> Accept case
                    </button>
                  )}
                  {detail.status !== 'resolved' && (
                    <button className="btn btn-sm" onClick={() => setResolving((r) => !r)}>
                      <CheckCheck size={15} /> Resolve
                    </button>
                  )}
                </div>
                <dl className="case-meta">
                  <div><dt>Customer</dt><dd>{detail.customer.name || '—'}</dd></div>
                  <div><dt>Email</dt><dd>{detail.customer.email ? <a href={`mailto:${detail.customer.email}`}>{detail.customer.email}</a> : '—'}</dd></div>
                  <div><dt>Phone</dt><dd>{detail.customer.phone ? <a href={`tel:${detail.customer.phone}`}>{detail.customer.phone}</a> : '—'}</dd></div>
                  <div><dt>Triggered by</dt><dd>“{detail.trigger_text}”</dd></div>
                  <div><dt>Intent confidence</dt><dd>{detail.trigger_confidence !== null ? `${Math.round(detail.trigger_confidence * 100)}%` : 'n/a (customer request)'}</dd></div>
                  <div><dt>Assigned</dt><dd>{detail.assigned_to ?? 'Unassigned'}</dd></div>
                </dl>
                {detail.documents.length > 0 && (
                  <div className="actions-row">
                    {detail.documents.map((d) => (
                      <a key={d.id} className="chip" href={`/api/staff/documents/${d.id}/download`}>
                        <FileText size={13} /> {d.reference} · {d.name}
                      </a>
                    ))}
                  </div>
                )}
                {resolving && (
                  <form
                    style={{ display: 'flex', gap: 8 }}
                    onSubmit={(e) => {
                      e.preventDefault()
                      act('resolve', { note }).then(() => {
                        setResolving(false)
                        setNote('')
                      })
                    }}
                  >
                    <input className="input" placeholder="Resolution note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
                    <button className="btn btn-primary btn-sm">Mark resolved</button>
                  </form>
                )}
                {detail.status === 'resolved' && detail.resolution_note && <p className="hint">Resolution: {detail.resolution_note}</p>}
              </div>

              <div className="case-body" ref={bodyRef}>
                {detail.messages.map((m, i) => (
                  <div key={m.id} style={{ display: 'contents' }}>
                    {i === handedOffAt && (
                      <div className="msg msg-system">
                        <div className="bubble">Handed to staff · everything above was shared with the specialist</div>
                      </div>
                    )}
                    <Line m={m} />
                  </div>
                ))}
              </div>

              <form
                className="case-reply"
                onSubmit={(e) => {
                  e.preventDefault()
                  sendReply()
                }}
              >
                <label className="sr-only" htmlFor="reply">Reply to customer</label>
                <textarea
                  id="reply"
                  className="textarea"
                  value={reply}
                  disabled={detail.status === 'resolved' || detail.session_status === 'closed'}
                  placeholder={detail.session_status === 'closed' ? 'Customer has left. Follow up by email or phone.' : 'Reply to the customer… (Enter to send)'}
                  onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      sendReply()
                    }
                  }}
                />
                <button className="btn btn-primary" disabled={!reply.trim() || detail.status === 'resolved' || detail.session_status === 'closed'}>
                  <SendHorizontal size={16} /> Send
                </button>
              </form>
            </>
          )}
        </section>
      </div>
    </>
  )
}
