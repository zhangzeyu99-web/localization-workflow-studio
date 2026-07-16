import { announcementTaskStatusText } from '../appText'
import type { AnnouncementSessionScope } from '../domain/announcementTaskLifecycle'
import type { Project } from '../types'
import { usePolling } from './usePolling'

// Every 2.5s while the current project has queued/running announcement
// tasks, polls the project snapshot and clears busy state once none of the
// tracked tasks are still active. Moved verbatim from main.tsx's App
// component.
export function useAnnouncementTaskPolling(
  current: Project | undefined,
  announcementFocusTaskId: string,
  announcementSessionGeneration: number,
  refreshProjectSnapshot: (projectId: string, signal?: AbortSignal) => Promise<Project | null>,
  isCurrentProject: (projectId?: string | null) => boolean,
  isCurrentAnnouncementSession: (scope: AnnouncementSessionScope) => boolean,
  setBusyForProject: (projectId: string, value: boolean) => void,
  setStatusForProject: (projectId: string, message: string) => void
) {
  const runningTaskIds = (current?.announcement_tasks || [])
    .filter((task) => ['queued', 'running'].includes(task.status))
    .map((task) => task.id)
  const enabled = Boolean(current && runningTaskIds.length)
  const projectId = current?.id || ''
  const scope: AnnouncementSessionScope = {
    projectId,
    taskId: announcementFocusTaskId,
    generation: announcementSessionGeneration,
  }

  usePolling(async (isStale, signal) => {
    const loaded = await refreshProjectSnapshot(projectId, signal)
    if (isStale()) return
    if (!loaded || !isCurrentProject(projectId)) return
    if (!scope.taskId || !runningTaskIds.includes(scope.taskId) || !isCurrentAnnouncementSession(scope)) return
    const tasks = loaded.announcement_tasks || []
    const stillRunning = tasks.some((task) => task.id === scope.taskId && ['queued', 'running'].includes(task.status))
    if (!stillRunning) {
      const finished = tasks.find((task) => task.id === scope.taskId)
      setBusyForProject(projectId, false)
      const message = announcementTaskStatusText(finished)
      if (message) setStatusForProject(projectId, message)
    }
  }, { intervalMs: 2500, enabled }, [
    current?.id,
    current?.announcement_tasks?.map((task) => `${task.id}:${task.status}`).join('|'),
    announcementFocusTaskId,
    announcementSessionGeneration,
  ])
}
