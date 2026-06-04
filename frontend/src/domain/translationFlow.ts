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
