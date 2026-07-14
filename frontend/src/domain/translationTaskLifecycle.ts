import { normalizeLanguageCode, type LanguageCode } from '../languages'
import type { Project, Run } from '../types'

export type TranslationTaskSession = {
  id: string
  projectId: string
  step: number
  sourceArtifactId: string
  selectedLanguages: LanguageCode[]
  status: 'draft' | 'delivered'
}

export type FormalTranslationTask = {
  id: string
  translationTaskId: string
  legacy: boolean
  runs: Run[]
  latestRun: Run
  sourceArtifactId: string
  languages: LanguageCode[]
  state: string
}

const CLOSED_TASK_STATES = new Set(['delivered', 'abandoned', 'closed'])
const ACTIVE_RUN_STATUSES = new Set(['queued', 'running'])
const LEGACY_UNFINISHED_STATUSES = new Set(['failed', 'needs_input', 'canceled'])

export function createTranslationTaskId(): string {
  const uuid = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  return `translation-task-${uuid}`
}

export function translationTaskIdOfRun(run: Run | null | undefined): string {
  return String(run?.metadata?.translation_task_id || '').trim()
}

export function runMatchesTranslationTask(run: Run | null | undefined, translationTaskId: string): boolean {
  return Boolean(run && translationTaskId && translationTaskIdOfRun(run) === translationTaskId)
}

function isFormalRun(run: Run): boolean {
  return ['translation', 'qa'].includes(run.kind) && String(run.metadata?.task_origin || 'translation_run') !== 'quick_task'
}

function taskState(runs: Run[]): string {
  return [...runs]
    .filter((run) => String(run.metadata?.translation_task_state || ''))
    .sort((left, right) => String(right.metadata?.translation_task_state_updated_at || right.updated_at || '').localeCompare(String(left.metadata?.translation_task_state_updated_at || left.updated_at || '')))
    .map((run) => String(run.metadata?.translation_task_state || ''))[0] || ''
}

function taskSourceArtifactId(runs: Run[]): string {
  const sourceOrderedRuns = [
    ...runs.filter((run) => run.kind === 'translation'),
    ...runs.filter((run) => run.kind !== 'translation'),
  ]
  for (const run of sourceOrderedRuns) {
    const metadata = run.metadata || {}
    const sourceId = metadata.multilingual_source_artifact_id
      || metadata.parent_input_artifact_id
      || (run.kind === 'translation' ? metadata.input_artifact_id : '')
      || metadata.input_artifact_id
    if (sourceId) return String(sourceId)
  }
  return ''
}

function taskLanguages(runs: Run[]): LanguageCode[] {
  const result: LanguageCode[] = []
  for (const run of runs) {
    const language = normalizeLanguageCode(run.language)
    if (language && !result.includes(language)) result.push(language)
  }
  return result.length ? result : ['en']
}

export function formalTranslationTasks(project: Project | null | undefined): FormalTranslationTask[] {
  if (!project) return []
  const groups = new Map<string, { translationTaskId: string; legacy: boolean; runs: Run[] }>()
  for (const run of (project.runs || []).filter(isFormalRun)) {
    const translationTaskId = translationTaskIdOfRun(run)
    const key = translationTaskId || `legacy:${run.id}`
    const group = groups.get(key) || { translationTaskId, legacy: !translationTaskId, runs: [] }
    group.runs.push(run)
    groups.set(key, group)
  }
  return [...groups.entries()].map(([id, group]) => {
    const runs = [...group.runs].sort((left, right) => String(right.created_at || '').localeCompare(String(left.created_at || '')))
    return {
      id,
      translationTaskId: group.translationTaskId,
      legacy: group.legacy,
      runs,
      latestRun: runs[0],
      sourceArtifactId: taskSourceArtifactId(runs),
      languages: taskLanguages(runs),
      state: taskState(runs),
    }
  })
}

export function findActiveFormalTask(project: Project | null | undefined): FormalTranslationTask | null {
  return formalTranslationTasks(project).find((task) => (
    !CLOSED_TASK_STATES.has(task.state)
    && task.runs.some((run) => ACTIVE_RUN_STATUSES.has(run.status))
  )) || null
}

export function findUnfinishedFormalTask(project: Project | null | undefined): FormalTranslationTask | null {
  return formalTranslationTasks(project).find((task) => {
    if (CLOSED_TASK_STATES.has(task.state)) return false
    if (task.runs.some((run) => ACTIVE_RUN_STATUSES.has(run.status))) return false
    if (task.legacy) return task.runs.some((run) => LEGACY_UNFINISHED_STATUSES.has(run.status))
    return true
  }) || null
}

export function translationTaskResumeStep(task: FormalTranslationTask): number {
  if (task.runs.some((run) => run.kind === 'qa')) return 8
  const latest = task.latestRun
  const reason = String(latest.metadata?.reason || '')
  if (latest.status === 'needs_input' && ['glossary_candidates_not_confirmed', 'selected_term_artifact_empty'].includes(reason)) return 5
  if (['passed', 'failed'].includes(latest.status)) return 8
  return 7
}
