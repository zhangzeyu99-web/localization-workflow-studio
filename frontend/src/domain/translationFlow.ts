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
  if (translationInputMode(readiness) === 'ready_for_qa') return true
  if (!readiness || readiness.source_rows <= 0) return false
  if (readiness.empty_target_rows > 0 || readiness.translated_rows <= 0) return false
  const cjkLimit = Math.max(5, Math.ceil(readiness.source_rows * 0.01))
  return readiness.translated_rows >= readiness.source_rows * 0.8 && readiness.cjk_target_rows <= cjkLimit
}

export function translationInputMode(readiness: TranslationReadiness | null | undefined): 'needs_translation' | 'ready_for_qa' | 'invalid' | 'unknown' {
  if (!readiness) return 'unknown'
  if (readiness.input_mode === 'needs_translation' || readiness.input_mode === 'ready_for_qa' || readiness.input_mode === 'invalid') {
    return readiness.input_mode
  }
  if (readiness.ready_for_qa) return 'ready_for_qa'
  if (readiness.needs_translation || readiness.ready_for_translation) return 'needs_translation'
  if (readiness.reason === 'no_source_rows' || readiness.reason === 'invalid_id_rows' || readiness.reason === 'unsupported_file' || readiness.reason === 'target_column_missing') return 'invalid'
  return 'unknown'
}

export function translationNextStep(readiness: TranslationReadiness | null | undefined): number {
  if (typeof readiness?.next_step === 'number') return readiness.next_step
  const mode = translationInputMode(readiness)
  if (mode === 'ready_for_qa') return 8
  if (mode === 'needs_translation') return 5
  return 4
}

export function translationReadinessUserMessage(readiness: TranslationReadiness | null | undefined): string {
  const message = String(readiness?.user_message || '').trim()
  if (message) return message
  const mode = translationInputMode(readiness)
  if (mode === 'ready_for_qa') return '检测到已有完整译文，可跳过 AI 翻译，直接进入校对。'
  if (mode === 'needs_translation') return '检测到待翻译内容，请先扫描术语候选。'
  if (readiness?.reason === 'invalid_id_rows') return '有行缺少可回写 ID，请修正后重新上传。'
  if (readiness?.reason === 'target_column_missing') return '未检测到目标语言译文列，请上传包含 ID、CN 和目标语言列的语言表。'
  if (readiness?.reason === 'no_source_rows') return '未检测到 CN/原文行，请上传包含 ID 和 CN 的语言表。'
  if (readiness?.reason === 'unsupported_file') return '当前文件类型不适合作为语言表，请重新上传。'
  return '选择语言表后自动检查。'
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
  // Runs are returned newest first. The visible task must follow the user's
  // latest attempt; an older stale running run must not hide a newer passed or
  // failed result.
  return runs[0] || null
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
