import { useEffect } from 'react'
import { usePolling } from './usePolling'

// Refreshes the project list every 10s, plus on window focus and on
// visibilitychange-to-visible. Moved verbatim from main.tsx's App component.
export function useProjectListPolling(
  refreshProjects: (selectId?: string, signal?: AbortSignal) => Promise<void>,
  currentIdRef: { current: string }
) {
  const syncProjectList = (signal?: AbortSignal) => {
    if (document.hidden) return
    refreshProjects(currentIdRef.current, signal).catch(() => undefined)
  }

  useEffect(() => {
    const onFocus = () => syncProjectList()
    const onVisibilityChange = () => {
      if (!document.hidden) syncProjectList()
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  usePolling((isStale, signal) => { if (!isStale()) syncProjectList(signal) }, { intervalMs: 10000, enabled: true }, [])
}
