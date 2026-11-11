import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Alert, Field, Logo } from '../ui'

function PasswordStep({ onDone }) {
  const [f, setF] = useState({ current_password: '', new_password: '', confirm: '' })
  const [err, setErr] = useState('')
  const submit = async (e) => {
    e.preventDefault(); setErr('')
    if (f.new_password !== f.confirm) { setErr('New passwords do not match'); return }
    try { await api.post('/api/auth/password', { current_password: f.current_password, new_password: f.new_password }); onDone() }
    catch (ex) { setErr(ex.message) }
  }
  return (
    <form onSubmit={submit}>
      <h2>Set your password</h2>
      <p className="muted">At least 12 characters, using three of: lowercase, uppercase, digits, symbols.</p>
      <Alert>{err}</Alert>
      <Field label="Current (temporary) password"><input type="password" autoComplete="current-password" required
        value={f.current_password} onChange={e => setF({ ...f, current_password: e.target.value })} /></Field>
      <Field label="New password"><input type="password" autoComplete="new-password" required minLength={12}
        value={f.new_password} onChange={e => setF({ ...f, new_password: e.target.value })} /></Field>
      <Field label="Confirm new password"><input type="password" autoComplete="new-password" required
        value={f.confirm} onChange={e => setF({ ...f, confirm: e.target.value })} /></Field>
      <button className="btn primary block">Save password</button>
    </form>
  )
}

function MfaStep({ onDone }) {
  const [setup, setSetup] = useState(null)
  const [code, setCode] = useState('')
  const [err, setErr] = useState('')
  const start = async () => { setErr(''); try { setSetup(await api.post('/api/auth/mfa/setup')) } catch (ex) { setErr(ex.message) } }
  const confirm = async (e) => {
    e.preventDefault(); setErr('')
    try { await api.post('/api/auth/mfa/confirm', { code: code.replace(/\s/g, '') }); onDone() } catch (ex) { setErr(ex.message) }
  }
  return (
    <div>
      <h2>Set up two-factor authentication</h2>
      <p className="muted">Use Microsoft Authenticator, Google Authenticator or any TOTP app.</p>
      <Alert>{err}</Alert>
      {!setup ? <button className="btn primary block" onClick={start}>Start setup</button> : (
        <form onSubmit={confirm}>
          <div className="center"><img className="qr" src={setup.qr_svg} alt="MFA QR code" /></div>
          <p className="small muted center">Can't scan? Enter this key manually:<br /><code className="mono">{setup.secret}</code></p>
          <Field label="6-digit code from the app"><input inputMode="numeric" maxLength={8} required value={code}
            onChange={e => setCode(e.target.value)} /></Field>
          <button className="btn primary block">Verify and enable</button>
        </form>
      )}
    </div>
  )
}

export default function Setup() {
  const { needs, refresh, logout, user } = useAuth()
  return (
    <div className="login-wrap">
      <div className="card login">
        <div className="login-brand"><Logo size={40} /><div><b>Welcome, {user.full_name}</b><span>Complete your account setup</span></div></div>
        {needs.includes('password') ? <PasswordStep onDone={refresh} /> : needs.includes('mfa') ? <MfaStep onDone={refresh} /> : null}
        <button className="btn ghost sm" onClick={logout}>Sign out</button>
      </div>
    </div>
  )
}
