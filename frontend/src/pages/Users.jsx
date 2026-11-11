import { useCallback, useEffect, useState } from 'react'
import { api, fmt, ROLE_LABEL } from '../api'
import { useAuth } from '../auth'
import { Alert, Field, Modal, useMeta } from '../ui'

const EMPTY = { username: '', full_name: '', email: '', role: 'reception', location_id: '' }

function UserForm({ initial, onSave, onCancel, locations, isNew }) {
  const [f, setF] = useState(initial)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave(f) }}>
      {isNew && <Field label="Username"><input required pattern="[A-Za-z0-9._\-]{3,64}" value={f.username} onChange={set('username')} /></Field>}
      <Field label="Full name"><input required value={f.full_name} onChange={set('full_name')} /></Field>
      <Field label="E-mail"><input type="email" value={f.email || ''} onChange={set('email')} /></Field>
      <Field label="Role"><select value={f.role} onChange={set('role')}>
        {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
      {f.role === 'reception' && (
        <Field label="Location"><select required value={f.location_id || ''} onChange={set('location_id')}><option value="">Select…</option>
          {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}</select></Field>
      )}
      <div className="row"><button className="btn primary">Save</button><button type="button" className="btn ghost" onClick={onCancel}>Cancel</button></div>
    </form>
  )
}

export default function Users() {
  const { user: me } = useAuth()
  const meta = useMeta()
  const [users, setUsers] = useState([])
  const [err, setErr] = useState('')
  const [edit, setEdit] = useState(null)
  const [secret, setSecret] = useState(null)

  const load = useCallback(() => api.get('/api/admin/users').then(setUsers).catch(e => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  const save = async (f) => {
    setErr('')
    const body = { ...f, email: f.email || null, location_id: f.role === 'reception' ? Number(f.location_id) : null }
    try {
      if (edit.isNew) {
        const r = await api.post('/api/admin/users', body)
        setSecret({ username: r.user.username, password: r.temporary_password })
      } else {
        const { username, ...patch } = body
        await api.patch(`/api/admin/users/${edit.user.id}`, patch)
      }
      setEdit(null); load()
    } catch (ex) { setErr(ex.message) }
  }
  const action = async (u, path, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setErr('')
    try {
      const r = await api.post(`/api/admin/users/${u.id}/${path}`)
      if (r.temporary_password) setSecret({ username: u.username, password: r.temporary_password })
      load()
    } catch (ex) { setErr(ex.message) }
  }
  const toggle = async (u) => {
    try { await api.patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active }); load() } catch (ex) { setErr(ex.message) }
  }

  return (
    <div>
      <div className="page-head"><h1>Administrators</h1>
        <button className="btn primary" onClick={() => setEdit({ isNew: true, user: EMPTY })}>Add administrator</button></div>
      <Alert>{err}</Alert>
      <div className="card table-wrap">
        <table className="table">
          <thead><tr><th>User</th><th>Role</th><th>Site</th><th>MFA</th><th>Status</th><th>Last login</th><th></th></tr></thead>
          <tbody>{users.map(u => (
            <tr key={u.id}>
              <td><b>{u.full_name}</b><div className="muted small">{u.username}{u.email ? ` · ${u.email}` : ''}</div></td>
              <td>{ROLE_LABEL[u.role]}</td><td>{u.location_code || 'All'}</td>
              <td>{u.mfa_enabled ? <span className="badge ok">on</span> : <span className="badge warn">off</span>}</td>
              <td>{!u.is_active ? <span className="badge bad">disabled</span> : u.locked_until && new Date(u.locked_until) > new Date() ? <span className="badge bad">locked</span> : <span className="badge ok">active</span>}</td>
              <td className="small">{fmt.dt(u.last_login_at)}</td>
              <td className="actions">
                <button className="btn ghost sm" onClick={() => setEdit({ isNew: false, user: u })}>Edit</button>
                <button className="btn ghost sm" onClick={() => action(u, 'reset-password', `Reset password for ${u.username}? A temporary password will be shown once.`)}>Reset password</button>
                {u.mfa_enabled && <button className="btn ghost sm" onClick={() => action(u, 'reset-mfa', `Reset MFA for ${u.username}?`)}>Reset MFA</button>}
                {u.locked_until && <button className="btn ghost sm" onClick={() => action(u, 'unlock')}>Unlock</button>}
                {u.id !== me.id && <button className={`btn sm ${u.is_active ? 'danger' : 'ghost'}`} onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>}
              </td>
            </tr>))}
          </tbody>
        </table>
      </div>
      {edit && <Modal title={edit.isNew ? 'Add administrator' : `Edit ${edit.user.username}`} onClose={() => setEdit(null)}>
        <UserForm initial={edit.user} isNew={edit.isNew} locations={meta.locations} onSave={save} onCancel={() => setEdit(null)} />
      </Modal>}
      {secret && <Modal title="Temporary password" onClose={() => setSecret(null)}>
        <p>Give this temporary password to <b>{secret.username}</b> securely. It is shown only once; they must change it and enrol MFA at first sign-in.</p>
        <p className="mono big center">{secret.password}</p>
        <button className="btn primary" onClick={() => setSecret(null)}>Done</button>
      </Modal>}
    </div>
  )
}
