import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Alert } from '../ui'

const DEFAULT_HOURS = 4
const waited = (s) => s < 60 ? `${s}s` : `${Math.floor(s / 60)} min`

function RequestRow({ r, durations, onDone }) {
  const [hours, setHours] = useState(durations.includes(DEFAULT_HOURS) ? DEFAULT_HOURS : durations[0])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const act = async (fn) => {
    setBusy(true); setErr('')
    try { await fn(); onDone() } catch (ex) { setErr(ex.message); setBusy(false) }
  }
  const approve = () => act(() => api.post(`/api/guests/${r.id}/approve`, { duration_hours: hours }))
  const reject = () => {
    const reason = window.prompt(`Reason for declining ${r.full_name}?`, 'Not a registered visitor')
    if (reason === null) return
    act(() => api.post(`/api/guests/${r.id}/reject`, { reason: reason.trim().length >= 2 ? reason.trim() : 'Declined' }))
  }

  return (
    <div className="card request">
      <div className="request-main">
        <div>
          <h3>{r.full_name}</h3>
          <div className="muted">{r.mobile} · {r.location_code}</div>
          <div className="small"><b>{r.device || 'Unknown device'}</b> <span className="mono muted">{r.client_ip}</span></div>
          <div className="small muted" title={r.user_agent || ''}>Waiting {waited(r.waiting_seconds)}</div>
        </div>
        <div className="request-actions">
          <div className="seg">
            {durations.map(h => (
              <button type="button" key={h} className={hours === h ? 'on' : ''} onClick={() => setHours(h)} disabled={busy}>{h} h</button>
            ))}
          </div>
          <div className="row">
            <button className="btn primary" onClick={approve} disabled={busy}>Approve {hours} h</button>
            <button className="btn danger" onClick={reject} disabled={busy}>Decline</button>
          </div>
        </div>
      </div>
      <Alert>{err}</Alert>
    </div>
  )
}

export default function Requests() {
  const [data, setData] = useState({ items: [], durations: [], window_minutes: 30 })
  const [err, setErr] = useState('')
  const [updated, setUpdated] = useState(null)

  const load = useCallback(() => {
    api.get('/api/requests').then(d => { setData(d); setErr(''); setUpdated(new Date()) }).catch(e => setErr(e.message))
  }, [])
  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  return (
    <div>
      <div className="page-head">
        <h1>Wi-Fi requests</h1>
        <span className="muted small">Live · refreshes every 5 s{updated ? ` · ${updated.toLocaleTimeString('en-IN')}` : ''}</span>
      </div>
      <p className="muted">Guests who tapped <b>Request access</b> on the Wi-Fi sign-in page. When you approve, their device connects automatically within a few seconds.
        Requests not answered within {data.window_minutes} minutes are cancelled. To cut someone off later, use <Link to="/sessions">Active sessions</Link> (disconnect) or revoke the visitor.</p>
      <Alert>{err}</Alert>
      {data.items.length === 0 ? (
        <div className="card muted center">No one is waiting.</div>
      ) : data.items.map(r => <RequestRow key={r.id} r={r} durations={data.durations} onDone={load} />)}
    </div>
  )
}
