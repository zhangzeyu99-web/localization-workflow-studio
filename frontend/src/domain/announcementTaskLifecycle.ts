import type { AnnouncementTask } from '../types'

const ACTIVE_STATUSES = new Set(['queued', 'running'])
const TERMINAL_STATUSES = new Set(['delivered', 'canceled'])

export type AnnouncementTaskLifecycle = {
  activeTask: AnnouncementTask | null
  stoppedTasks: AnnouncementTask[]
}

export type AnnouncementSessionScope = {
  projectId: string
  taskId: string
  generation: number
}

export function selectAnnouncementTaskLifecycle(tasks: AnnouncementTask[]): AnnouncementTaskLifecycle {
  const unfinished = tasks.filter((task) => !TERMINAL_STATUSES.has(task.status || ''))
  return {
    activeTask: unfinished.find((task) => ACTIVE_STATUSES.has(task.status || '')) || null,
    stoppedTasks: unfinished.filter((task) => !ACTIVE_STATUSES.has(task.status || '')),
  }
}

export function unfinishedAnnouncementConflictTaskId(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || '')
  try {
    const payload = JSON.parse(message) as { detail?: { code?: unknown; task_id?: unknown } }
    if (payload.detail?.code !== 'unfinished_announcement_task_exists') return ''
    return String(payload.detail.task_id || '')
  } catch {
    return ''
  }
}

export function announcementTaskStatusConflict(error: unknown): { taskId: string; status: string } | null {
  const message = error instanceof Error ? error.message : String(error || '')
  try {
    const payload = JSON.parse(message) as { detail?: { code?: unknown; task_id?: unknown; status?: unknown } }
    if (payload.detail?.code !== 'announcement_task_status_conflict') return null
    const taskId = String(payload.detail.task_id || '')
    if (!taskId) return null
    return { taskId, status: String(payload.detail.status || '') }
  } catch {
    return null
  }
}
