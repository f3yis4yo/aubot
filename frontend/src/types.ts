export type Role = 'customer' | 'bot' | 'specialist' | 'system'
export type SessionStatus = 'active' | 'escalated' | 'closed'

export interface ChatMessage {
  id: number
  role: Role
  source: string
  text: string
  channel: 'text' | 'voice'
  intent: string
  confidence: number | null
  sentiment_label: string
  sentiment_score: number | null
  author: string | null
  created_at: string
}

export interface PublicConfig {
  business_name: string
  tagline: string
  phone: string
  opening_hours: string
  buddy_name: string
  ai_disclosure: string
  max_upload_mb: number
  voice_available: boolean
}

export interface SessionState {
  session_id: string
  status: SessionStatus
  escalation_reference: string | null
  contact: { name: string; email: string; phone: string }
  voice_consent: boolean
  messages: ChatMessage[]
}

export interface EscalationInfo {
  id: number
  reference: string
  reason: string
  status: string
  session_id: string
}

export interface TurnResponse {
  messages: ChatMessage[]
  status: SessionStatus
  escalation: EscalationInfo | null
  actions: string[]
}

export interface VoiceResponse extends TurnResponse {
  transcript: string
  audio_base64: string | null
  audio_mime: string
  timings_ms: { speech_to_text: number; assistant: number; text_to_speech: number; total: number }
}

export interface DocumentRow {
  id: string
  reference: string
  name: string
  file_type: string
  size_bytes: number
  page_count: number | null
  word_count: number
  has_text_layer: boolean
  category: string
  department: string
  routing_reason: string
  status: 'received' | 'in_review' | 'processed'
  session_id: string | null
  processing_ms: number
  created_at: string
  text_excerpt?: string
}

export interface CaseRow {
  id: number
  reference: string
  reason: string
  reason_label: string
  status: 'queued' | 'active' | 'resolved'
  session_id: string
  session_status: SessionStatus
  customer: { name: string; email: string; phone: string }
  trigger_text: string
  trigger_confidence: number | null
  assigned_to: string | null
  created_at: string
  accepted_at: string | null
  resolved_at: string | null
  resolution_note: string
}

export interface CaseDetail extends CaseRow {
  transcript: ChatMessage[]
  messages: ChatMessage[]
  documents: { id: string; reference: string; name: string; department: string; status: string }[]
}

export interface StaffUser {
  username: string
  name: string
  is_owner: boolean
}

export interface EvaluationRun {
  id: number
  suite: string
  label: string
  passed: boolean
  score: number
  threshold: number
  summary: Record<string, unknown>
  duration_ms: number
  created_at: string
  cases?: Record<string, unknown>[]
}

export interface Overview {
  window_days: number
  sessions: number
  escalated_sessions: number
  automation_rate: number | null
  bot_replies_by_source: Record<string, number>
  top_intents: { intent: string; count: number }[]
  sentiment: Record<string, number>
  daily: { date: string; automated: number; escalated: number }[]
  open_cases: { queued: number; active: number }
  documents_pending: number
  documents_7d: number
  usage: {
    month_spend_usd: number
    monthly_budget_usd: number
    last_30_days_by_service: Record<string, number>
    llm_configured: boolean
    llm_paused_reason: string | null
  }
}

export interface ProfileSettings {
  business_name: string
  tagline: string
  phone: string
  email: string
  address: string
  opening_hours: string
  buddy_name: string
  buddy_greeting: string
  buddy_tone: string
  buddy_voice: string
  tone_choices: { value: string; label: string }[]
  voice_choices: { value: string; label: string }[]
  updated_at: string
}
