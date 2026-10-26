import { useCallback, useEffect, useState } from 'react'
import { Download, ScanLine, X } from 'lucide-react'
import { api } from '../api'
import type { DocumentRow } from '../types'
import { useStaffEvents } from './staffContext'

const STATUS: Record<DocumentRow['status'], { label: string; chip: string }> = {
  received: { label: 'Received', chip: 'chip-warn' },
  in_review: { label: 'In review', chip: 'chip-brand' },
  processed: { label: 'Processed', chip: 'chip-good' },
}
const DEPARTMENTS = ['Claims & Insurance', 'Accounts', 'Sales & Scheduling', 'Compliance', 'Estimating', 'Customer Care']

const size = (b: number) => (b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`)

export default function DocumentsPage() {
  const [items, setItems] = useState<DocumentRow[]>([])
  const [status, setStatus] = useState('')
  const [department, setDepartment] = useState('')
  const [open, setOpen] = useState<DocumentRow | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    const q = new URLSearchParams({ status, department })
    api<{ items: DocumentRow[] }>(`/staff/documents?${q}`).then((r) => setItems(r.items)).catch((e) => setError(e.message))
  }, [status, department])
  useEffect(load, [load])
  useStaffEvents((e) => {
    if (e.event === 'document.new' || e.event === 'document.updated') load()
  })

  const view = async (d: DocumentRow) => setOpen(await api<DocumentRow>(`/staff/documents/${d.id}`))
  const setDocStatus = async (d: DocumentRow, next: DocumentRow['status']) => {
    try {
      const row = await api<DocumentRow>(`/staff/documents/${d.id}`, { method: 'PATCH', json: { status: next } })
      setOpen((o) => (o && o.id === row.id ? { ...o, ...row } : o))
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <>
      <div className="page-head">
        <h2>Documents</h2>
        <span className="hint">Uploaded by customers, checked and routed automatically</span>
      </div>
      <div className="filters">
        <select className="select" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">All statuses</option>
          {Object.entries(STATUS).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        <select className="select" value={department} onChange={(e) => setDepartment(e.target.value)} aria-label="Filter by team">
          <option value="">All teams</option>
          {DEPARTMENTS.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </select>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>Reference</th>
              <th>File</th>
              <th>Routed to</th>
              <th>Status</th>
              <th>Received</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.id}>
                <td><strong>{d.reference}</strong></td>
                <td>
                  {d.name}
                  <div className="hint">
                    {d.file_type.toUpperCase()} · {size(d.size_bytes)}
                    {d.page_count ? ` · ${d.page_count} p` : ''}
                    {!d.has_text_layer && (
                      <span className="chip chip-warn" style={{ marginLeft: 6 }}>
                        <ScanLine size={12} /> scan, needs manual review
                      </span>
                    )}
                  </div>
                </td>
                <td>
                  {d.department}
                  <div className="hint">{d.category.replace('_', ' ')}</div>
                </td>
                <td><span className={`chip ${STATUS[d.status].chip}`}>{STATUS[d.status].label}</span></td>
                <td className="hint">{new Date(d.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</td>
                <td><button className="btn btn-sm" onClick={() => view(d)}>Open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length === 0 && <p className="empty">No documents match.</p>}
      </div>

      {open && (
        <aside className="drawer" aria-label={`Document ${open.reference}`}>
          <div className="page-head">
            <h3>{open.reference}</h3>
            <span className="spacer" />
            <button className="btn btn-ghost icon-btn" onClick={() => setOpen(null)} aria-label="Close">
              <X size={18} />
            </button>
          </div>
          <dl className="kv">
            <dt>File</dt><dd>{open.name}</dd>
            <dt>Size</dt><dd>{size(open.size_bytes)} · {open.word_count} words{open.page_count ? ` · ${open.page_count} pages` : ''}</dd>
            <dt>Routed to</dt><dd>{open.department} ({open.category.replace('_', ' ')})</dd>
            <dt>Why</dt><dd>{open.routing_reason}</dd>
            <dt>Processed in</dt><dd>{open.processing_ms} ms</dd>
          </dl>
          <div className="actions-row">
            <a className="btn btn-sm" href={`/api/staff/documents/${open.id}/download`}>
              <Download size={15} /> Download
            </a>
            {(['received', 'in_review', 'processed'] as const).map((s) => (
              <button key={s} className={`btn btn-sm ${open.status === s ? 'btn-primary' : ''}`} onClick={() => setDocStatus(open, s)}>
                {STATUS[s].label}
              </button>
            ))}
          </div>
          <div>
            <strong>Extracted text</strong>
            <div className="excerpt">{open.text_excerpt || 'No text layer found (scanned document).'}</div>
          </div>
        </aside>
      )}
    </>
  )
}
