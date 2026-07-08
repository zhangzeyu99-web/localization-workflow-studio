import { runArtifacts } from '../domain/artifacts'
import { latestProjectActivityRun, projectRunStatusText } from '../domain/projectActivity'
import { getTranslationProgress } from '../domain/translationFlow'
import type { Project, Run } from '../types'
import { usePolling } from './usePolling'

// Every 6s while a project is open, checks whether its latest activity run
// is still active (or just finished failing) and syncs `latestRun`/`busy`/
// `status` accordingly. Moved verbatim from main.tsx's App component.
//
// `pause` disables this poller while a more specific poller already covers
// the same snapshot: the 2s run-status poller handles an active translation/
// QA run (and refreshes the project via `refreshCurrent` once it finishes),
// and the announcement-task poller already calls `refreshProjectSnapshot`
// itself. Skipping this poller in those windows removes duplicate
// `/api/projects/:id` calls without changing eventual consistency.
export function useProjectSnapshotPolling(
  currentId: string,
  currentIdRef: { current: string },
  refreshProjectSnapshot: (projectId: string, signal?: AbortSignal) => Promise<Project | null>,
  isCurrentProject: (projectId?: string | null) => boolean,
  setLatestRun: (run: Run | null) => void,
  setBusy: (value: boolean) => void,
  setStatus: (message: string) => void,
  pause: boolean
) {
  usePolling(async (isStale, signal) => {
    const loaded = await refreshProjectSnapshot(currentIdRef.current, signal)
    if (isStale()) return
    const activeRun = latestProjectActivityRun(loaded || undefined)
    if (!activeRun || !isCurrentProject(activeRun.project_id)) return
    const progress = getTranslationProgress(activeRun)
    if (['queued', 'running'].includes(activeRun.status)) {
      setLatestRun({ ...activeRun, artifacts: runArtifacts(loaded!, activeRun.id) })
      setBusy(true)
      setStatus(`后台任务处理中：${projectRunStatusText(activeRun)}`)
    } else if (progress && progress.completed_rows >= progress.total_rows && activeRun.status === 'failed') {
      setLatestRun({ ...activeRun, artifacts: runArtifacts(loaded!, activeRun.id) })
      setBusy(false)
      setStatus(`后台任务已结束但未通过 QA：${projectRunStatusText(activeRun)}`)
    }
  }, { intervalMs: 6000, enabled: Boolean(currentId) && !pause, skipWhenHidden: true }, [currentId, pause])
}
