import { artifactDownloadHref, artifactPickerLabel, pickerArtifacts, runArtifacts } from '../../domain/artifacts'
import { shortRunId } from '../../domain/format'
import { normalizeLanguageCode, languageSpec } from '../../languages'
import { runStatusLabel, shortIdLabel } from '../../uiText'
import type { Artifact, HistoryKind, LargeTextRunState, Project, Run, TranslationProgress, TranslationReadiness } from '../../types'
import { runDeliveryState } from './QaIssuePanel'

export function downloadableArtifact(artifacts: Artifact[], kind: HistoryKind): Artifact | null {
  const accepted = kind === 'translation'
    ? ['qa_final_workbook']
    : ['qa_changes', 'qa_final_workbook']
  return artifacts.find((artifact) => artifact.exists !== false && (accepted.includes(artifact.role || '') || accepted.includes(artifact.kind))) || null
}

export function RunDetail({ project, run, kind }: { project: Project; run: Run; kind: HistoryKind }) {
  const artifacts = runArtifacts(project, run.id)
  const visibleArtifacts = pickerArtifacts(artifacts.filter((artifact) => downloadableArtifact([artifact], kind)))
  const largeTextState = run.metadata?.large_text as LargeTextRunState | undefined
  const largeTextGateKinds = ['large_text_preflight', 'large_text_cache_lint', 'delivery_readback_gate', 'large_text_retro']
  const largeTextArtifacts = pickerArtifacts(artifacts.filter((artifact) => largeTextGateKinds.includes(artifact.kind)))
  const inputs = (run.metadata?.input_artifacts || {}) as Record<string, string>
  const artifactById = new Map((project.artifacts || []).map((artifact) => [artifact.id, artifact]))
  const task = runTaskSummary(project, run)
  const quality = (run.metadata?.quality_summary || {}) as Record<string, unknown>
  const archiveCount = runArchiveCount(run)
  const inputItems = [
    ['源/译文', inputs.source_workbook || inputs.translation_workbook],
    ['术语快照', inputs.glossary_snapshot],
    ['提示词快照', inputs.prompt_snapshot],
    ['规则快照', inputs.harness_snapshot],
    ['临时参考快照', inputs.quick_reference_snapshot],
    ['大文本预检', largeTextState?.preflight_artifact_id],
    ['大文本复盘', largeTextState?.retro_artifact_id],
  ].filter(([, id]) => Boolean(id))
  return (
    <div className="history-detail">
      <div className="history-detail-head">
        <strong>{run.kind === 'qa' ? '校对任务详情' : '翻译任务详情'}</strong>
        <span title={run.id}>{shortIdLabel(run.id)}</span>
      </div>
      <div className="history-detail-grid">
        <div><strong>任务类型</strong><span>{task.taskType}</span></div>
        <div><strong>任务ID</strong><span>{task.taskLabel}</span></div>
        <div><strong>状态</strong><span>{runStatusLabel(run.status)}</span></div>
        <div><strong>语言</strong><span>{run.language ? languageSpec(normalizeLanguageCode(run.language) || 'en').short : '-'}</span></div>
        <div><strong>创建时间</strong><span>{new Date(run.created_at).toLocaleString()}</span></div>
        <div><strong>更新时间</strong><span>{new Date(run.updated_at).toLocaleString()}</span></div>
        <div><strong>来源文件</strong><span>{inputArtifactName(project, run) || '-'}</span></div>
        <div><strong>QA 结果</strong><span>必须修复 {Number(quality.hard_errors || 0)}</span></div>
        <div><strong>翻译处理</strong><span>{runTranslationProgressText(run)}</span></div>
        <div><strong>校对处理</strong><span>{runQaRowsText(run)}</span></div>
        <div><strong>本次归档</strong><span>{archiveCount > 0 ? `${archiveCount} 条` : '未归档'}</span></div>
        <div><strong>累计归档</strong><span>{project.stats.archived_rows || 0} 条</span></div>
        <div><strong>交付状态</strong><span>{runDeliveryState(run, visibleArtifacts)}</span></div>
      </div>
      <div className="artifact-links">
        {visibleArtifacts.map((artifact) => (
          <a key={artifact.id} className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact, project.id)}>{artifactPickerLabel(artifact)}</a>
        ))}
        {!visibleArtifacts.length ? <span className="muted-left">暂无可下载结果；若任务已通过，请到“交付”页生成最终交付文件。</span> : null}
      </div>
      {largeTextArtifacts.length ? (
        <div className="artifact-links">
          {largeTextArtifacts.map((artifact) => (
            <a key={artifact.id} className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact, project.id)}>{artifactPickerLabel(artifact)}</a>
          ))}
        </div>
      ) : null}
      {inputItems.length ? (
        <div className="run-inputs">
          {inputItems.map(([label, id]) => {
            const artifact = artifactById.get(String(id))
            return <span key={`${label}-${id}`}>{label}: {artifact ? artifactPickerLabel(artifact) : id}</span>
          })}
        </div>
      ) : null}
    </div>
  )
}

export function runTaskSummary(project: Project, run: Run, seen: Set<string> = new Set()): { taskCode: string; taskType: string; taskLabel: string } {
  if (seen.has(run.id)) {
    const code = run.kind === 'qa' ? 'QA' : run.kind === 'translation' ? 'T' : run.kind.toUpperCase()
    return { taskCode: code, taskType: code, taskLabel: `${code}-${shortRunId(run.id)}` }
  }
  seen.add(run.id)
  const sourceId = String(run.metadata?.manual_fix_source_run_id || run.metadata?.model_fix_source_run_id || run.metadata?.source_run_id || '')
  if (sourceId) {
    const sourceRun = (project.runs || []).find((item) => item.id === sourceId)
    if (sourceRun && (run.kind === 'qa' || run.metadata?.task_origin === 'translation_continuation')) {
      return runTaskSummary(project, sourceRun, seen)
    }
  }
  const code = String(run.metadata?.task_code || (run.kind === 'qa' ? 'QA' : run.kind === 'translation' ? 'T' : run.kind.toUpperCase())).toUpperCase()
  const label = `${code}-${shortRunId(run.id)}`
  const quick = run.metadata?.task_origin === 'quick_task'
  const type = quick
    ? (run.kind === 'qa' ? '快速校对' : '快速翻译')
    : code === 'A' ? '完整工作流' : code === 'QA' ? '校对任务' : code === 'T' ? '翻译任务' : code
  return { taskCode: code, taskType: type, taskLabel: label }
}

export function inputArtifactName(project: Project, run: Run): string {
  const inputs = (run.metadata?.input_artifacts || {}) as Record<string, string>
  const artifactId = inputs.source_workbook || inputs.translation_workbook || String(run.metadata?.input_artifact_id || '')
  if (!artifactId) return ''
  const artifact = (project.artifacts || []).find((item) => item.id === artifactId)
  return artifact ? artifactPickerLabel(artifact) : artifactId
}

export function runArchiveCount(run: Run): number {
  const archive = run.metadata?.translation_archive as { imported_count?: number } | undefined
  return Number(archive?.imported_count || 0)
}

export function runProcessedLabel(run: Run): string {
  const archiveCount = runArchiveCount(run)
  if (archiveCount > 0) return `${archiveCount} 条归档`
  const progress = run.metadata?.translation_progress as TranslationProgress | undefined
  if (progress?.total_rows) return `${progress.completed_rows || 0}/${progress.total_rows} 行`
  const readiness = run.metadata?.translation_readiness as TranslationReadiness | undefined
  if (readiness?.source_rows) {
    if (readiness.ready_for_qa) return `${readiness.translated_rows}/${readiness.source_rows} 行已译`
    return `${readiness.source_rows} 行待译`
  }
  const qualityRows = qualityRowsScanned(run)
  if (qualityRows > 0) return `${qualityRows} 行校对`
  return '-'
}

export function runTranslationProgressText(run: Run): string {
  const progress = run.metadata?.translation_progress as TranslationProgress | undefined
  if (progress?.total_rows) {
    const percent = typeof progress.percent === 'number' ? `，${progress.percent}%` : ''
    return `${progress.completed_rows || 0}/${progress.total_rows} 行${percent}`
  }
  const readiness = run.metadata?.translation_readiness as TranslationReadiness | undefined
  if (readiness?.source_rows) {
    return readiness.ready_for_qa
      ? `输入已含译文 ${readiness.translated_rows}/${readiness.source_rows} 行，跳过 AI 翻译`
      : `${readiness.source_rows} 行待翻译，预计 ${readiness.estimated_batches || 0} 批`
  }
  return run.kind === 'translation' ? '未开始' : '不涉及'
}

export function runQaRowsText(run: Run): string {
  const rows = qualityRowsScanned(run)
  if (rows > 0) return `${rows} 行`
  const archiveCount = runArchiveCount(run)
  if (archiveCount > 0) return `${archiveCount} 行`
  return run.kind === 'qa' || run.metadata?.quality_summary ? '已运行，未返回行数' : '未运行'
}

export function qualityRowsScanned(run: Run): number {
  const summary = (run.metadata?.quality_summary || {}) as Record<string, unknown>
  const directQuality = (run.metadata?.quality || {}) as { rows_scanned?: number }
  const globalQuality = summary.global_harness_quality as { rows_scanned?: number } | undefined
  const projectQuality = summary.project_harness_quality as { rows_scanned?: number } | undefined
  return Number(directQuality.rows_scanned || globalQuality?.rows_scanned || projectQuality?.rows_scanned || 0)
}
