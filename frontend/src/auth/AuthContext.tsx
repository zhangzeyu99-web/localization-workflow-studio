import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import * as authApi from './authApi'
import type { AuthMeResponse } from './authApi'
import { onMustChangePassword, onUnauthorized } from './authEvents'

export type AuthGateStatus = 'loading' | 'error' | 'anonymous' | 'must-change-password' | 'authenticated'

export type AuthActionResult = { ok: boolean; detail?: string; stale?: boolean }

export type AuthState = {
  status: AuthGateStatus
  user: AuthMeResponse | null
  authEnabled: boolean
  can: (capability: string) => boolean
  login: (username: string, password: string) => Promise<AuthActionResult>
  register: (username: string, displayName: string, password: string) => Promise<AuthActionResult>
  invalidateAuthActions: () => void
  logout: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<AuthActionResult>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthGateStatus>('loading')
  const [user, setUser] = useState<AuthMeResponse | null>(null)
  const authActionGenerationRef = useRef(0)
  const authActionControllerRef = useRef<AbortController | null>(null)

  const invalidateAuthActions = useCallback(() => {
    authActionGenerationRef.current += 1
    authActionControllerRef.current?.abort()
    authActionControllerRef.current = null
  }, [])

  const startAuthAction = useCallback(() => {
    authActionControllerRef.current?.abort()
    const controller = new AbortController()
    authActionControllerRef.current = controller
    return { controller, generation: ++authActionGenerationRef.current }
  }, [])

  const finishAuthAction = useCallback((controller: AbortController) => {
    if (authActionControllerRef.current === controller) authActionControllerRef.current = null
  }, [])

  const applyMe = useCallback((data: AuthMeResponse | null) => {
    setUser(data)
    if (!data) {
      setStatus('anonymous')
    } else {
      setStatus(data.must_change_password ? 'must-change-password' : 'authenticated')
    }
  }, [])

  const refresh = useCallback(async () => {
    const { controller, generation } = startAuthAction()
    setStatus('loading')
    try {
      const result = await authApi.fetchMe(controller.signal)
      if (generation !== authActionGenerationRef.current) return
      applyMe(result.status === 200 ? result.data || null : null)
    } catch (error) {
      if (generation !== authActionGenerationRef.current || controller.signal.aborted || isAbortError(error)) return
      setUser(null)
      setStatus('error')
    } finally {
      finishAuthAction(controller)
    }
  }, [applyMe, finishAuthAction, startAuthAction])

  useEffect(() => {
    refresh()
  }, [refresh])

  // A later API call (anywhere in the app, long after the initial gate check)
  // coming back 401 means the session died mid-session (expired/revoked) --
  // drop back to the login screen rather than leaving the shell showing
  // stale authenticated UI that every further action will just 401 on.
  useEffect(() => onUnauthorized(() => {
    invalidateAuthActions()
    applyMe(null)
  }), [applyMe, invalidateAuthActions])

  // A 403 "首次登录请先修改密码" can surface from *any* endpoint once the
  // force-password-change gate is active server-side (see main.py's
  // _enforce_authentication), not just from the initial /api/auth/me call.
  useEffect(() => onMustChangePassword(() => {
    setStatus((previous) => (previous === 'anonymous' ? previous : 'must-change-password'))
  }), [])

  const login = useCallback(async (username: string, password: string): Promise<AuthActionResult> => {
    const { controller, generation } = startAuthAction()
    try {
      const result = await authApi.login(username, password, controller.signal)
      if (generation !== authActionGenerationRef.current) return { ok: false, stale: true }
      if (result.status !== 200 || !result.data) {
        return { ok: false, detail: result.detail || '登录失败，请重试。' }
      }
      applyMe(result.data)
      return { ok: true }
    } catch (error) {
      if (generation !== authActionGenerationRef.current || controller.signal.aborted || isAbortError(error)) {
        return { ok: false, stale: true }
      }
      return { ok: false, detail: '网络连接失败，请检查网络后重试。' }
    } finally {
      finishAuthAction(controller)
    }
  }, [applyMe, finishAuthAction, startAuthAction])

  const register = useCallback(async (username: string, displayName: string, password: string): Promise<AuthActionResult> => {
    const { controller, generation } = startAuthAction()
    try {
      const result = await authApi.register(username, displayName, password, controller.signal)
      if (generation !== authActionGenerationRef.current) return { ok: false, stale: true }
      if (result.status === 201 && result.data) {
        applyMe(result.data)
        return { ok: true }
      }
      const detailByStatus: Record<number, string> = {
        403: '当前环境未开放注册，请使用已有账号登录。',
        409: '用户名已存在，请更换后重试。',
        422: '注册信息不符合要求，请检查后重试。',
        429: '注册请求过多，请稍后再试。',
      }
      return { ok: false, detail: detailByStatus[result.status] || '注册服务暂时不可用，请稍后重试。' }
    } catch (error) {
      if (generation !== authActionGenerationRef.current || controller.signal.aborted || isAbortError(error)) {
        return { ok: false, stale: true }
      }
      return { ok: false, detail: '网络连接失败，请检查网络后重试。' }
    } finally {
      finishAuthAction(controller)
    }
  }, [applyMe, finishAuthAction, startAuthAction])

  const logout = useCallback(async () => {
    invalidateAuthActions()
    await authApi.logout()
    applyMe(null)
  }, [applyMe, invalidateAuthActions])

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
    register,
    invalidateAuthActions,
    logout,
    changePassword,
    refresh
  }), [status, user, can, login, register, invalidateAuthActions, logout, changePassword, refresh])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
