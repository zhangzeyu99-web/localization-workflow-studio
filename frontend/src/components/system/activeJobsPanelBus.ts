// Tiny pub-sub so any inline error renderer (ActionStatus, 8+ call sites) can
// ask the header's active-jobs panel to open without prop-drilling a
// callback through every wizard/tab component between main.tsx and the
// error line. main.tsx subscribes once and owns the actual open/close state.
type Listener = () => void

let listeners: Listener[] = []

export function requestOpenActiveJobsPanel(): void {
  listeners.forEach((listener) => listener())
}

export function onOpenActiveJobsPanelRequest(listener: Listener): () => void {
  listeners = [...listeners, listener]
  return () => {
    listeners = listeners.filter((item) => item !== listener)
  }
}
