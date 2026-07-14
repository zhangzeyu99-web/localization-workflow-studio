import { Download, PackageCheck, RefreshCw, Wrench } from 'lucide-react'
import { artifactDownloadHref, artifactKindLabel, artifactPickerLabel, pickerArtifacts, runArtifacts } from '../../../domain/artifacts'
import { issueCountPhrase } from '../../../uiText'
import { type LanguageCode, languageSpec } from '../../../languages'
import { multilingualWorkflowItems } from '../../../domain/translationFlow'
import type { Artifact, DeliverableTask, DeliveryFile, DeliveryLanguageResult, Project, QualityIssue, Run } from '../../../types'
import { qaPendingIssueCount } from '../QaIssuePanel'
import { TaskRunSummary } from '../TaskRunSummary'
import { WorkflowSideCard, WorkflowStepShell } from '../WorkflowStepShell'
import { ArchiveProvenanceBadge } from '../../shared/StatusPrimitives'
import { MultilingualWorkflowBoard } from '../MultilingualWorkflowBoard'

export function StepDone({
  project,
  translationTaskId,
  latestRun,
  qualityIssues,
  setStep,
  sourceArtifact,
  selectedLanguage,
  setSelectedLanguage,
  selectedLanguages,
  busy,
  onCreateDelivery,
  onCreateMergedDelivery,
  onRetryTranslations,
  deliverables,
  generatedDeliveryRunId,
  generatedDeliveryFiles,
  generatedDeliveryMergedLanguages,
  generatedDeliverySkippedLanguages,
  generatedDeliveryLanguageResults,
}: {
  project: Project
  translationTaskId: string
  latestRun: Run | null
  qualityIssues: QualityIssue[]
  setStep: (step: number) => void
  sourceArtifact: Artifact | null
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  busy: boolean
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
  onCreateMergedDelivery?: () => Promise<DeliveryFile[] | null> | void
  onRetryTranslations?: () => void
  deliverables: DeliverableTask[]
  generatedDeliveryRunId?: string
  generatedDeliveryFiles?: DeliveryFile[]
  generatedDeliveryMergedLanguages?: string[]
  generatedDeliverySkippedLanguages?: string[]
  generatedDeliveryLanguageResults?: DeliveryLanguageResult[]
}) {
  const taskScope = { translationTaskId, inputArtifactId: sourceArtifact?.id, language: selectedLanguage }
  const deliveryRun = findWizardDeliveryRun(project, latestRun, taskScope)
  const artifacts = pickerArtifacts(deliveryRun?.artifacts?.length ? deliveryRun.artifacts : runArtifacts(project, deliveryRun?.id))
    .filter((artifact) => artifact.kind === 'qa_final_workbook' || artifact.kind === 'qa_changes')
  const pendingIssueCount = deliveryRun?.kind === 'qa' ? qaPendingIssueCount(deliveryRun, qualityIssues) : 0
  const hasFinalWorkbook = artifacts.some((artifact) => artifact.kind === 'qa_final_workbook')
  const deliveryBlocked = deliveryRun?.kind === 'qa' && deliveryRun.status !== 'passed' && !hasFinalWorkbook
  const deliveryWarning = deliveryRun?.kind === 'qa' && deliveryRun.status === 'failed' && hasFinalWorkbook
  const multiDelivery = selectedLanguages.length > 1
  const workflowItems = multilingualWorkflowItems(project, selectedLanguages, sourceArtifact?.id, translationTaskId)
  const deliverableItems = workflowItems.filter((item) => item.state === 'ready' || item.state === 'issues')
  const retryItems = workflowItems.filter((item) => item.state === 'pending' || item.state === 'blocked')
  const activeLanguageCount = workflowItems.filter((item) => item.state === 'running').length
  const mergedTask = findMergedDeliverable(deliverables, sourceArtifact?.id, translationTaskId)
  const deliveryFiles = wizardDeliveryFiles(project, latestRun, deliverables, generatedDeliveryRunId, generatedDeliveryFiles, multiDelivery, sourceArtifact?.id, translationTaskId)
  const hasGeneratedSnapshot = Boolean(generatedDeliveryFiles?.length)
  const mergedLanguages = hasGeneratedSnapshot ? generatedDeliveryMergedLanguages || [] : mergedTask?.merged_languages || []
  const skippedLanguages = hasGeneratedSnapshot ? generatedDeliverySkippedLanguages || [] : mergedTask?.skipped_languages || []
  const languageResults = hasGeneratedSnapshot ? generatedDeliveryLanguageResults || [] : mergedTask?.language_results || []
  const canGenerateDelivery = Boolean(deliveryRun && hasFinalWorkbook && !deliveryBlocked)
  const canGenerateMergedDelivery = Boolean(multiDelivery && sourceArtifact && onCreateMergedDelivery && deliverableItems.length > 0 && activeLanguageCount === 0)
  const generated = deliveryFiles.length > 0
  const hasQaSummary = deliveryFiles.some((file) => file.kind === 'qa_summary')
  const deliveryStatus = multiDelivery
    ? generated
      ? `已合并 ${mergedLanguages.length || deliverableItems.length} 种语言`
      : canGenerateMergedDelivery
        ? `可合并 ${deliverableItems.length} 种语言`
        : activeLanguageCount > 0
          ? '多语言任务仍在处理'
          : '暂无可合并语言'
    : !deliveryRun
      ? '暂无可交付任务'
      : generated
        ? `已生成 ${deliveryFiles.length} 个文件`
        : deliveryBlocked
          ? '需要返回 QA'
          : deliveryWarning
            ? '可带问题摘要交付'
            : '可生成最终交付'
  return (
    <WorkflowStepShell
      stepLabel="步骤 9/9"
      title="交付"
      description="生成并下载交付文件。"
      status={deliveryStatus}
      statusTone={generated ? 'ready' : !multiDelivery && deliveryBlocked ? 'blocked' : !multiDelivery && deliveryWarning ? 'warn' : 'neutral'}
      nextAction={generated
        ? '下载文件或点击完成'
        : multiDelivery
          ? canGenerateMergedDelivery ? '合并当前可用语言' : retryItems.length ? '处理未完成语言' : '等待多语言任务完成'
          : canGenerateDelivery ? '生成交付文件' : '返回 QA 处理'}
      showStatus={false}
      side={
        <>
          <WorkflowSideCard title="下载文件" tone={generated ? 'ready' : 'neutral'}>
            <DeliveryFileLinks files={deliveryFiles} projectId={project.id} />
          </WorkflowSideCard>
          {!multiDelivery && deliveryBlocked ? (
            <WorkflowSideCard title="需要处理" tone="blocked">
              <p>缺少可交付译文。</p>
              <button className="btn btn-primary btn-sm" onClick={() => setStep(8)}>回到 QA</button>
            </WorkflowSideCard>
          ) : null}
          {!multiDelivery && deliveryRun && generated ? (
            <WorkflowSideCard title={deliveryWarning ? '待复核归档' : '归档完成'} tone={deliveryWarning ? 'warn' : 'ready'}>
              <ArchiveProvenanceBadge sourceType={deliveryWarning ? 'delivered_with_issues' : 'qa_passed'} />
              <p>{deliveryWarning ? `仍有 ${issueCountPhrase(pendingIssueCount)}问题，归档标记为待复核。` : '交付时已同步归档。'}</p>
              {deliveryWarning ? <button className="btn btn-ghost btn-sm" onClick={() => setStep(8)}><Wrench size={14} aria-hidden="true" />回到 QA</button> : null}
            </WorkflowSideCard>
          ) : null}
          {multiDelivery && skippedLanguages.length ? (
            <WorkflowSideCard title="仍需处理" tone="warn">
              <p>{skippedLanguages.join(' / ')} 未进入本次合并。</p>
              {onRetryTranslations ? <button className="btn btn-ghost btn-sm" disabled={busy || activeLanguageCount > 0} onClick={onRetryTranslations}><Wrench size={14} aria-hidden="true" />继续处理未完成语言</button> : null}
            </WorkflowSideCard>
          ) : null}
        </>
      }
    >
      <div className="workflow-block delivery-workbench">
        {multiDelivery ? (
          <MultilingualWorkflowBoard
            project={project}
            languages={selectedLanguages}
            inputArtifactId={sourceArtifact?.id}
            translationTaskId={translationTaskId}
            selectedLanguage={selectedLanguage}
            onSelectLanguage={(language) => {
              setSelectedLanguage(language)
              setStep(8)
            }}
          />
        ) : null}
        {!deliveryRun && !multiDelivery ? <div className="muted-left">暂无可交付任务。</div> : null}
        {!multiDelivery && canGenerateDelivery ? (
          <div className={`delivery-primary-card ${generated ? 'ready' : ''}`}>
            <div>
              <strong>{generated ? `已生成 ${deliveryFiles.length} 个文件` : deliveryWarning ? '生成带问题交付' : '生成交付文件'}</strong>
              <span>{generated ? '可在右侧下载' : deliveryWarning ? '附带 QA 摘要' : '生成后同步归档'}</span>
            </div>
            <button className="btn btn-primary" data-testid="wizard-generate-delivery" disabled={busy} onClick={() => deliveryRun && void onCreateDelivery(deliveryRun.id)}>
              {busy ? '生成中...' : generated ? <><RefreshCw size={15} aria-hidden="true" />重新生成交付文件</> : <><PackageCheck size={15} aria-hidden="true" />生成交付文件</>}
            </button>
          </div>
        ) : null}
        {!multiDelivery && deliveryWarning && generated && !hasQaSummary ? (
          <div className="warn-line" data-testid="delivery-missing-qa-summary">
            这份历史交付未检测到 QA 摘要。请点击“重新生成交付文件”，确保问题清单随交付一起输出。
          </div>
        ) : null}
        {multiDelivery ? (
          <div className={`delivery-primary-card ${generated ? 'ready' : ''}`}>
            <div>
              <strong>{generated ? `已生成 ${deliveryFiles.length} 个多语言交付文件` : `合并当前可用 ${deliverableItems.length} 种语言`}</strong>
              <span>{generated ? `已合并 ${mergedLanguages.length || deliverableItems.length} 种，跳过 ${skippedLanguages.length} 种；可在右侧下载。` : '通过结构门禁的语言写回同一语言表；未完成或结构异常语言写入 QA 摘要。'}</span>
            </div>
            <button className="btn btn-primary" data-testid="wizard-generate-merged-delivery" disabled={busy || !canGenerateMergedDelivery} onClick={() => void onCreateMergedDelivery?.()}>
              {busy ? '生成中...' : generated ? <><RefreshCw size={15} aria-hidden="true" />重新生成多语言交付</> : <><PackageCheck size={15} aria-hidden="true" />生成多语言合并交付</>}
            </button>
          </div>
        ) : null}
        {multiDelivery && retryItems.length > 0 ? (
          <div className="multilingual-bulk-actions" data-testid="multilingual-delivery-recovery">
            <div>
              <strong>剩余语言不阻塞当前交付</strong>
              <span>{retryItems.map((item) => languageSpec(item.code).short).join(' / ')} 可原地处理，完成后重新生成合并文件。</span>
            </div>
            {onRetryTranslations ? <button className="btn btn-primary btn-sm" data-testid="multilingual-delivery-retry" disabled={busy || activeLanguageCount > 0} onClick={onRetryTranslations}><Wrench size={14} aria-hidden="true" />继续处理 {retryItems.length} 种语言</button> : null}
          </div>
        ) : null}
        {multiDelivery && languageResults.length ? (
          <div className="multilingual-delivery-results" data-testid="multilingual-delivery-results">
            {languageResults.map((item) => (
              <div key={`${item.language}-${item.run_id || item.status}`} className={item.status === 'merged' ? 'ready' : 'warn'}>
                <strong>{item.language}</strong>
                <span>{item.status === 'merged' ? `已合并 ${item.rows || 0} 行` : item.reason || '本次未合并'}</span>
              </div>
            ))}
          </div>
        ) : null}
        {deliveryRun ? (
          <details className="delivery-run-details">
            <summary>查看交付详情</summary>
            <div className="delivery-run-details-body">
              <TaskRunSummary run={deliveryRun} issues={deliveryRun.id === latestRun?.id ? qualityIssues : []} />
              <div className="artifact-grid compact-artifact-grid">
                {artifacts.map((artifact) => <a key={artifact.id} className="artifact" href={artifactDownloadHref(artifact, project.id)}>{artifactPickerLabel(artifact)}<span>{artifactKindLabel(artifact)}</span></a>)}
              </div>
            </div>
          </details>
        ) : null}
      </div>
    </WorkflowStepShell>
  )
}

export type WizardTaskScope = {
  translationTaskId?: string | null
  inputArtifactId?: string | null
  language?: string | null
}

export function findWizardDeliveryRun(project: Project, latestRun: Run | null, scope: WizardTaskScope = {}): Run | null {
  const seen = new Set<string>()
  const candidates = [
    latestRun,
    ...(project.runs || [])
  ].filter((run): run is Run => {
    if (!run || seen.has(run.id)) return false
    seen.add(run.id)
    if (!['translation', 'qa'].includes(run.kind)) return false
    const metadata = run.metadata || {}
    if (scope.translationTaskId && String(metadata.translation_task_id || '') !== scope.translationTaskId) return false
    if (scope.language && run.language !== scope.language) return false
    if (scope.inputArtifactId) {
      const artifactIds = [metadata.input_artifact_id, metadata.parent_input_artifact_id, metadata.multilingual_source_artifact_id]
        .map((value) => String(value || ''))
      if (!artifactIds.includes(scope.inputArtifactId)) return false
    }
    return true
  })
  for (const run of candidates) {
    const artifacts = run.artifacts?.length ? run.artifacts : runArtifacts(project, run.id)
    if (artifacts.some((artifact) => artifact.kind === 'qa_final_workbook' || artifact.kind === 'qa_changes')) return run
  }
  return null
}

export function wizardDeliveryFiles(
  project: Project,
  latestRun: Run | null,
  deliverables: DeliverableTask[],
  generatedRunId?: string,
  generatedFiles?: DeliveryFile[],
  multiDelivery = false,
  inputArtifactId?: string,
  translationTaskId?: string,
): DeliveryFile[] {
  if (multiDelivery) {
    const generated = (generatedFiles || []).filter(isDownloadableDeliveryFile)
    if (generated.length) return uniqueDeliveryFiles(generated)
    const task = findMergedDeliverable(deliverables, inputArtifactId, translationTaskId)
    return deliveryFilesForTask(task)
  }
  const run = findWizardDeliveryRun(project, latestRun, { inputArtifactId, translationTaskId })
  return deliveryFilesForRun(deliverables, run?.id, generatedRunId, generatedFiles)
}

function findMergedDeliverable(deliverables: DeliverableTask[], inputArtifactId?: string, translationTaskId?: string): DeliverableTask | null {
  const merged = deliverables.filter((task) => (
    String(task.task_code || '').toUpperCase() === 'ALL'
    && (!translationTaskId || task.translation_task_id === translationTaskId)
  ))
  if (!inputArtifactId) return merged[0] || null
  return merged.find((task) => task.input_artifact_id === inputArtifactId)
    || merged.find((task) => !task.input_artifact_id)
    || null
}

function deliveryFilesForTask(task: DeliverableTask | null): DeliveryFile[] {
  if (!task) return []
  const files = task.files || {}
  return uniqueDeliveryFiles([
    files.final,
    files.changes,
    files.package,
    files.qa_summary || undefined,
    ...(files.outputs || []),
  ].filter(isDownloadableDeliveryFile))
}

function deliveryFilesForRun(
  deliverables: DeliverableTask[],
  runId?: string | null,
  generatedRunId?: string,
  generatedFiles: DeliveryFile[] = []
): DeliveryFile[] {
  const generated = runId && generatedRunId === runId ? generatedFiles.filter(isDownloadableDeliveryFile) : []
  if (generated.length) return uniqueDeliveryFiles(generated)
  const task = runId ? deliverables.find((item) => item.run_id === runId) : null
  return deliveryFilesForTask(task || null)
}

function isDownloadableDeliveryFile(file: DeliveryFile | null | undefined): file is DeliveryFile {
  return Boolean(file?.download_url)
}

function uniqueDeliveryFiles(files: DeliveryFile[]): DeliveryFile[] {
  const seen = new Set<string>()
  const result: DeliveryFile[] = []
  for (const file of files) {
    const key = `${file.kind}:${file.filename}:${file.download_url || file.artifact_id || ''}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(file)
  }
  return result
}

function deliveryFileHref(file: DeliveryFile, projectId: string): string {
  if (file.download_url) return file.download_url
  return `/api/projects/${projectId}/delivery/${encodeURIComponent(file.filename)}`
}

function deliveryFileLabel(file: DeliveryFile): string {
  if (file.kind === 'final') return '最终译文'
  if (file.kind === 'merged_final') return '多语言合并译文'
  if (file.kind === 'changes') return '修改记录'
  if (file.kind === 'package') return '交付包'
  if (file.kind === 'qa_summary') return 'QA 摘要'
  if (file.kind === 'announcement') return '公告交付'
  return artifactKindLabel({ kind: file.kind } as Artifact)
}

function DeliveryFileLinks({ files, projectId }: { files: DeliveryFile[]; projectId: string }) {
  if (!files.length) return <div className="muted-left">暂无可下载文件。</div>
  return (
    <div className="workflow-file-list">
      {files.map((file, index) => (
        <a key={`${file.kind}-${file.filename}-${index}`} className="workflow-file-link" href={deliveryFileHref(file, projectId)}>
          <Download size={15} aria-hidden="true" />
          <span>{deliveryFileLabel(file)}</span>
          <strong>{file.filename}</strong>
        </a>
      ))}
    </div>
  )
}
