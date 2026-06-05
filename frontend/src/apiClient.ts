export const API = import.meta.env.VITE_API_BASE_URL || ''

export function apiErrorText(text: string, fallback: string): string {
  if (!text.trim()) return fallback
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown }
    const detail = payload.detail ?? payload.message ?? payload.error
    if (typeof detail === 'string' && detail.trim()) return detail
  } catch {
    // Keep the original text when the backend returns plain text.
  }
  return text
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(apiErrorText(text, response.statusText))
  }
  return response.json()
}
