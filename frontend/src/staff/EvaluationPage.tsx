import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Play, XCircle } from 'lucide-react'
import { api } from '../api'
import type { EvaluationRun } from '../types'

interface EvalData {
  suites: { suite: string; label: string; threshold: number }[]
  latest: Record<string, EvaluationRun | null>
  history: EvaluationRun[]
}

const DESCRIPTIONS: Record<string, string> = {
  tc01: '100 held-out customer queries (10 intents, incl. misspelled & ambiguous) classified against ground truth.',
  tc02: 'Valid PDF (2 MB) & DOCX (1 MB), oversized (8 MB), unsupported, empty, corrupted, renamed and scanned files.',
  tc03: '20 vague, incomplete or conflicting queries. Every low-confidence one must be escalated or answered strictly from the FAQ.',
  tc04: '50 human-labelled utterances (positive / neutral / negative) scored by the sentiment model.',
}

const isRate = (key: string) => /rate|accuracy/.test(key)

function fmt(v: unknown, key = ''): string {
  if (typeof v === 'number') return isRate(key) && v <= 1 ? `${(v * 100).toFixed(1)}%` : String(v)
  if (typeof v === 'object' && v !== null)
    return Object.entries(v)
      .map(([k, x]) => (typeof x === 'object' && x !== null ? `${k} → ${fmt(x, key)}` : `${k} ${fmt(x, key)}`))
      .join(isRate(key) || Object.values(v).some((x) => typeof x === 'object') ? ' · ' : ', ')
  return String(v)
}

function CaseTable({ cases }: { cases: Record<string, unknown>[] }) {
  if (!cases.length) return null
  const cols = Object.keys(cases[0])
  return (
    <div className="table-wrap" style={{ maxHeight: 360, overflow: 'auto' }}>
      <table>
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c.replaceAll('_', ' ')}</th>)}</tr>
        </thead>
        <tbody>
          {cases.map((row, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = row[c]
                return <td key={c}>{typeof v === 'boolean' ? (v ? '✓' : '✗') : v === null ? '–' : String(v)}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function EvaluationPage() {
  const [data, setData] = useState<EvalData | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(() => {
    api<EvalData>('/staff/evaluation').then(setData).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])

  const run = async (suite: string) => {
    setRunning(suite)
    setError('')
    try {
      await api('/staff/evaluation/run', { json: { suite } })
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(null)
    }
  }

  return (
    <>
      <div className="page-head">
        <h2>Evaluation</h2>
        <span className="hint">Benchmarks from Assessment 2 (Table 8), stored as evidence</span>
        <span className="spacer" />
        <button className="btn btn-primary" onClick={() => run('all')} disabled={!!running}>
          <Play size={16} /> {running === 'all' ? 'Running all…' : 'Run all suites'}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      <p className="hint">
        TC05 (voice latency ≤ 5 s) and the 10-concurrent-request test (≤ 3 s) need a running server: <code>python scripts/benchmark.py</code>.
      </p>
      <div className="suites">
        {data?.suites.map((s) => {
          const r = data.latest[s.suite]
          return (
            <section key={s.suite} className="card suite">
              <div className="page-head">
                <h3>{s.label}</h3>
                <span className="spacer" />
                {r &&
                  (r.passed ? (
                    <span className="chip chip-good"><CheckCircle2 size={13} /> Pass</span>
                  ) : (
                    <span className="chip chip-bad"><XCircle size={13} /> Fail</span>
                  ))}
              </div>
              <p className="hint">{DESCRIPTIONS[s.suite]}</p>
              <div className="score">
                {r ? `${(r.score * 100).toFixed(1)}%` : '–'} <span className="hint">target ≥ {(s.threshold * 100).toFixed(0)}%</span>
              </div>
              {r && (
                <dl className="kv">
                  {Object.entries(r.summary)
                    .filter(([k]) => k !== 'note')
                    .map(([k, v]) => (
                      <div key={k} style={{ display: 'contents' }}>
                        <dt>{k.replaceAll('_', ' ')}</dt>
                        <dd>{fmt(v, k)}</dd>
                      </div>
                    ))}
                </dl>
              )}
              {r && typeof r.summary.note === 'string' && <p className="hint">{r.summary.note}</p>}
              <div className="actions-row">
                <button className="btn btn-sm" onClick={() => run(s.suite)} disabled={!!running}>
                  <Play size={14} /> {running === s.suite ? 'Running…' : 'Run'}
                </button>
                {r && <span className="hint">Last run {new Date(r.created_at).toLocaleString()} · {r.duration_ms} ms</span>}
              </div>
              {r?.cases && (
                <details>
                  <summary className="hint">Show all {r.cases.length} cases</summary>
                  <CaseTable cases={r.cases} />
                </details>
              )}
            </section>
          )
        })}
      </div>
      {data && data.history.length > 0 && (
        <section className="card panel">
          <h3>Run history</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>When</th><th>Suite</th><th>Score</th><th>Target</th><th>Result</th></tr>
              </thead>
              <tbody>
                {data.history.map((h) => (
                  <tr key={h.id}>
                    <td>{new Date(h.created_at).toLocaleString()}</td>
                    <td>{h.label}</td>
                    <td>{(h.score * 100).toFixed(1)}%</td>
                    <td>{(h.threshold * 100).toFixed(0)}%</td>
                    <td>{h.passed ? <span className="chip chip-good"><CheckCircle2 size={12} /> Pass</span> : <span className="chip chip-bad"><XCircle size={12} /> Fail</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
