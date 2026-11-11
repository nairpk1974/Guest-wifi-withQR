import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Alert, Field, Logo } from '../ui'

export default function Login() {
  const { refresh } = useAuth()
  const [form, setForm] = useState({ username: '', password: '' })
  const [ticket, setTicket] = useState(null)
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      if (!ticket) {
        const r = await api.post('/api/auth/login', form)
        if (r.mfa_required) { setTicket(r.ticket); setBusy(false); return }
      } else {
        await api.post('/api/auth/mfa', { ticket, code: code.replace(/\s/g, '') })
      }
      await refresh()
    } catch (ex) {
      setErr(ex.message)
      if (ticket && ex.status === 401 && /expired/i.test(ex.message)) { setTicket(null); setCode('') }
    }
    setBusy(false)
  }

  return (
    <div className="login-wrap">
      <form className="card login" onSubmit={submit}>
        <div className="login-brand"><Logo size={44} /><div><b>Bessel Systems</b><span>Guest Wi-Fi Administration</span></div></div>
        <Alert>{err}</Alert>
        {!ticket ? (
          <>
            <Field label="Username"><input autoFocus autoComplete="username" value={form.username}
              onChange={e => setForm({ ...form, username: e.target.value })} required /></Field>
            <Field label="Password"><input type="password" autoComplete="current-password" value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })} required /></Field>
          </>
        ) : (
          <Field label="Authenticator code" hint="Enter the 6-digit code from your authenticator app.">
            <input autoFocus inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code}
              onChange={e => setCode(e.target.value)} required />
          </Field>
        )}
        <button className="btn primary block" disabled={busy}>{busy ? 'Please wait…' : ticket ? 'Verify' : 'Sign in'}</button>
        <p className="muted small center">Authorised Bessel Systems staff only. All activity is logged.</p>
      </form>
    </div>
  )
}
