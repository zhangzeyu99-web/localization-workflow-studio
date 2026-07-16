import type { Run } from '../types'

const TERMINAL_STATES = new Set(['delivered', 'canceled', 'abandoned', 'closed'])
const ACTIVE_STATUSES = new Set(['running', 'queued'])

export type QuickTaskGroup = {
  id: string
  taskId: string
  legacy: boolean
  runs: Run[]
  latestRun: Run
  activeRun: Run | null
  state: string
  terminal: boolean
}

export type QuickTaskLifecycle = {
  groups: QuickTaskGroup[]
  activeTask: QuickTaskGroup | null
  stoppedTasks: QuickTaskGroup[]
}

export type QuickTaskSessionScope = {
  projectId: string
  taskId: string
  generation: number
}

const timestamp = (run: Run) => String(run.updated_at || run.created_at || '')

const newestFirst = (left: Run, right: Run) => timestamp(right).localeCompare(timestamp(left))

export function quickTaskIdOfRun(run?: Run | null): string {
  if (!run || run.metadata?.task_origin !== 'quick_task') return ''
  return String(run.metadata?.translation_task_id || '').trim()
}

export function isQuickTaskRun(run?: Run | null): boolean {
  if (!run) return false
  const taskId = String(run.metadata?.translation_task_id || '').trim()
  return run.metadata?.task_origin === 'quick_task' || taskId.startsWith('quick-task-')
}

function groupState(runs: Run[]): string {
  return runs
    .filter((run) => String(run.metadata?.translation_task_state || '').trim())
    .sort((left, right) => String(right.metadata?.translation_task_state_updated_at || timestamp(right))
      .localeCompare(String(left.metadata?.translation_task_state_updated_at || timestamp(left))))
    .map((run) => String(run.metadata?.translation_task_state || '').trim().toLowerCase())[0] || ''
}

function preferredActiveRun(runs: Run[]): Run | null {
  const running = runs.filter((run) => run.status === 'running').sort(newestFirst)[0]
  if (running) return running
  return runs.filter((run) => run.status === 'queued').sort(newestFirst)[0] || null
}

export function groupQuickTasks(runs: Run[]): QuickTaskGroup[] {
  const taskRuns = (runs || []).filter((run) => run.metadata?.task_origin === 'quick_task')
  const grouped = new Map<string, { taskId: string; legacy: boolean; runs: Run[] }>()
  for (const run of taskRuns) {
    const taskId = quickTaskIdOfRun(run)
    const id = taskId || `legacy:${run.id}`
    const current = grouped.get(id) || { taskId, legacy: !taskId, runs: [] }
    current.runs.push(run)
    grouped.set(id, current)
  }
  return [...grouped.entries()]
    .map(([id, group]) => {
      const sortedRuns = [...group.runs].sort(newestFirst)
      const state = groupState(sortedRuns)
      return {
        id,
        taskId: group.taskId,
        legacy: group.legacy,
        runs: sortedRuns,
        latestRun: sortedRuns[0],
        activeRun: preferredActiveRun(sortedRuns),
        state,
        terminal: TERMINAL_STATES.has(state),
      }
    })
    .sort((left, right) => newestFirst(left.latestRun, right.latestRun))
}

export function selectQuickTaskLifecycle(runs: Run[]): QuickTaskLifecycle {
  const groups = groupQuickTasks(runs)
  const identifiedOpenGroups = groups.filter((group) => !group.legacy && !group.terminal)
  const activeCandidates = identifiedOpenGroups.filter((group) => group.activeRun)
  const running = activeCandidates
    .filter((group) => group.activeRun?.status === 'running')
    .sort((left, right) => newestFirst(left.activeRun!, right.activeRun!))[0]
  const queued = activeCandidates
    .filter((group) => group.activeRun?.status === 'queued')
    .sort((left, right) => newestFirst(left.activeRun!, right.activeRun!))[0]
  const activeTask = running || queued || null
  const stoppedTasks = identifiedOpenGroups
    .filter((group) => !group.activeRun)
    .sort((left, right) => newestFirst(left.latestRun, right.latestRun))
  return { groups, activeTask, stoppedTasks }
}

export function createQuickTaskId(): string {
  const uuid = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `quick-task-${uuid}`
}

export function quickTaskIsTerminalState(state?: string | null): boolean {
  return TERMINAL_STATES.has(String(state || '').trim().toLowerCase())
}

export function quickTaskRunIsActive(run?: Run | null): boolean {
  return Boolean(run && ACTIVE_STATUSES.has(run.status))
}
