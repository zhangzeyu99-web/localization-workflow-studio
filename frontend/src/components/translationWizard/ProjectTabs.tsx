import { formatDateTime } from '../../domain/format'
import { projectPromptForLanguage } from '../../domain/projectAssets'
import { deliverableOutcomePresentation } from '../../domain/workflowPresentation'
import { languageSpec, type LanguageCode } from '../../languages'
import { ActionStatus, AssetSelect, FileBox, LanguageSelector, SelectedInput } from '../shared/WorkflowPrimitives'
import type { AppSettings, Artifact, DeliverableTask, DeliveryFile, Project, QualityIssue, Run, TranslationReadiness } from '../../types'
import { formalTranslationBlockReason } from './translationGuards'
import { TaskHistoryTable } from './TaskHistoryTable'
import { TaskRunSummary } from './TaskRunSummary'

export function TranslationTab({
  project,
  settings,
  busy,
  status,
  sourceArtifact,
  termArtifact,
  latestRun,
  translationReadiness,
  qualityIssues,
  setSourceArtifact,
  setTermArtifact,
  onUploadSource,
  onTranslate,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  settings: AppSettings | null
  busy: boolean
  status: string
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  onUploadSource: (file: File) => void
  onTranslate: () => void
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id ? translationReadiness : null
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project, readiness)
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const lang = languageSpec(selectedLanguage)
  const promptReady = Boolean(projectPromptForLanguage(project, selectedLanguage))
  return (
    <>
      <div className="card">
        <div className="card-title"><div className="left">{lang.short} 翻译任务</div></div>
        <div className="action-card">
          <div className="language-inline-select">
            <span>翻译目标语言：</span>
            <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
          </div>
          <AssetSelect label="待翻译语言表" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} allowEmpty />
          <FileBox label="上传待翻译表格" onFile={onUploadSource} />
          <button className="btn btn-primary" data-testid="formal-translate" disabled={busy || Boolean(blockReason)} onClick={onTranslate}>开始正式翻译</button>
          {blockReason ? <div className="warn-line">{blockReason}</div> : null}
          <ActionStatus status={status} busy={busy} />
        </div>
        <SelectedInput label="语言表" artifact={sourceArtifact} />
        <div className="workflow-note-grid">
          <div><strong>{lang.short} 提示词</strong><span>{promptReady ? '已在元信息页生成' : '未生成'}</span></div>
          <div><strong>项目术语库</strong><span>{glossaryCount} 条，run 开始时生成快照</span></div>
          <div><strong>交付规则</strong><span>QA 通过生成标准交付；未通过可继续修复或带问题摘要交付</span></div>
        </div>
      </div>
      <TaskHistoryTable project={project} kind="translation" title="翻译历史记录" />
      {latestRun && latestRun.kind === 'translation' ? <TaskRunSummary run={latestRun} /> : null}
    </>
  )
}

export function DeliveryTab({
  project,
  deliverables,
  loading,
  error,
  busy,
  status,
  onCreateDelivery,
  onRefresh,
  onGoTranslate,
  onGoQA,
  onGoArchive
}: {
  project: Project
  deliverables: DeliverableTask[]
  loading: boolean
  error: string
  busy: boolean
  status: string
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
  onRefresh: () => void
  onGoTranslate: () => void
  onGoQA: () => void
  onGoArchive: () => void
}) {
  return (
    <div className="card">
      <div className="card-title">
        <div className="left">最终交付</div>
        {deliverables.length ? <span className="muted-inline">共 {deliverables.length} 个可交付任务</span> : null}
      </div>
      {loading && !deliverables.length ? (
        <div className="delivery-empty" data-testid="delivery-loading">
          <div><strong>正在加载交付任务</strong><span>正在读取当前项目的翻译、QA 和公告交付记录。</span></div>
        </div>
      ) : null}
      {error ? (
        <div className="delivery-empty" data-testid="delivery-load-error">
          <div><strong>交付列表加载失败</strong><span>{error}</span></div>
          <button className="btn btn-primary btn-sm" onClick={onRefresh}>重新加载</button>
        </div>
      ) : null}
      {!loading && !error && !deliverables.length ? (
        <div className="delivery-empty" data-testid="delivery-empty">
          <div>
            <strong>还没有可下载的交付文件</strong>
            <span>先完成翻译或校对。QA 通过可生成标准交付；未通过且保留译文时，也可生成附带问题摘要的交付。</span>
          </div>
          <div className="row-actions">
            <button className="btn btn-primary btn-sm" data-testid="delivery-empty-translate" onClick={onGoTranslate}>去翻译</button>
            <button className="btn btn-ghost btn-sm" data-testid="delivery-empty-qa" onClick={onGoQA}>去校对</button>
            <button className="btn btn-ghost btn-sm" data-testid="delivery-empty-archive" onClick={onGoArchive}>看归档</button>
          </div>
        </div>
      ) : null}
      {busy || (status && status !== '准备就绪') ? <ActionStatus status={status} busy={busy} /> : null}
      <div className="delivery-list delivery-list-compact">
        {deliverables.map((task) => {
          const finalFile = task.files.final
          const changesFile = task.files.changes
          const packageFile = task.files.package
          const qaSummaryFile = task.files.qa_summary || null
          const outputFiles = task.files.outputs || []
          const hasFinal = Boolean(finalFile?.download_url)
          const hasChanges = Boolean(changesFile?.download_url)
          const hasPackage = Boolean(packageFile?.download_url)
          const hasDelivery = hasFinal || hasPackage
          const hasQaIssues = task.status === 'failed' || task.qa_status === 'failed' || Number(task.qa_hard_errors || 0) > 0
          const hasQaSummary = Boolean(qaSummaryFile?.download_url)
          const missingQaSummary = hasQaIssues && hasDelivery && !hasQaSummary
          const canRebuildMissingSummary = missingQaSummary && ['T', 'QA'].includes(String(task.task_code || '').toUpperCase())
          const outcome = deliverableOutcomePresentation(task)
          const outcomeSummary = missingQaSummary
            ? canRebuildMissingSummary
              ? '这份历史交付缺少 QA 摘要，当前文件不完整。请重新生成交付，补齐问题清单后再下载。'
              : '这份历史交付缺少 QA 摘要，当前文件不完整。请回到对应任务重新生成交付。'
            : outcome.summary
          const resultLabel = missingQaSummary
            ? '历史交付缺少 QA 摘要'
            : hasPackage
              ? '已生成公告交付包'
              : hasDelivery
                ? (hasChanges ? '已生成最终译文 + 修改记录' : '已生成最终译文')
                : '待生成'
          return (
            <div key={task.run_id} className="delivery-card delivery-line">
              <div className="delivery-head">
                <div>
                  <strong>{deliveryTaskTitle(task)}</strong>
                  <span>{deliveryTaskSubtitle(task)}</span>
                </div>
                <span className={`tag ${hasQaIssues ? 'tag-warn' : task.status === 'passed' ? 'tag-done' : 'tag-doing'}`}>{deliveryStatusLabel(task)}</span>
              </div>
              <div
                className={`delivery-outcome-strip ${outcome.tone}`}
                data-testid={missingQaSummary ? 'delivery-missing-qa-summary' : hasQaIssues ? 'delivery-problem-warning' : undefined}
              >
                <strong>{outcome.label}</strong><span>{outcomeSummary}</span>
              </div>
              <div className="delivery-line-info">
                <div><span>任务进度</span><strong>{deliveryProgressLabel(task)}</strong></div>
                <div><span>交付结果</span><strong>{resultLabel}</strong></div>
              </div>
              <div className="delivery-actions">
                {packageFile?.download_url ? <a className="btn btn-primary btn-sm" href={packageFile.download_url}>下载交付包</a> : null}
                {outputFiles.map((file) => file.download_url ? <a key={`${task.run_id}-${file.kind}-${file.filename}`} className="btn btn-ghost btn-sm" href={file.download_url}>下载成品</a> : null)}
                {qaSummaryFile?.download_url ? <a className="btn btn-ghost btn-sm" href={qaSummaryFile.download_url}>下载 QA 摘要</a> : null}
                {finalFile?.download_url ? <a className="btn btn-primary btn-sm" href={finalFile.download_url}>下载最终译文</a> : null}
                {changesFile?.download_url ? <a className="btn btn-ghost btn-sm" href={changesFile.download_url}>下载修改记录</a> : null}
                {!hasDelivery || canRebuildMissingSummary ? (
                  <button className="btn btn-primary btn-sm" data-testid={`delivery-generate-${task.run_id}`} disabled={busy} onClick={() => onCreateDelivery(task.run_id)}>
                    {canRebuildMissingSummary ? '重新生成并补齐摘要' : '生成交付文件'}
                  </button>
                ) : null}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function deliveryTaskTitle(task: DeliverableTask): string {
  const input = compactDeliveryInputLabel(task.input_label)
  return input ? `${input} · ${task.language}` : `${task.task_type} · ${task.language}`
}

export function deliveryTaskSubtitle(task: DeliverableTask): string {
  return `${task.task_type} · ${formatDateTime(task.created_at)} · ${task.task_label}`
}

export function compactDeliveryInputLabel(value?: string): string {
  const label = String(value || '').trim()
  if (!label || label === '-') return ''
  const parts = label.split('｜').map((part) => part.trim()).filter(Boolean)
  if (parts.length >= 4) return parts.slice(1, 3).join(' · ')
  if (parts.length >= 2) return parts.slice(1).join(' · ')
  return label
}

export function deliveryStatusLabel(task: DeliverableTask): string {
  if (task.delivered_with_issues) return '带问题已交付'
  if (task.status === 'delivered') return '已交付'
  if (task.status === 'passed' && Number(task.qa_hard_errors || 0) === 0) return '可交付'
  if (task.status === 'failed') return '带问题可交付'
  return task.status || '处理中'
}

export function deliveryProgressLabel(task: DeliverableTask): string {
  if (task.task_code === 'ANN' || task.status === 'delivered') return 'STEP 9/9 · 已交付'
  const total = Number(task.source_rows || task.processed_rows || 0)
  const done = Number(task.processed_rows || task.translated_rows || 0)
  const qa = `QA 必修 ${task.qa_hard_errors ?? 0} / 建议 ${task.qa_soft_warnings ?? 0}`
  return total > 0 ? `${done}/${total} 行 · ${qa}` : qa
}
