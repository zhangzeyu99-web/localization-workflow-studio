export const API = import.meta.env.VITE_API_BASE_URL || ''

export function sanitizeUserFacingError(text: string, fallback = '\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002'): string {
  const raw = String(text || '').trim()
  if (!raw) return fallback
  const unsupported = raw.match(/unsupported file format:\s*(\.\w+)/i)
  if (unsupported) {
    return `\u5f53\u524d\u5165\u53e3\u4e0d\u652f\u6301 ${unsupported[1]} \u6587\u4ef6\u3002\u8bed\u8a00\u5305\u7ffb\u8bd1\u8bf7\u4e0a\u4f20 XLSX/XLS/CSV \u8bed\u8a00\u8868\uff1bTXT/DOCX \u957f\u6587\u672c\u8bf7\u4f7f\u7528\u516c\u544a\u7ffb\u8bd1/\u5916\u6587\u672c\u6d41\u7a0b\u3002`
  }
  if (/another long-text AI job is active/i.test(raw)) {
    return '\u5df2\u6709\u4e00\u4e2a\u957f\u6587\u672c AI \u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u8bf7\u7b49\u5f85\u5b8c\u6210\u6216\u5148\u53d6\u6d88\u540e\u518d\u7ee7\u7eed\u3002'
  }
  if (/Traceback|command failed|python\.exe|run_translation_harness\.py|\bFile "[^\n]+", line/i.test(raw) || /[A-Za-z]:[\\/]/.test(raw)) {
    return '\u672c\u5730 workflow \u6267\u884c\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8f93\u5165\u6587\u4ef6\u683c\u5f0f\u548c\u5f53\u524d\u6b65\u9aa4\u662f\u5426\u5339\u914d\u3002'
  }
  if (/Failed to fetch/i.test(raw)) return '\u8fde\u63a5\u5de5\u4f5c\u53f0\u540e\u7aef\u5931\u8d25\uff0c\u8bf7\u786e\u8ba4\u540e\u7aef\u670d\u52a1\u5df2\u542f\u52a8\u3002'
  const singleLine = raw.replace(/\s+/g, ' ').trim()
  return singleLine.length > 240 ? `${singleLine.slice(0, 237)}...` : singleLine
}

export function apiErrorText(text: string, fallback: string): string {
  if (!text.trim()) return fallback
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown }
    const detail = payload.detail ?? payload.message ?? payload.error
    if (typeof detail === 'string' && detail.trim()) return sanitizeUserFacingError(detail, fallback)
  } catch {
    // Keep the original text when the backend returns plain text.
  }
  return sanitizeUserFacingError(text, fallback)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(apiErrorText(text, response.statusText))
  }
  return response.json()
}
