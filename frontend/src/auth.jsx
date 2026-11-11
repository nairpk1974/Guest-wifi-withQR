import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, setCsrf, setUnauthorizedHandler } from './api'

const AuthCtx = createContext(null)

export function AuthProvider({ children }) {
  const [state, setState] = useState({ loading: true, user: null, stage: null, needs: [] })

  const refresh = useCallback(async () => {
    try {
      const me = await api.get('/api/auth/me')
      setCsrf(me.csrf_token)
      setState({ loading: false, user: me.user, stage: me.stage, needs: me.needs })
    } catch {
      setCsrf('')
      setState({ loading: false, user: null, stage: null, needs: [] })
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setState({ loading: false, user: null, stage: null, needs: [] }))
    refresh()
  }, [refresh])

  const logout = async () => {
    try { await api.post('/api/auth/logout') } catch { /* already gone */ }
    setCsrf('')
    setState({ loading: false, user: null, stage: null, needs: [] })
  }

  const can = (...roles) => !!state.user && roles.includes(state.user.role)

  return <AuthCtx.Provider value={{ ...state, refresh, logout, can }}>{children}</AuthCtx.Provider>
}

export const useAuth = () => useContext(AuthCtx)
