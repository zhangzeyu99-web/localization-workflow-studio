// Optional, unauthenticated operator attribution for a small shared team.
// There is no account/session system in this product: this is only a
// browser-local nickname sent as the X-Operator request header so a handful
// of key backend actions (run creation, delivery, project deletion) can show
// who did them. No validation, no permissions.

const STORAGE_KEY = 'lws.operatorName'
const MAX_LENGTH = 40

export function getOperatorName(): string {
  try {
    return (window.localStorage.getItem(STORAGE_KEY) || '').trim().slice(0, MAX_LENGTH)
  } catch {
    return ''
  }
}

export function setOperatorName(value: string): void {
  const trimmed = value.trim().slice(0, MAX_LENGTH)
  try {
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // localStorage may be unavailable (private mode, disabled storage); the
    // nickname is a nice-to-have, not a requirement, so fail silently.
  }
}
