import { Download, PackageCheck, RefreshCw, Wrench } from 'lucide-react'
import { artifactDownloadHref, artifactKindLabel, artifactPickerLabel, pickerArtifacts, runArtifacts } from '../../../domain/artifacts'
import { issueCountPhrase } from '../../../uiText'
import { type LanguageCode, languageSpec } from '../../../languages'
import type { Artifact, DeliverableTask, DeliveryFile, Project, QualityIssue, Run } from '../../../types'
import { qaPendingIssueCount } from '../QaIssuePanel'
import { TaskRunSummary } from '../TaskRunSummary'
import { WorkflowSideCard, WorkflowStepShell } from '../WorkflowStepShell'
import { ArchiveProvenanceBadge } from '../../shared/StatusPrimitives'

export function StepDone({
  project,
  latestRun,
  qualityIssues,
  setStep,
  sourceArtifact,
  selectedLanguages,
  busy,
  onCreateDelivery,
  onCreateMergedDelivery,
  deliverables,
  generatedDeliveryRunId,
  generatedDeliveryFiles
}: {
  project: Project
  latestRun: Run | null
  qualityIssues: QualityIssue[]
  setStep: (step: number) => void
  sourceArtifact: Artifact | null
  selectedLanguages: LanguageCode[]
  busy: boolean
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
  onCreateMergedDelivery?: () => void
  deliverables: DeliverableTask[]
  generatedDeliveryRunId?: string
  generatedDeliveryFiles?: DeliveryFile[]
}) {
  const deliveryRun = findWizardDeliveryRun(project, latestRun)
  const artifacts = pickerArtifacts(deliveryRun?.artifacts?.length ? deliveryRun.artifacts : runArtifacts(project, deliveryRun?.id))
    .filter((artifact) => artifact.kind === 'qa_final_workbook' || artifact.kind === 'qa_changes')
  const pendingIssueCount = deliveryRun?.kind === 'qa' ? qaPendingIssueCount(deliveryRun, qualityIssues) : 0
  const hasFinalWorkbook = artifacts.some((artifact) => artifact.kind === 'qa_final_workbook')
  const deliveryBlocked = deliveryRun?.kind === 'qa' && deliveryRun.status !== 'passed' && !hasFinalWorkbook
  const deliveryWarning = deliveryRun?.kind === 'qa' && deliveryRun.status === 'failed' && hasFinalWorkbook
  const multiDelivery = selectedLanguages.length > 1
  const selectedLanguageText = selectedLanguages.map((code) => languageSpec(code).short).join(' / ')
  const deliveryFiles = deliveryFilesForRun(deliverables, deliveryRun?.id, generatedDeliveryRunId, generatedDeliveryFiles)
  const canGenerateDelivery = Boolean(deliveryRun && hasFinalWorkbook && !deliveryBlocked)
  const generated = deliveryFiles.length > 0
  const hasQaSummary = deliveryFiles.some((file) => file.kind === 'qa_summary')
  const deliveryStatus = !deliveryRun
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
      stepLabel="STEP 9"
      title="最终交付"
      description="生成并下载交付文件。QA 通过输出标准交付；QA 未通过时输出带问题摘要的交付，并将归档标记为待复核。"
      status={deliveryStatus}
      statusTone={generated ? 'ready' : deliveryBlocked ? 'blocked' : deliveryWarning ? 'warn' : 'neutral'}
      nextAction={generated ? '下载文件或点击完成' : canGenerateDelivery ? '生成交付文件' : '返回 QA 处理'}
      side={
        <>
          <WorkflowSideCard title="下载文件" tone={generated ? 'ready' : 'neutral'}>
            <DeliveryFileLinks files={deliveryFiles} projectId={project.id} />
          </WorkflowSideCard>
          <WorkflowSideCard title="交付说明" tone={deliveryWarning ? 'warn' : deliveryBlocked ? 'blocked' : 'neutral'}>
            {deliveryBlocked ? (
              <>
                <p>最近一次 QA 未返回可交付文件，请回到校对页重新运行 QA 或上传译文表。</p>
                <button className="btn btn-primary btn-sm" onClick={() => setStep(8)}>回到校对修复</button>
              </>
            ) : deliveryWarning ? (
              <>
                <p>仍有{issueCountPhrase(pendingIssueCount)} QA 问题未清零。交付文件会附带问题摘要，译文归档会标记为“待复核”。</p>
                <button className="btn btn-ghost btn-sm" onClick={() => setStep(8)}><Wrench size={14} aria-hidden="true" />回到校对修复</button>
              </>
            ) : (
              <p>{generated ? '交付文件已经生成，可直接下载；底部“完成”会回到项目交付页。' : '系统会把最终译文、修改记录和必要的 QA 摘要打到交付目录。'}</p>
            )}
          </WorkflowSideCard>
          {deliveryRun ? (
            <WorkflowSideCard title="归档结果" tone={deliveryWarning ? 'warn' : 'ready'}>
              <ArchiveProvenanceBadge sourceType={deliveryWarning ? 'delivered_with_issues' : 'qa_passed'} />
              <p>{generated ? '交付生成时已同步写入项目译文归档。' : '生成交付后会同步写入项目译文归档，并保留当前质量来源。'}</p>
            </WorkflowSideCard>
          ) : null}
        </>
      }
    >
      <div className="workflow-block delivery-workbench">
        {deliveryRun ? <TaskRunSummary run={deliveryRun} issues={deliveryRun.id === latestRun?.id ? qualityIssues : []} /> : <div className="muted-left">暂无可交付任务。先完成翻译或校对。</div>}
        {canGenerateDelivery ? (
          <div className={`delivery-primary-card ${generated ? 'ready' : ''}`}>
            <div>
              <strong>{generated ? '交付文件已生成' : deliveryWarning ? '生成带问题摘要的交付' : '生成最终交付文件'}</strong>
              <span>{generated ? '下载入口已在右侧出现；项目概览的交付页也会同步显示。' : '点击后会生成可下载文件，并立即显示在本页下载区。'}</span>
            </div>
            <button className="btn btn-primary" data-testid="wizard-generate-delivery" disabled={busy} onClick={() => deliveryRun && void onCreateDelivery(deliveryRun.id)}>
              {busy ? '生成中...' : generated ? <><RefreshCw size={15} aria-hidden="true" />重新生成交付文件</> : <><PackageCheck size={15} aria-hidden="true" />生成交付文件</>}
            </button>
          </div>
        ) : null}
        {deliveryWarning && generated && !hasQaSummary ? (
          <div className="warn-line" data-testid="delivery-missing-qa-summary">
            这份历史交付未检测到 QA 摘要。请点击“重新生成交付文件”，确保问题清单随交付一起输出。
          </div>
        ) : null}
        {multiDelivery ? (
          <div className="delivery-primary-card">
            <div>
              <strong>多语言合并交付</strong>
              <span>已选 {selectedLanguageText}。已完成或允许交付的语言列会合并回同一语言表；未完成语言写入 QA 摘要。</span>
            </div>
            <button className="btn btn-ghost" disabled={busy || !sourceArtifact || !onCreateMergedDelivery} onClick={onCreateMergedDelivery}>生成多语言合并交付</button>
          </div>
        ) : null}
        <div className="artifact-grid compact-artifact-grid">
          {artifacts.map((artifact) => <a key={artifact.id} className="artifact" href={artifactDownloadHref(artifact, project.id)}>{artifactPickerLabel(artifact)}<span>{artifactKindLabel(artifact)}</span></a>)}
        </div>
        {!generated ? <div className="muted-left">底部“完成”会在交付文件生成后启用。</div> : null}
      </div>
    </WorkflowStepShell>
  )
}

export function findWizardDeliveryRun(project: Project, latestRun: Run | null): Run | null {
  const seen = new Set<string>()
  const candidates = [
    latestRun,
    ...(project.runs || [])
  ].filter((run): run is Run => {
    if (!run || seen.has(run.id)) return false
    seen.add(run.id)
    return ['translation', 'qa'].includes(run.kind)
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
  generatedFiles?: DeliveryFile[]
): DeliveryFile[] {
  const run = findWizardDeliveryRun(project, latestRun)
  return deliveryFilesForRun(deliverables, run?.id, generatedRunId, generatedFiles)
}

function deliveryFilesForRun(
  deliverables: DeliverableTask[],
  runId?: string | null,
  generatedRunId?: string,
  generatedFiles: DeliveryFile[] = []
): DeliveryFile[] {
  const generated = runId && generatedRunId === runId ? generatedFiles : []
  if (generated.length) return uniqueDeliveryFiles(generated)
  const task = runId ? deliverables.find((item) => item.run_id === runId) : null
  if (!task) return []
  const files = task.files || {}
  return uniqueDeliveryFiles([
    files.final,
    files.changes,
    files.package,
    files.qa_summary || undefined,
    ...(files.outputs || []),
  ].filter((file): file is DeliveryFile => Boolean(file)))
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
