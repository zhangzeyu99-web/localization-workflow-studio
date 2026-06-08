import type { AppSettings, Project, Run, TranslationProgress, TranslationReadiness } from '../types'

export function clampBatchSize(value: number): number {
  if (!Number.isFinite(value)) return 90
  return Math.max(1, Math.min(200, Math.round(value)))
}

export function effectiveBatchSize(settings: AppSettings | null | undefined, fallback = 90): number {
  return clampBatchSize(Number(settings?.batch_size || fallback))
}

export function estimateBatches(rows: number | undefined, batchSize: number): number {
  const total = Number(rows || 0)
  return total > 0 ? Math.ceil(total / Math.max(1, batchSize)) : 0
}

export function getTranslationProgress(run: Run | null): TranslationProgress | null {
  const progress = run?.metadata?.translation_progress
  if (!progress || typeof progress !== 'object') return null
  return progress as TranslationProgress
}

export function canSkipModelTranslation(readiness: TranslationReadiness | null | undefined): boolean {
  if (!readiness || readiness.source_rows <= 0) return false
  if (readiness.ready_for_qa) return true
  if (readiness.empty_target_rows > 0 || readiness.translated_rows <= 0) return false
  const cjkLimit = Math.max(5, Math.ceil(readiness.source_rows * 0.01))
  return readiness.translated_rows >= readiness.source_rows * 0.8 && readiness.cjk_target_rows <= cjkLimit
}

export function latestRunOfKind(project: Project, kind: string): Run | null {
  return (project.runs || []).find((run) => run.kind === kind) || null
}



export const RESUMABLE_TRANSLATION_STATUSES = ['failed', 'needs_input', 'canceled'] as const

function runTaskOrigin(run: Run): string {
  return String(run.metadata?.task_origin || 'translation_run')
}

export function isTranslationRunResumable(run: Run | null | undefined): boolean {
  if (!run || run.kind !== 'translation') return false
  if (run.status === 'needs_input' || run.status === 'canceled') return true
  if (run.status !== 'failed') return false
  const progress = getTranslationProgress(run)
  const quality = run.metadata?.quality as { passed?: boolean } | undefined
  const reason = String(run.metadata?.reason || '')
  if (quality?.passed === false && progress && progress.completed_rows >= progress.total_rows) return false
  if (progress?.failed_batch) return true
  if (progress && progress.completed_rows < progress.total_rows) return true
  return ['background_job_interrupted', 'api_budget_confirmation_required'].includes(reason) || Boolean(run.metadata?.error)
}

export function matchesTranslationRun(
  run: Run,
  language: string,
  inputArtifactId: string | null | undefined,
  taskOrigin: 'translation_run' | 'quick_task' | null = 'translation_run'
): boolean {
  if (run.kind !== 'translation') return false
  if (run.language !== language) return false
  if (inputArtifactId && run.metadata?.input_artifact_id !== inputArtifactId) return false
  if (taskOrigin === null) return true
  const origin = runTaskOrigin(run)
  if (taskOrigin === 'translation_run') return origin === 'translation_run' || origin === ''
  return origin === taskOrigin
}

export function matchingTranslationRuns(
  project: Project,
  language: string,
  inputArtifactId: string | null | undefined,
  taskOrigin: 'translation_run' | 'quick_task' | null = 'translation_run'
): Run[] {
  return (project.runs || []).filter((run) => matchesTranslationRun(run, language, inputArtifactId, taskOrigin))
}

export function findResumableTranslationRun(
  project: Project,
  language: string,
  inputArtifactId: string | null | undefined,
  taskOrigin: 'translation_run' | 'quick_task' | null = 'translation_run'
): Run | null {
  return matchingTranslationRuns(project, language, inputArtifactId, taskOrigin).find(isTranslationRunResumable) || null
}

export function findVisibleTranslationRun(
  project: Project,
  language: string,
  inputArtifactId: string | null | undefined,
  taskOrigin: 'translation_run' | 'quick_task' | null = 'translation_run'
): Run | null {
  const runs = matchingTranslationRuns(project, language, inputArtifactId, taskOrigin)
  return runs.find((run) => ['queued', 'running'].includes(run.status))
    || runs.find(isTranslationRunResumable)
    || runs[0]
    || null
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return '首批完成后估算'
  const value = Math.max(0, Math.round(Number(seconds)))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${secs}s`
  return `${secs}s`
}
