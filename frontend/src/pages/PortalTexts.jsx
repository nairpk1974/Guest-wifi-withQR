import { useEffect, useState } from 'react'
import { api } from '../api'
import { Alert, Field } from '../ui'

export default function PortalTexts() {
  const [f, setF] = useState(null)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  useEffect(() => { api.get('/api/admin/settings').then(setF).catch(e => setErr(e.message)) }, [])
  const save = async (e) => {
    e.preventDefault(); setErr(''); setOk('')
    try { setF(await api.put('/api/admin/settings', f)); setOk('Saved. Guests see the new text immediately.') } catch (ex) { setErr(ex.message) }
  }
  return (
    <div>
      <div className="page-head"><h1>Guest portal terms & privacy notice</h1></div>
      <p className="muted">Have the final wording reviewed by Bessel Systems' legal/compliance team before go-live.</p>
      <Alert>{err}</Alert><Alert kind="info">{ok}</Alert>
      {f && <form className="card" onSubmit={save}>
        <Field label="Terms of use"><textarea rows={12} value={f.terms_text} onChange={e => setF({ ...f, terms_text: e.target.value })} /></Field>
        <Field label="Privacy notice"><textarea rows={10} value={f.privacy_text} onChange={e => setF({ ...f, privacy_text: e.target.value })} /></Field>
        <button className="btn primary">Save</button>
      </form>}
    </div>
  )
}
