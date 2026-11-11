import { useEffect, useState } from 'react'
import { api, download, qs } from '../api'
import { useAuth } from '../auth'
import { Alert, Field, useMeta } from '../ui'

const iso = (d) => d.toISOString().slice(0, 10)

export default function Reports() {
  const { can } = useAuth()
  const meta = useMeta()
  const [kinds, setKinds] = useState([])
  const [kind, setKind] = useState('visitors')
  const [f, setF] = useState({ location_id: '', date_from: iso(new Date(Date.now() - 30 * 864e5)), date_to: iso(new Date()), q: '', mobile: '', status: '' })
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.get('/api/reports').then(setKinds).catch(e => setErr(e.message)) }, [])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const run = async (e) => {
    e?.preventDefault(); setErr(''); setBusy(true)
    try { setData(await api.get(`/api/reports/${kind}` + qs({ ...f, format: 'json' }))) } catch (ex) { setErr(ex.message) }
    setBusy(false)
  }
  const exp = async (format) => {
    setErr('')
    try { await download(`/api/reports/${kind}` + qs({ ...f, format }), `${kind}.${format}`) } catch (ex) { setErr(ex.message) }
  }

  return (
    <div>
      <div className="page-head"><h1>Reports & audit</h1></div>
      <form className="card filters" onSubmit={run}>
        <Field label="Report"><select value={kind} onChange={e => { setKind(e.target.value); setData(null) }}>
          {kinds.map(k => <option key={k.kind} value={k.kind}>{k.title}</option>)}</select></Field>
        {can('super_admin', 'auditor') && (
          <Field label="Location"><select value={f.location_id} onChange={set('location_id')}><option value="">All</option>
            {meta.locations.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}</select></Field>
        )}
        <Field label="From"><input type="date" value={f.date_from} onChange={set('date_from')} /></Field>
        <Field label="To"><input type="date" value={f.date_to} onChange={set('date_to')} /></Field>
        <Field label="Name / text"><input value={f.q} onChange={set('q')} /></Field>
        {['visitors', 'devices', 'logins', 'sessions', 'usage', 'expired-revoked'].includes(kind) && <Field label="Mobile"><input value={f.mobile} onChange={set('mobile')} /></Field>}
        {kind === 'visitors' && <Field label="Status"><select value={f.status} onChange={set('status')}><option value="">Any</option>
          {meta.statuses.map(s => <option key={s} value={s}>{s}</option>)}</select></Field>}
        <div className="filters-actions">
          <button className="btn primary" disabled={busy}>Preview</button>
          <button type="button" className="btn ghost" onClick={() => exp('csv')}>Export CSV</button>
          <button type="button" className="btn ghost" onClick={() => exp('xlsx')}>Export Excel</button>
        </div>
      </form>
      <Alert>{err}</Alert>
      {data && (
        <div className="card table-wrap">
          <h3>{data.title} <span className="muted small">({data.rows.length}{data.truncated ? '+, preview limited to 500 — export for all rows' : ''} rows)</span></h3>
          <table className="table compact">
            <thead><tr>{data.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>
              {data.rows.length === 0 && <tr><td colSpan={data.columns.length} className="muted center">No rows.</td></tr>}
              {data.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v === null ? '' : String(v)}</td>)}</tr>)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
