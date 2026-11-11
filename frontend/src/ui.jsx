import { useEffect, useState } from 'react'
import { api } from './api'

export function Logo({ size = 34 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <path d="M20 3 35 11.5v17L20 37 5 28.5v-17z" fill="#0b3d5c" />
      <path d="M12 19a11 11 0 0 1 16 0M15 22.5a6.5 6.5 0 0 1 10 0" stroke="#3ec5c0" strokeWidth="2.4" fill="none" strokeLinecap="round" />
      <circle cx="20" cy="26.5" r="2.2" fill="#3ec5c0" />
    </svg>
  )
}

const STATUS_CLASS = { pending: 'warn', approved: 'info', active: 'ok', expired: 'muted', rejected: 'bad', revoked: 'bad' }
export function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_CLASS[status] || ''}`}>{status}</span>
}

export function Alert({ kind = 'error', children }) {
  if (!children) return null
  return <div className={`alert ${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</div>
}

export function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="muted">{hint}</small>}
    </label>
  )
}

export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <div className="modal-head"><h2>{title}</h2><button className="btn ghost sm" onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
  )
}

export function useMeta() {
  const [meta, setMeta] = useState({ locations: [], durations: [], statuses: [] })
  useEffect(() => { api.get('/api/meta').then(setMeta).catch(() => {}) }, [])
  return meta
}

export function PassCard({ pass }) {
  return (
    <div className="pass printable">
      <div className="pass-head"><Logo size={30} /><div><b>Bessel Systems</b><span>Guest Wi-Fi pass</span></div></div>
      <div className="pass-name">{pass.guest_name}<small>{pass.company}</small></div>
      <div className="pass-grid">
        <div>
          <div className="step">1 · Join Wi-Fi</div>
          <img src={pass.wifi_qr_svg} alt={`Wi-Fi QR for ${pass.ssid}`} />
          <div className="mono">{pass.ssid}</div>
        </div>
        <div>
          <div className="step">2 · Scan to connect</div>
          <img src={pass.qr_svg} alt="Access QR code" />
          <div className="mono big">{pass.access_code}</div>
          <small>or enter this code on the sign-in page</small>
        </div>
      </div>
      <ul className="pass-meta">
        <li>{pass.location} · valid on {pass.visit_date}</li>
        <li>Access lasts <b>{pass.duration_hours} h</b> from first sign-in</li>
        <li>Use before {new Date(pass.redeem_before).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</li>
        <li>Works on one device only. Do not share.</li>
      </ul>
    </div>
  )
}

export function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="pager">
      <span className="muted small">{total} record{total === 1 ? '' : 's'}</span>
      <button className="btn ghost sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Prev</button>
      <span className="small">Page {page} / {pages}</span>
      <button className="btn ghost sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
    </div>
  )
}
