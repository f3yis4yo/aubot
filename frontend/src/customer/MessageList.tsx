import { Mic } from 'lucide-react'
import type { ChatMessage } from '../types'

function time(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export function MessageBubble({ m, assistantName }: { m: ChatMessage; assistantName: string }) {
  if (m.role === 'system') {
    return (
      <div className="msg msg-system" role="status">
        <div className="bubble">{m.text}</div>
      </div>
    )
  }
  return (
    <div className={`msg msg-${m.role}`}>
      <div className="msg-meta">
        {m.role === 'bot' && (
          <>
            <strong>{assistantName}</strong>
            <span className="ai-tag" title="Automated reply from an AI assistant">AI</span>
          </>
        )}
        {m.role === 'specialist' && (
          <>
            <strong>{m.author ?? 'Our team'}</strong>
            <span className="human-tag">TEAM</span>
          </>
        )}
        {m.role === 'customer' && (
          <>
            {m.channel === 'voice' && <Mic size={12} aria-label="Voice message" />}
            <span>You</span>
          </>
        )}
        <span aria-hidden>·</span>
        <time dateTime={m.created_at}>{time(m.created_at)}</time>
      </div>
      <div className="bubble">{m.text}</div>
    </div>
  )
}

export function Typing({ label }: { label: string }) {
  return (
    <div className="msg msg-bot" aria-live="polite">
      <div className="bubble typing" aria-label={label}>
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}
