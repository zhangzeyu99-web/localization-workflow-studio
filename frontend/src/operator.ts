// Unauthenticated operator attribution for a small shared team.
// There is no account/session system in this product: this is only a
// browser-local nickname sent as the X-Operator request header so a handful
// of key backend actions (run creation, delivery, project deletion) can show
// who did them. Cloud AI task starts require a nickname, but it is still not
// authentication and grants no permissions.

const STORAGE_KEY = 'lws.operatorName'
const MAX_LENGTH = 40
const OPEN_EVENT = 'lws:open-operator-identity'
const CHANGE_EVENT = 'lws:operator-identity-changed'

export function getOperatorName(): string {
  try {
    return (window.localStorage.getItem(STORAGE_KEY) || '').trim().slice(0, MAX_LENGTH)
  } catch {
    return ''
  }
}

export function setOperatorName(value: string): boolean {
  const trimmed = value.trim().slice(0, MAX_LENGTH)
  try {
    if (trimmed) {
      window.localStorage.setItem(STORAGE_KEY, trimmed)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
    window.dispatchEvent(new Event(CHANGE_EVENT))
    return getOperatorName() === trimmed
  } catch {
    // localStorage may be unavailable (private mode, disabled storage); the
    // Storage may be unavailable; the backend still enforces cloud task starts.
    return false
  }
}

export function isOperatorRequiredMessage(value: string): boolean {
  return value.includes('请先设置操作人昵称')
}

export function requestOpenOperatorIdentity(): void {
  window.dispatchEvent(new Event(OPEN_EVENT))
}

export function onOpenOperatorIdentityRequest(handler: () => void): () => void {
  window.addEventListener(OPEN_EVENT, handler)
  return () => window.removeEventListener(OPEN_EVENT, handler)
}

export function onOperatorIdentityChange(handler: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, handler)
  return () => window.removeEventListener(CHANGE_EVENT, handler)
}
