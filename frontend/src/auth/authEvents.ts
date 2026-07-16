// Tiny pub-sub (same pattern as components/system/activeJobsPanelBus.ts) so
// the plain apiClient.ts module -- which cannot use React hooks -- can tell
// AuthContext to flip the app-shell gate back to the login/change-password
// screen after any API call comes back 401/"must change password", without
// apiClient needing to import React or AuthContext directly.
type Listener = () => void

let unauthorizedListeners: Listener[] = []
let mustChangePasswordListeners: Listener[] = []

export function broadcastUnauthorized(): void {
  unauthorizedListeners.forEach((listener) => listener())
}

export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners = [...unauthorizedListeners, listener]
  return () => {
    unauthorizedListeners = unauthorizedListeners.filter((item) => item !== listener)
  }
}

export function broadcastMustChangePassword(): void {
  mustChangePasswordListeners.forEach((listener) => listener())
}

export function onMustChangePassword(listener: Listener): () => void {
  mustChangePasswordListeners = [...mustChangePasswordListeners, listener]
  return () => {
    mustChangePasswordListeners = mustChangePasswordListeners.filter((item) => item !== listener)
  }
}
