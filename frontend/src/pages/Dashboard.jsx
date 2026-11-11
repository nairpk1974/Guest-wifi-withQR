import { useCallback, useEffect, useState } from 'react'
import { api, fmt, qs } from '../api'
import { useAuth } from '../auth'
import { Alert, useMeta } from '../ui'

function Tile({ label, value, sub, tone }) {
  return <div className={`tile ${tone || ''}`}><div className="tile-label">{label}</div><div className="tile-value">{value}</div>{sub && <div className="tile-sub">{sub}</div>}</div>
}

function Bars({ data, labelKey, valueKey, height = 140, every = 1 }) {
  const max = Math.max(1, ...data.map(d => d[valueKey]))
  const w = 100 / Math.max(1, data.length)
  return (
    <div className="bars">
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" role="img" aria-label="chart">
        {data.map((d, i) => {
          const h = (d[valueKey] / max) * (height - 4)
          return <rect key={i} x={i * w + w * 0.15} width={w * 0.7} y={height - h} height={h} rx="0.6" fill="var(--teal)">
            <title>{`${d[labelKey]}: ${d[valueKey]}`}</title></rect>
        })}
      </svg>
      <div className="bars-x">
        {data.map((d, i) => <span key={i} style={{ width: `${w}%` }}>{i % every === 0 ? String(d[labelKey]).slice(-5) : ''}</span>)}
      </div>
    </div>
  )
}

function Status({ ok, label }) {
  const cls = ok === null || ok === undefined ? 'muted' : ok ? 'ok' : 'bad'
  return <span className={`dot ${cls}`}>{label}</span>
}

export default function Dashboard() {
  const { can } = useAuth()
  const meta = useMeta()
  const [loc, setLoc] = useState('')
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api.get('/api/dashboard' + qs({ location_id: loc })).then(r => { setD(r); setErr('') }).catch(e => setErr(e.message))
  }, [loc])
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [load])

  return (
    <div>
      <div className="page-head">
        <h1>Dashboard</h1>
        {can('super_admin', 'auditor') && (
          <select value={loc} onChange={e => setLoc(e.target.value)}>
            <option value="">All locations</option>
            {meta.locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        )}
      </div>
      <Alert>{err}</Alert>
      {d && <>
        <div className="tiles">
          <Tile label="Registered visitors" value={d.totals.registered} />
          <Tile label="Active sessions" value={d.active_sessions} tone="accent" />
          <Tile label="Active · Bangalore" value={d.active_sessions_by_location.BLR || 0} />
          <Tile label="Active · Hyderabad" value={d.active_sessions_by_location.HYD || 0} />
          <Tile label="Pending approval" value={d.totals.pending} tone={d.totals.pending ? 'warn' : ''} />
          <Tile label="Expired" value={d.totals.expired} />
          <Tile label="Rejected" value={d.totals.rejected} />
          <Tile label="Revoked" value={d.totals.revoked} />
          <Tile label="Guest bandwidth (total)" value={fmt.bytes(d.bandwidth.input_octets + d.bandwidth.output_octets)}
            sub={`This month ${fmt.bytes(d.bandwidth.month_octets)}`} />
        </div>
        <div className="grid2">
          <section className="card">
            <h3>Visitors per day (last 30 days)</h3>
            <Bars data={d.daily} labelKey="day" valueKey="count" every={5} />
          </section>
          <section className="card">
            <h3>Visitors per month</h3>
            {d.monthly.length ? <Bars data={d.monthly} labelKey="month" valueKey="count" /> : <p className="muted">No data yet.</p>}
          </section>
        </div>
        <div className="grid2">
          <section className="card">
            <h3>Firewall connectivity</h3>
            <table className="table compact"><thead><tr><th>Site</th><th>Ping</th><th>RADIUS traffic</th><th>Last RADIUS</th></tr></thead>
              <tbody>{d.firewalls.map(f => (
                <tr key={f.id}><td>{f.name}</td>
                  <td><Status ok={f.ping_ok} label={f.ping_ok === null ? 'not configured' : f.ping_ok ? 'reachable' : 'unreachable'} /></td>
                  <td><Status ok={f.radius_recent} label={f.radius_recent ? 'last 30 min' : 'none recently'} /></td>
                  <td className="small">{fmt.dt(f.last_radius_seen_at)}</td></tr>))}
              </tbody></table>
          </section>
          <section className="card">
            <h3>Application server</h3>
            <ul className="status-list">
              <li><Status ok={d.server.api === 'ok'} label="API" /></li>
              <li><Status ok={d.server.database === 'ok'} label="PostgreSQL database" /></li>
              <li><Status ok={d.server.worker_ok} label={`Background worker (last seen ${fmt.dt(d.server.worker_last_seen)})`} /></li>
            </ul>
            <p className="muted small">Refreshes every 30 seconds.</p>
          </section>
        </div>
      </>}
    </div>
  )
}
