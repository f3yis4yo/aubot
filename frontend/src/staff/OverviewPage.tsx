import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'
import { api } from '../api'
import type { Overview } from '../types'
import { useStaffEvents } from './staffContext'

const pct = (v: number | null) => (v === null ? '–' : `${Math.round(v * 100)}%`)
const INTENT_LABELS: Record<string, string> = {
  opening_hours: 'Opening hours',
  book_appointment: 'Book a job',
  manage_booking: 'Change booking',
  pricing_quote: 'Pricing & quotes',
  services_offered: 'Services',
  location_contact: 'Contact & area',
  payment_billing: 'Payments',
  document_submission: 'Documents',
  complaint: 'Complaints',
  human_agent: 'Asked for human',
  out_of_scope: 'Not recognised',
}

function DailyChart({ daily }: { daily: Overview['daily'] }) {
  const max = Math.max(1, ...daily.map((d) => d.automated + d.escalated))
  const day = (iso: string) => new Date(`${iso}T00:00`).toLocaleDateString([], { weekday: 'short' })
  return (
    <figure style={{ margin: 0, display: 'grid', gap: 8 }}>
      <div className="legend" aria-hidden>
        <span><i style={{ background: 'var(--series-1)' }} />Handled by AUBOT</span>
        <span><i style={{ background: 'var(--series-2)' }} />Escalated to staff</span>
      </div>
      <div className="barchart" role="img" aria-label="Chats per day for the last 7 days, split by automated and escalated">
        {daily.map((d) => {
          const total = d.automated + d.escalated
          return (
            <div key={d.date} className="bar-col" tabIndex={0} aria-label={`${day(d.date)}: ${d.automated} automated, ${d.escalated} escalated`}>
              {d.automated > 0 && (
                <div className={`bar-seg ${d.escalated > 0 ? 'bottom' : ''}`} style={{ height: `${(d.automated / max) * 100}%`, background: 'var(--series-1)' }} />
              )}
              {d.escalated > 0 && <div className="bar-seg" style={{ height: `${(d.escalated / max) * 100}%`, background: 'var(--series-2)' }} />}
              <div className="tooltip">
                <strong>{new Date(`${d.date}T00:00`).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })}</strong>
                <br />
                {d.automated} handled by AUBOT · {d.escalated} escalated · {total} total
              </div>
            </div>
          )
        })}
      </div>
      <div className="bar-labels" aria-hidden>
        {daily.map((d) => (
          <span key={d.date}>{day(d.date)}</span>
        ))}
      </div>
      <details>
        <summary className="hint">Show as table</summary>
        <table>
          <thead>
            <tr><th>Date</th><th>Handled by AUBOT</th><th>Escalated</th></tr>
          </thead>
          <tbody>
            {daily.map((d) => (
              <tr key={d.date}><td>{d.date}</td><td>{d.automated}</td><td>{d.escalated}</td></tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}

function HBars({ rows }: { rows: { label: string; value: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  if (!rows.length) return <p className="empty">No data yet.</p>
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.map((r) => (
        <div className="hbar" key={r.label}>
          <span>{r.label}</span>
          <div className="track" aria-hidden>
            <div className="fill" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
          <span className="num">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(() => {
    api<Overview>('/staff/overview').then(setData).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])
  useStaffEvents((e) => {
    if (e.event === 'escalation.new' || e.event === 'document.new') load()
  })

  if (error) return <p className="error-text">{error}</p>
  if (!data) return <p className="empty">Loading overview…</p>
  const u = data.usage
  const spendShare = Math.min(1, u.month_spend_usd / u.monthly_budget_usd)

  return (
    <>
      <div className="page-head">
        <h2>Overview</h2>
        <span className="hint">Last {data.window_days} days</span>
        <span className="spacer" />
        <button className="btn btn-sm" onClick={load}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      {(!u.llm_configured || u.llm_paused_reason) && (
        <div className="card panel" role="alert" style={{ borderColor: 'var(--warning)' }}>
          <strong style={{ display: 'flex', gap: 8, alignItems: 'center', color: 'var(--warning-text)' }}>
            <AlertTriangle size={18} /> Generative answers and voice are off
          </strong>
          <p className="hint">
            {u.llm_paused_reason
              ? `OpenAI reported: ${u.llm_paused_reason}. AUBOT is escalating unclear questions to staff instead. It retries automatically every 5 minutes.`
              : 'No OpenAI API key is configured. Intent answers, documents and escalation still work.'}
          </p>
        </div>
      )}

      <div className="tiles">
        <div className="card tile">
          <span className="label">Chats</span>
          <span className="value">{data.sessions}</span>
          <span className="sub">{data.escalated_sessions} needed a person</span>
        </div>
        <div className="card tile">
          <span className="label">Handled by AUBOT</span>
          <span className="value">{pct(data.automation_rate)}</span>
          <span className="sub">without staff involvement</span>
        </div>
        <div className="card tile">
          <span className="label">Cases waiting</span>
          <span className="value">{data.open_cases.queued}</span>
          <span className="sub">{data.open_cases.active} in progress</span>
        </div>
        <div className="card tile">
          <span className="label">Documents to review</span>
          <span className="value">{data.documents_pending}</span>
          <span className="sub">{data.documents_7d} received this week</span>
        </div>
        <div className="card tile">
          <span className="label">AI spend this month</span>
          <span className="value">${u.month_spend_usd.toFixed(2)}</span>
          <span className="sub">
            {spendShare < 0.8 ? <CheckCircle2 size={13} color="var(--good)" style={{ verticalAlign: -2 }} /> : <AlertTriangle size={13} color="var(--warning)" style={{ verticalAlign: -2 }} />}{' '}
            of ${u.monthly_budget_usd.toFixed(0)} USD cap
          </span>
          <div className="meter" aria-label={`${Math.round(spendShare * 100)}% of budget used`}>
            <div style={{ width: `${spendShare * 100}%` }} />
          </div>
        </div>
      </div>

      <div className="grid-2">
        <section className="card panel">
          <h3>Chats per day</h3>
          <DailyChart daily={data.daily} />
        </section>
        <section className="card panel">
          <h3>What customers ask about</h3>
          <HBars rows={data.top_intents.map((i) => ({ label: INTENT_LABELS[i.intent] ?? i.intent, value: i.count }))} />
        </section>
      </div>
      <div className="grid-2">
        <section className="card panel">
          <h3>How AUBOT answered</h3>
          <HBars
            rows={[
              { label: 'Matched intent', value: data.bot_replies_by_source.intent ?? 0 },
              { label: 'From FAQ (AI)', value: data.bot_replies_by_source.faq_llm ?? 0 },
              { label: 'Small talk', value: data.bot_replies_by_source.smalltalk ?? 0 },
            ]}
          />
        </section>
        <section className="card panel">
          <h3>Customer sentiment</h3>
          <p className="hint">Logged for insight only. It never decides whether a chat is escalated.</p>
          <HBars rows={['positive', 'neutral', 'negative'].map((k) => ({ label: k[0].toUpperCase() + k.slice(1), value: data.sentiment[k] ?? 0 }))} />
        </section>
      </div>
    </>
  )
}
