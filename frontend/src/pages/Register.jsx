import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { Alert, Field, PassCard, useMeta } from '../ui'

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const DEFAULT_HOURS = 4
const EMPTY = { full_name: '', mobile: '', company: '', email: '', host_person: '', department: '', location_id: '',
  purpose: '', visit_date: today(), duration_hours: DEFAULT_HOURS }

export default function Register() {
  const meta = useMeta()
  const nav = useNavigate()
  const [f, setF] = useState(EMPTY)
  const [more, setMore] = useState(false)
  const [err, setErr] = useState('')
  const [created, setCreated] = useState(null)
  const [pass, setPass] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (meta.locations.length && !f.location_id) setF(x => ({ ...x, location_id: meta.locations[0].id }))
    if (meta.durations.length && !meta.durations.includes(Number(f.duration_hours)))
      setF(x => ({ ...x, duration_hours: meta.durations.includes(DEFAULT_HOURS) ? DEFAULT_HOURS : meta.durations[0] }))
  }, [meta]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const payload = () => {
    const p = { full_name: f.full_name, mobile: f.mobile, location_id: Number(f.location_id) || null,
      duration_hours: Number(f.duration_hours) || null }
    if (more) {
      for (const k of ['company', 'email', 'host_person', 'department', 'purpose']) if (f[k].trim()) p[k] = f[k].trim()
      if (f.visit_date) p.visit_date = f.visit_date
    }
    return p
  }

  const submit = async (quick) => {
    setErr(''); setBusy(true)
    try {
      const g = await api.post('/api/guests' + (quick ? '?approve=true' : ''), payload())
      setCreated(g)
      if (g.pass) setPass(g.pass)
    } catch (ex) { setErr(ex.message) }
    setBusy(false)
  }

  const approve = async () => {
    setErr(''); setBusy(true)
    try { setPass(await api.post(`/api/guests/${created.id}/approve`)) } catch (ex) { setErr(ex.message) }
    setBusy(false)
  }

  const reset = () => {
    setF({ ...EMPTY, location_id: meta.locations[0]?.id || '', duration_hours: f.duration_hours })
    setCreated(null); setPass(null); setErr('')
  }

  if (created) {
    return (
      <div>
        <div className="page-head"><h1>{pass ? 'Visitor pass' : 'Request submitted'}</h1></div>
        <Alert>{err}</Alert>
        {!pass ? (
          <div className="card narrow">
            <p><b>{created.full_name}</b> is registered for {created.duration_hours} h at {created.location_code}.</p>
            <p className="muted">The request is pending approval.</p>
            <div className="row">
              <button className="btn primary" onClick={approve} disabled={busy}>Approve & generate QR</button>
              <button className="btn ghost" onClick={() => nav(`/visitors/${created.id}`)}>Open request</button>
              <button className="btn ghost" onClick={reset}>Register another</button>
            </div>
          </div>
        ) : (
          <div>
            <PassCard pass={pass} />
            <div className="row no-print">
              <button className="btn primary" onClick={() => window.print()}>Print pass</button>
              <button className="btn ghost" onClick={reset}>Next visitor</button>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div>
      <div className="page-head"><h1>Register visitor</h1></div>
      <form className="card form-grid" onSubmit={(e) => { e.preventDefault(); submit(true) }}>
        <Alert>{err}</Alert>
        <Field label="Visitor name *"><input autoFocus required value={f.full_name} onChange={set('full_name')} maxLength={120} /></Field>
        <Field label="Mobile number *"><input required type="tel" value={f.mobile} onChange={set('mobile')} placeholder="+91 98xxxxxxxx" maxLength={20} /></Field>
        {meta.locations.length > 1 && (
          <Field label="Office">
            <select value={f.location_id} onChange={set('location_id')}>
              {meta.locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Access duration">
          <div className="seg">
            {meta.durations.map(h => (
              <button type="button" key={h} className={String(f.duration_hours) === String(h) ? 'on' : ''}
                onClick={() => setF({ ...f, duration_hours: h })}>{h} h</button>
            ))}
          </div>
        </Field>
        <div className="form-actions">
          <button type="button" className="btn ghost sm" onClick={() => setMore(m => !m)}>
            {more ? '− Hide optional details' : '+ More details (optional)'}
          </button>
        </div>
        {more && <>
          <Field label="Company / organisation"><input value={f.company} onChange={set('company')} maxLength={160} /></Field>
          <Field label="E-mail"><input type="email" value={f.email} onChange={set('email')} maxLength={160} /></Field>
          <Field label="Person to visit"><input value={f.host_person} onChange={set('host_person')} maxLength={120} /></Field>
          <Field label="Department"><input value={f.department} onChange={set('department')} maxLength={80} /></Field>
          <Field label="Purpose of visit"><input value={f.purpose} onChange={set('purpose')} maxLength={255} /></Field>
          <Field label="Visit date"><input type="date" min={today()} value={f.visit_date} onChange={set('visit_date')} /></Field>
        </>}
        <div className="form-actions row">
          <button className="btn primary" disabled={busy}>Create pass now</button>
          <button type="button" className="btn ghost" disabled={busy} onClick={(e) => { if (e.currentTarget.form.reportValidity()) submit(false) }}>Submit for approval</button>
        </div>
      </form>
    </div>
  )
}
