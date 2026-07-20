// Thin, deliberately raw fetch wrappers for the /api/auth/* family.
//
// These bypass apiClient.ts's `api()` helper on purpose: `api()` throws a
// sanitized Error on any non-2xx response and discards the HTTP status code,
// but the auth gate needs to branch on the exact status (200 vs 401 vs 403
// vs 429) to decide which screen to show -- so these return a plain
// `{ status, ... }` shape instead of throwing.
import { API } from '../apiClient'

export type AuthMeResponse = {
  id: string
  username: string
  display_name: string
  role: string
  must_change_password: boolean
  auth_enabled: boolean
  capabilities: string[]
}

type AuthResult<T> = { status: number; data?: T; detail?: string }

async function authFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API}${path}`, { ...init, credentials: 'include' })
}

async function readDetail(response: Response): Promise<string> {
  try {
    const payload = await response.json() as { detail?: unknown }
    return typeof payload.detail === 'string' ? payload.detail : ''
  } catch {
    return ''
  }
}

export async function fetchMe(): Promise<AuthResult<AuthMeResponse>> {
  const response = await authFetch('/api/auth/me')
  if (response.ok) return { status: response.status, data: await response.json() }
  return { status: response.status, detail: await readDetail(response) }
}

export async function login(username: string, password: string): Promise<AuthResult<AuthMeResponse>> {
  const response = await authFetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
  if (response.ok) return { status: response.status, data: await response.json() }
  return { status: response.status, detail: await readDetail(response) }
}

export async function register(username: string, displayName: string, password: string): Promise<AuthResult<AuthMeResponse>> {
  const response = await authFetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, display_name: displayName, password })
  })
  if (response.ok) return { status: response.status, data: await response.json() }
  return { status: response.status, detail: await readDetail(response) }
}

export async function logout(): Promise<void> {
  await authFetch('/api/auth/logout', { method: 'POST' })
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<AuthResult<{ ok: boolean }>> {
  const response = await authFetch('/api/auth/change-password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
  })
  if (response.ok) return { status: response.status, data: await response.json() }
  return { status: response.status, detail: await readDetail(response) }
}
