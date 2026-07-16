import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import * as authApi from './authApi'
import type { AuthMeResponse } from './authApi'
import { onMustChangePassword, onUnauthorized } from './authEvents'

export type AuthGateStatus = 'loading' | 'error' | 'anonymous' | 'must-change-password' | 'authenticated'

export type AuthActionResult = { ok: boolean; detail?: string }

export type AuthState = {
  status: AuthGateStatus
  user: AuthMeResponse | null
  authEnabled: boolean
  can: (capability: string) => boolean
  login: (username: string, password: string) => Promise<AuthActionResult>
  logout: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<AuthActionResult>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthGateStatus>('loading')
  const [user, setUser] = useState<AuthMeResponse | null>(null)

  const applyMe = useCallback((data: AuthMeResponse | null) => {
    setUser(data)
    if (!data) {
      setStatus('anonymous')
    } else {
      setStatus(data.must_change_password ? 'must-change-password' : 'authenticated')
    }
  }, [])

  const refresh = useCallback(async () => {
    setStatus('loading')
    try {
      const result = await authApi.fetchMe()
      applyMe(result.status === 200 ? result.data || null : null)
    } catch {
      setUser(null)
      setStatus('error')
    }
  }, [applyMe])

  useEffect(() => {
    refresh()
  }, [refresh])

  // A later API call (anywhere in the app, long after the initial gate check)
  // coming back 401 means the session died mid-session (expired/revoked) --
  // drop back to the login screen rather than leaving the shell showing
  // stale authenticated UI that every further action will just 401 on.
  useEffect(() => onUnauthorized(() => applyMe(null)), [applyMe])

  // A 403 "首次登录请先修改密码" can surface from *any* endpoint once the
  // force-password-change gate is active server-side (see main.py's
  // _enforce_authentication), not just from the initial /api/auth/me call.
  useEffect(() => onMustChangePassword(() => {
    setStatus((previous) => (previous === 'anonymous' ? previous : 'must-change-password'))
  }), [])

  const login = useCallback(async (username: string, password: string): Promise<AuthActionResult> => {
    const result = await authApi.login(username, password)
    if (result.status !== 200) return { ok: false, detail: result.detail || '登录失败，请重试。' }
    await refresh()
    return { ok: true }
  }, [refresh])

  const logout = useCallback(async () => {
    await authApi.logout()
    applyMe(null)
  }, [applyMe])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string): Promise<AuthActionResult> => {
    const result = await authApi.changePassword(currentPassword, newPassword)
    if (result.status !== 200) return { ok: false, detail: result.detail || '修改密码失败，请重试。' }
    await refresh()
    return { ok: true }
  }, [refresh])

  const can = useCallback((capability: string): boolean => {
    if (!user) return false
    if (!user.auth_enabled) return true
    return user.capabilities.includes(capability)
  }, [user])

  const value = useMemo<AuthState>(() => ({
    status,
    user,
    authEnabled: user?.auth_enabled ?? false,
    can,
    login,
    logout,
    changePassword,
    refresh
  }), [status, user, can, login, logout, changePassword, refresh])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
