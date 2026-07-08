import { announcementTaskStatusText } from '../appText'
import type { Project } from '../types'
import { usePolling } from './usePolling'

// Every 2.5s while the current project has queued/running announcement
// tasks, polls the project snapshot and clears busy state once none of the
// tracked tasks are still active. Moved verbatim from main.tsx's App
// component.
export function useAnnouncementTaskPolling(
  current: Project | undefined,
  refreshProjectSnapshot: (projectId: string) => Promise<Project | null>,
  isCurrentProject: (projectId?: string | null) => boolean,
  setBusyForProject: (projectId: string, value: boolean) => void,
  setStatusForProject: (projectId: string, message: string) => void
) {
  const runningTaskIds = (current?.announcement_tasks || [])
    .filter((task) => ['queued', 'running'].includes(task.status))
    .map((task) => task.id)
  const enabled = Boolean(current && runningTaskIds.length)
  const projectId = current?.id || ''

  usePolling(async () => {
    const loaded = await refreshProjectSnapshot(projectId)
    if (!loaded || !isCurrentProject(projectId)) return
    const tasks = loaded.announcement_tasks || []
    const stillRunning = tasks.some((task) => runningTaskIds.includes(task.id) && ['queued', 'running'].includes(task.status))
    if (!stillRunning) {
      const finished = tasks.find((task) => runningTaskIds.includes(task.id)) || tasks[0]
      setBusyForProject(projectId, false)
      const message = announcementTaskStatusText(finished)
      if (message) setStatusForProject(projectId, message)
    }
  }, { intervalMs: 2500, enabled }, [current?.id, current?.announcement_tasks?.map((task) => `${task.id}:${task.status}`).join('|')])
}
