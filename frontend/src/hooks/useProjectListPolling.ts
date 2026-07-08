import { useEffect } from 'react'
import { usePolling } from './usePolling'

// Refreshes the project list every 10s, plus on window focus and on
// visibilitychange-to-visible. Moved verbatim from main.tsx's App component.
export function useProjectListPolling(
  refreshProjects: (selectId?: string) => Promise<void>,
  currentIdRef: { current: string }
) {
  const syncProjectList = () => {
    if (document.hidden) return
    refreshProjects(currentIdRef.current).catch(() => undefined)
  }

  useEffect(() => {
    const onVisibilityChange = () => {
      if (!document.hidden) syncProjectList()
    }
    window.addEventListener('focus', syncProjectList)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('focus', syncProjectList)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  usePolling((isStale) => { if (!isStale()) syncProjectList() }, { intervalMs: 10000, enabled: true }, [])
}
