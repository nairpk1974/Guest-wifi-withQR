// Thin fetch wrapper: same-origin cookie session + per-session CSRF header on every mutation.
let csrfToken = ''
let onUnauthorized = () => {}

export function setCsrf(t) { csrfToken = t || '' }
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

export class ApiError extends Error {
  constructor(status, message, errors) { super(message); this.status = status; this.errors = errors }
}

async function request(method, url, body, { raw = false } = {}) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken
  const res = await fetch(url, { method, headers, credentials: 'same-origin',
    body: body !== undefined ? JSON.stringify(body) : undefined })
  if (res.status === 401 && !url.startsWith('/api/auth/login') && !url.startsWith('/api/auth/mfa')) {
    onUnauthorized()
  }
  if (!res.ok) {
    let msg = res.statusText, errors
    try { const j = await res.json(); msg = j.detail || msg; errors = j.errors } catch { /* not json */ }
    if (errors?.length) msg = errors.map(e => `${e.field}: ${e.message}`).join('; ')
    throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg), errors)
  }
  if (raw) return res
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  get: (u) => request('GET', u),
  post: (u, b = {}) => request('POST', u, b),
  patch: (u, b) => request('PATCH', u, b),
  put: (u, b) => request('PUT', u, b),
  raw: (u) => request('GET', u, undefined, { raw: true }),
}

export function qs(params) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => { if (v !== '' && v !== null && v !== undefined) p.set(k, v) })
  const s = p.toString()
  return s ? `?${s}` : ''
}

export async function download(url, fallbackName) {
  const res = await api.raw(url)
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') || ''
  const name = (cd.match(/filename="([^"]+)"/) || [])[1] || fallbackName
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

export const fmt = {
  dt: (s) => s ? new Date(s).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—',
  date: (s) => s ? new Date(s).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '—',
  bytes: (n) => {
    if (!n) return '0 B'
    const u = ['B', 'KB', 'MB', 'GB', 'TB']; let i = 0; let v = n
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
    return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`
  },
  mins: (sec) => sec ? `${Math.round(sec / 60)} min` : '—',
}

export const ROLE_LABEL = { super_admin: 'Super Administrator', reception: 'Reception/Admin', auditor: 'Security/Audit' }
