/** Thin fetch wrapper. Customers authenticate per chat with X-Session-Token; staff use
 *  the Django session cookie plus the CSRF token on every write. */

export class ApiError extends Error {
  status: number
  code?: string
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

function cookie(name: string): string {
  return document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))?.split('=')[1] ?? ''
}

interface Options {
  method?: string
  json?: unknown
  form?: FormData
  sessionToken?: string
  signal?: AbortSignal
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.json !== undefined || opts.form ? 'POST' : 'GET')
  const headers: Record<string, string> = {}
  if (opts.json !== undefined) headers['Content-Type'] = 'application/json'
  if (opts.sessionToken) headers['X-Session-Token'] = opts.sessionToken
  if (method !== 'GET') headers['X-CSRFToken'] = decodeURIComponent(cookie('csrftoken'))

  let resp: Response
  try {
    resp = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: opts.form ?? (opts.json !== undefined ? JSON.stringify(opts.json) : undefined),
      signal: opts.signal,
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your connection and try again.')
  }
  const isJson = resp.headers.get('content-type')?.includes('application/json')
  const body = isJson ? await resp.json() : null
  if (!resp.ok) {
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? 'Please check the form and try again.' : `Request failed (${resp.status})`
    throw new ApiError(resp.status, message, body?.code)
  }
  return body as T
}

export async function ensureCsrf() {
  if (!cookie('csrftoken')) await api('/auth/csrf')
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}
