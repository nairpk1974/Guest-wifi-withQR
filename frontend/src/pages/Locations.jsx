import { useCallback, useEffect, useState } from 'react'
import { api, fmt } from '../api'
import { Alert, Field } from '../ui'

function LocationCard({ loc, onSaved }) {
  const [f, setF] = useState({ ...loc, portal_post_hosts: (loc.portal_post_hosts || []).join(', ') })
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const save = async (e) => {
    e.preventDefault(); setErr(''); setOk('')
    try {
      await api.patch(`/api/admin/locations/${loc.id}`, {
        name: f.name, ssid: f.ssid, enabled: f.enabled, coa_host: f.coa_host || null, coa_port: Number(f.coa_port) || 3799,
        monitor_host: f.monitor_host || null,
        portal_post_hosts: f.portal_post_hosts.split(',').map(s => s.trim()).filter(Boolean),
      })
      setOk('Saved.'); onSaved()
    } catch (ex) { setErr(ex.message) }
  }

  return (
    <form className="card" onSubmit={save}>
      <h3>{loc.name} <span className="muted small">({loc.code} · RADIUS client “{loc.nas_shortname}”)</span></h3>
      <Alert>{err}</Alert><Alert kind="info">{ok}</Alert>
      <div className="form-grid">
        <Field label="Display name"><input value={f.name} onChange={set('name')} /></Field>
        <Field label="Guest SSID"><input value={f.ssid} onChange={set('ssid')} maxLength={32} /></Field>
        <Field label="Captive-portal post hosts" hint="FortiGate guest-interface address(es) the portal may send credentials to, e.g. 10.x.x.1:1000 — confirmed during discovery">
          <input value={f.portal_post_hosts} onChange={set('portal_post_hosts')} placeholder="host:port, host:port" /></Field>
        <Field label="RADIUS CoA/Disconnect host" hint="FortiGate IP that listens on UDP 3799"><input value={f.coa_host || ''} onChange={set('coa_host')} /></Field>
        <Field label="CoA port"><input type="number" value={f.coa_port} onChange={set('coa_port')} /></Field>
        <Field label="Monitor (ping) host"><input value={f.monitor_host || ''} onChange={set('monitor_host')} /></Field>
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={set('enabled')} /> Location enabled</label>
      </div>
      <ul className="status-list small">
        <li>CoA secret in server environment: {loc.coa_secret_configured ? <span className="badge ok">configured</span> : <span className="badge bad">missing</span>}</li>
        <li>Last RADIUS packet: {fmt.dt(loc.last_radius_seen_at)}</li>
        <li>Last successful ping: {fmt.dt(loc.last_ping_ok_at)}</li>
      </ul>
      <button className="btn primary">Save {loc.code}</button>
    </form>
  )
}

export default function Locations() {
  const [locs, setLocs] = useState([])
  const [err, setErr] = useState('')
  const load = useCallback(() => api.get('/api/admin/locations').then(setLocs).catch(e => setErr(e.message)), [])
  useEffect(() => { load() }, [load])
  return (
    <div>
      <div className="page-head"><h1>Locations & firewall integration</h1></div>
      <p className="muted">RADIUS shared secrets and CoA secrets are set in the server's <code>.env</code> file, never here. The application holds no FortiGate administrator credentials.</p>
      <Alert>{err}</Alert>
      <div className="stack">{locs.map(l => <LocationCard key={l.id} loc={l} onSaved={load} />)}</div>
    </div>
  )
}
