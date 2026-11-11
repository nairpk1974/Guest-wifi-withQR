import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, fmt, qs } from '../api'
import { useAuth } from '../auth'
import { Alert, Field, Modal, Pager, PassCard, StatusBadge, useMeta } from '../ui'

const EMPTY = { location_id: '', q: '', mobile: '', date_from: '', date_to: '', status: '', approval: '' }

function GuestDetail({ id, onClose, onChanged }) {
  const { can } = useAuth()
  const [g, setG] = useState(null)
  const [pass, setPass] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState(null) // 'reject' | 'revoke'
  const staff = can('super_admin', 'reception')

  const load = useCallback(() => api.get(`/api/guests/${id}`).then(setG).catch(e => setErr(e.message)), [id])
  useEffect(() => { load() }, [load])

  const act = async (fn) => {
    setErr(''); setMsg('')
    try { await fn(); await load(); onChanged() } catch (ex) { setErr(ex.message) }
  }
  const approve = () => act(async () => setPass(await api.post(`/api/guests/${id}/approve`)))
  const reissue = () => act(async () => setPass(await api.post(`/api/guests/${id}/reissue`)))
  const showPass = () => act(async () => setPass(await api.get(`/api/guests/${id}/pass`)))
  const email = () => act(async () => { await api.post(`/api/guests/${id}/pass/email`); setMsg('Pass e-mailed to visitor.') })
  const withReason = (e) => {
    e.preventDefault()
    act(async () => {
      const r = await api.post(`/api/guests/${id}/${mode}`, { reason })
      if (mode === 'revoke') {
        const res = r.disconnect_results || []
        setMsg(res.length ? `Access revoked. Firewall disconnect: ${res.join(', ')}` : 'Access revoked. No live session to disconnect.')
      }
      setMode(null); setReason('')
    })
  }

  return (
    <Modal title="Visitor details" onClose={onClose} wide>
      <Alert>{err}</Alert>
      <Alert kind="info">{msg}</Alert>
      {!g ? <p className="muted">Loading…</p> : pass ? (
        <div>
          <PassCard pass={pass} />
          <div className="row no-print">
            <button className="btn primary" onClick={() => window.print()}>Print pass</button>
            {g.email && !pass.redeemed && <button className="btn ghost" onClick={email}>E-mail pass</button>}
            <button className="btn ghost" onClick={() => setPass(null)}>Back to details</button>
          </div>
        </div>
      ) : (
        <div>
          <div className="detail-head">
            <div><h2>{g.full_name}</h2><div className="muted">{g.company} · {g.mobile}{g.email ? ` · ${g.email}` : ''}</div></div>
            <StatusBadge status={g.status} />
          </div>
          <dl className="kv">
            <dt>Location</dt><dd>{g.location_code}</dd>
            <dt>Visiting</dt><dd>{g.host_person} ({g.department})</dd>
            <dt>Purpose</dt><dd>{g.purpose}</dd>
            <dt>Visit date</dt><dd>{fmt.date(g.visit_date)}</dd>
            <dt>Duration</dt><dd>{g.duration_hours} h</dd>
            <dt>Registered</dt><dd>{fmt.dt(g.created_at)} by {g.created_by || '—'}</dd>
            <dt>Decision</dt><dd>{g.decided_at ? `${fmt.dt(g.decided_at)} by ${g.decided_by}` : '—'}{g.rejection_reason ? ` · ${g.rejection_reason}` : ''}</dd>
            <dt>QR redeemed</dt><dd>{fmt.dt(g.redeemed_at)}</dd>
            <dt>Access</dt><dd>{g.access_started_at ? `${fmt.dt(g.access_started_at)} → ${fmt.dt(g.access_expires_at)}` : 'not started'}</dd>
            {g.revoked_at && <><dt>Revoked</dt><dd>{fmt.dt(g.revoked_at)} by {g.revoked_by} · {g.revoke_reason}</dd></>}
          </dl>
          {staff && (
            <div className="row">
              {g.status === 'pending' && <><button className="btn primary" onClick={approve}>Approve & generate QR</button>
                <button className="btn danger" onClick={() => setMode('reject')}>Reject</button></>}
              {g.pass_available && <button className="btn" onClick={showPass}>Show / print pass</button>}
              {g.status === 'approved' && <button className="btn ghost" onClick={reissue}>Re-issue QR</button>}
              {['approved', 'active'].includes(g.status) && <button className="btn danger" onClick={() => setMode('revoke')}>Revoke access now</button>}
            </div>
          )}
          {mode && (
            <form className="inline-form" onSubmit={withReason}>
              <Field label={mode === 'reject' ? 'Reason for rejection' : 'Reason for revocation'}>
                <input autoFocus required minLength={2} maxLength={255} value={reason} onChange={e => setReason(e.target.value)} />
              </Field>
              <button className="btn danger">{mode === 'reject' ? 'Reject request' : 'Revoke & disconnect'}</button>
              <button type="button" className="btn ghost" onClick={() => setMode(null)}>Cancel</button>
            </form>
          )}
          <h3>Sessions</h3>
          {g.sessions.length === 0 ? <p className="muted small">No firewall sessions recorded.</p> : (
            <div className="table-wrap"><table className="table compact"><thead><tr><th>Started</th><th>Ended</th><th>IP / MAC</th><th>Down / Up</th><th>Cause</th></tr></thead>
              <tbody>{g.sessions.map(s => <tr key={s.id}><td>{fmt.dt(s.started_at)}</td><td>{s.stopped_at ? fmt.dt(s.stopped_at) : <span className="badge ok">live</span>}</td>
                <td className="mono small">{s.client_ip}<br />{s.client_mac}</td><td>{fmt.bytes(s.output_octets)} / {fmt.bytes(s.input_octets)}</td><td>{s.terminate_cause || ''}</td></tr>)}</tbody></table></div>
          )}
          <h3>Authentication events</h3>
          {g.auth_events.length === 0 ? <p className="muted small">None.</p> : (
            <div className="table-wrap"><table className="table compact"><thead><tr><th>Time</th><th>Source</th><th>Result</th><th>Reason</th><th>Client IP</th></tr></thead>
              <tbody>{g.auth_events.map((e, i) => <tr key={i}><td>{fmt.dt(e.ts)}</td><td>{e.source}</td>
                <td><span className={`badge ${e.result === 'accept' ? 'ok' : 'bad'}`}>{e.result}</span></td><td>{e.reason}</td><td className="mono small">{e.client_ip}</td></tr>)}</tbody></table></div>
          )}
        </div>
      )}
    </Modal>
  )
}

export default function Visitors() {
  const { id } = useParams()
  const nav = useNavigate()
  const { can } = useAuth()
  const meta = useMeta()
  const [filters, setFilters] = useState(EMPTY)
  const [applied, setApplied] = useState({ ...EMPTY, approval: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], total: 0, page_size: 25 })
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api.get('/api/guests' + qs({ ...applied, page, page_size: 25 })).then(setData).catch(e => setErr(e.message))
  }, [applied, page])
  useEffect(() => { load() }, [load])

  const set = (k) => (e) => setFilters({ ...filters, [k]: e.target.value })
  const apply = (e) => { e.preventDefault(); setPage(1); setApplied(filters) }
  const quick = (approval) => { const f = { ...EMPTY, approval }; setFilters(f); setApplied(f); setPage(1) }

  return (
    <div>
      <div className="page-head">
        <h1>Visitors & approvals</h1>
        <div className="row">
          <button className={`btn sm ${applied.approval === 'pending' ? 'primary' : 'ghost'}`} onClick={() => quick('pending')}>Pending approval</button>
          <button className={`btn sm ${applied.approval === '' && !applied.status ? 'primary' : 'ghost'}`} onClick={() => quick('')}>All</button>
        </div>
      </div>
      <form className="card filters" onSubmit={apply}>
        {can('super_admin', 'auditor') && (
          <Field label="Location"><select value={filters.location_id} onChange={set('location_id')}>
            <option value="">All</option>{meta.locations.map(l => <option key={l.id} value={l.id}>{l.code}</option>)}</select></Field>
        )}
        <Field label="Visitor / company / host"><input value={filters.q} onChange={set('q')} /></Field>
        <Field label="Mobile"><input value={filters.mobile} onChange={set('mobile')} /></Field>
        <Field label="From"><input type="date" value={filters.date_from} onChange={set('date_from')} /></Field>
        <Field label="To"><input type="date" value={filters.date_to} onChange={set('date_to')} /></Field>
        <Field label="Access status"><select value={filters.status} onChange={set('status')}>
          <option value="">Any</option>{meta.statuses.map(s => <option key={s} value={s}>{s}</option>)}</select></Field>
        <Field label="Approval"><select value={filters.approval} onChange={set('approval')}>
          <option value="">Any</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></Field>
        <div className="filters-actions"><button className="btn primary">Apply</button>
          <button type="button" className="btn ghost" onClick={() => { setFilters(EMPTY); setApplied(EMPTY); setPage(1) }}>Clear</button></div>
      </form>
      <Alert>{err}</Alert>
      <div className="card table-wrap">
        <table className="table">
          <thead><tr><th>Visitor</th><th>Mobile</th><th>Host</th><th>Site</th><th>Visit date</th><th>Duration</th><th>Status</th><th>Expires</th></tr></thead>
          <tbody>
            {data.items.length === 0 && <tr><td colSpan={8} className="muted center">No visitors match the filters.</td></tr>}
            {data.items.map(g => (
              <tr key={g.id} className="click" onClick={() => nav(`/visitors/${g.id}`)}>
                <td><b>{g.full_name}</b><div className="muted small">{g.company}</div></td>
                <td>{g.mobile}</td><td>{g.host_person}</td><td>{g.location_code}</td><td>{fmt.date(g.visit_date)}</td>
                <td>{g.duration_hours} h</td><td><StatusBadge status={g.status} /></td><td className="small">{fmt.dt(g.access_expires_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <Pager page={page} pageSize={data.page_size} total={data.total} onPage={setPage} />
      </div>
      {id && <GuestDetail id={id} onClose={() => nav('/visitors')} onChanged={load} />}
    </div>
  )
}
