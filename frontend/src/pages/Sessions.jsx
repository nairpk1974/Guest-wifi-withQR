import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmt, qs } from '../api'
import { useAuth } from '../auth'
import { Alert, useMeta } from '../ui'

export default function Sessions() {
  const { can } = useAuth()
  const meta = useMeta()
  const [loc, setLoc] = useState('')
  const [active, setActive] = useState(true)
  const [data, setData] = useState({ items: [], total: 0 })
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    api.get('/api/sessions' + qs({ location_id: loc, active, page_size: 200 })).then(setData).catch(e => setErr(e.message))
  }, [loc, active])
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [load])

  const disconnect = async (s) => {
    if (!window.confirm(`Disconnect ${s.guest_name || s.username} now? (Use Revoke on the visitor to block re-login.)`)) return
    setErr(''); setMsg('')
    try { const r = await api.post(`/api/sessions/${s.id}/disconnect`); setMsg(`Disconnect: ${r.results.join(', ')}`); load() }
    catch (ex) { setErr(ex.message) }
  }

  return (
    <div>
      <div className="page-head">
        <h1>{active ? 'Active sessions' : 'All sessions'}</h1>
        <div className="row">
          {can('super_admin', 'auditor') && (
            <select value={loc} onChange={e => setLoc(e.target.value)}><option value="">All locations</option>
              {meta.locations.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}</select>
          )}
          <label className="check"><input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)} /> Live only</label>
        </div>
      </div>
      <Alert>{err}</Alert><Alert kind="info">{msg}</Alert>
      <div className="card table-wrap">
        <table className="table">
          <thead><tr><th>Guest</th><th>Site</th><th>Client</th><th>Started</th><th>Last update</th><th>Download</th><th>Upload</th><th></th></tr></thead>
          <tbody>
            {data.items.length === 0 && <tr><td colSpan={8} className="muted center">No sessions.</td></tr>}
            {data.items.map(s => (
              <tr key={s.id}>
                <td>{s.guest_id ? <Link to={`/visitors/${s.guest_id}`}>{s.guest_name}</Link> : s.username}<div className="muted small">{[s.mobile, s.company].filter(Boolean).join(" · ")}</div></td>
                <td>{s.location_code}</td>
                <td className="mono small">{s.client_ip}<br />{s.client_mac}</td>
                <td className="small">{fmt.dt(s.started_at)}</td>
                <td className="small">{s.stopped_at ? `ended ${fmt.dt(s.stopped_at)}` : fmt.dt(s.last_update_at)}</td>
                <td>{fmt.bytes(s.output_octets)}</td><td>{fmt.bytes(s.input_octets)}</td>
                <td>{!s.stopped_at && can('super_admin', 'reception') && <button className="btn danger sm" onClick={() => disconnect(s)}>Disconnect</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="pager"><span className="muted small">{data.total} session(s) · refreshes every 30 s</span></div>
      </div>
    </div>
  )
}
