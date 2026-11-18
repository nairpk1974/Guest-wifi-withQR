import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt, qs } from '../api'
import { Alert, Field, Modal, Pager, PassCard, StatusBadge, useMeta } from '../ui'
import { GuestDetail } from './Visitors'

const EMPTY = { full_name: '', mobile: '', company: '', email: '', department: '', purpose: '', location_id: '', valid_until: '' }
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)

function CreateForm({ meta, onCreated, onClose }) {
  const [f, setF] = useState({ ...EMPTY, location_id: meta.locations[0]?.id || '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [pass, setPass] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault(); setErr(''); setBusy(true)
    const body = { full_name: f.full_name, mobile: f.mobile, location_id: Number(f.location_id) }
    for (const k of ['company', 'email', 'department', 'purpose']) if (f[k].trim()) body[k] = f[k].trim()
    if (f.valid_until) body.valid_until = f.valid_until
    try { const g = await api.post('/api/permanent-codes', body); setPass(g.pass); onCreated() } catch (ex) { setErr(ex.message) }
    setBusy(false)
  }

  return (
    <Modal title={pass ? 'Permanent code created' : 'New permanent Wi-Fi code'} onClose={onClose} wide>
      <Alert>{err}</Alert>
      {pass ? (
        <div>
          <PassCard pass={pass} />
          <div className="row no-print">
            <button className="btn primary" onClick={() => window.print()}>Print</button>
            <button className="btn ghost" onClick={onClose}>Done</button>
          </div>
        </div>
      ) : (
        <form className="form-grid" onSubmit={submit}>
          <Field label="Person's name *"><input autoFocus required maxLength={120} value={f.full_name} onChange={set('full_name')} /></Field>
          <Field label="Mobile number *"><input required type="tel" maxLength={20} placeholder="+91 98xxxxxxxx" value={f.mobile} onChange={set('mobile')} /></Field>
          <Field label="Office *">
            <select required value={f.location_id} onChange={set('location_id')}>
              {meta.locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </Field>
          <Field label="Valid until" hint="Leave empty: valid until you revoke it">
            <input type="date" min={today()} value={f.valid_until} onChange={set('valid_until')} />
          </Field>
          <Field label="Company / organisation"><input maxLength={160} value={f.company} onChange={set('company')} /></Field>
          <Field label="E-mail"><input type="email" maxLength={160} value={f.email} onChange={set('email')} /></Field>
          <Field label="Department"><input maxLength={80} value={f.department} onChange={set('department')} /></Field>
          <Field label="Note (why this person has a permanent code)"><input maxLength={255} value={f.purpose} onChange={set('purpose')} /></Field>
          <p className="muted small form-actions">The code works on any number of the person's devices until it is revoked or the end date passes. Revoking disconnects every device immediately.</p>
          <div className="form-actions row">
            <button className="btn primary" disabled={busy}>Create code</button>
            <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          </div>
        </form>
      )}
    </Modal>
  )
}

export default function PermanentCodes() {
  const { id } = useParams()
  const nav = useNavigate()
  const meta = useMeta()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('approved,active')
  const [applied, setApplied] = useState({ q: '', status: 'approved,active' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], total: 0, page_size: 25 })
  const [err, setErr] = useState('')
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => {
    api.get('/api/guests' + qs({ ...applied, kind: 'permanent', page, page_size: 25 })).then(setData).catch(e => setErr(e.message))
  }, [applied, page])
  useEffect(() => { load() }, [load])

  return (
    <div>
      <div className="page-head">
        <h1>Permanent Wi-Fi codes</h1>
        <button className="btn primary" onClick={() => setCreating(true)} disabled={!meta.locations.length}>+ New permanent code</button>
      </div>
      <form className="card filters" onSubmit={(e) => { e.preventDefault(); setPage(1); setApplied({ q, status }) }}>
        <Field label="Name / company"><input value={q} onChange={e => setQ(e.target.value)} /></Field>
        <Field label="Show"><select value={status} onChange={e => setStatus(e.target.value)}>
          <option value="approved,active">Valid codes</option>
          <option value="revoked,expired">Revoked / expired</option>
          <option value="">All</option>
        </select></Field>
        <div className="filters-actions"><button className="btn primary">Apply</button></div>
      </form>
      <Alert>{err}</Alert>
      <div className="card table-wrap">
        <table className="table">
          <thead><tr><th>Person</th><th>Mobile</th><th>Site</th><th>Valid until</th><th>First used</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>
            {data.items.length === 0 && <tr><td colSpan={7} className="muted center">No permanent codes.</td></tr>}
            {data.items.map(g => (
              <tr key={g.id} className="click" onClick={() => nav(`/permanent/${g.id}`)}>
                <td><b>{g.full_name}</b><div className="muted small">{[g.company, g.department].filter(v => v && v !== '-').join(' · ')}</div></td>
                <td>{g.mobile}</td><td>{g.location_code}</td>
                <td>{g.valid_until ? fmt.date(g.valid_until) : <span className="muted">until revoked</span>}</td>
                <td className="small">{g.access_started_at ? fmt.dt(g.access_started_at) : <span className="muted">not used</span>}</td>
                <td><StatusBadge status={g.status} /></td>
                <td className="small">{fmt.dt(g.created_at)}<div className="muted">{g.created_by}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
      </div>
      {creating && <CreateForm meta={meta} onCreated={load} onClose={() => setCreating(false)} />}
      {id && <GuestDetail id={id} onClose={() => nav('/permanent')} onChanged={load} />}
    </div>
  )
}
