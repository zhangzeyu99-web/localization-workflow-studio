import { formatDateTime } from '../../domain/format'
import { projectPromptForLanguage } from '../../domain/projectAssets'
import { currentDeliveryMissingQaSummary, currentDeliveryVersion, deliveryGroupKey, deliveryHasQaIssues, deliveryHistorySections, deliveryProcessingRun, deliveryQaLabel, deliveryTaskKindLabel } from '../../domain/deliveries'
import { useDeliveryHistory } from '../../hooks/useDeliveryHistory'
import { languageSpec, type LanguageCode } from '../../languages'
import { ActionStatus, AssetSelect, FileBox, LanguageSelector, SelectedInput } from '../shared/WorkflowPrimitives'
import type { AppSettings, Artifact, CurrentDeliveryTask, DeliverableTask, DeliveryFile, DeliveryVersion, Project, QualityIssue, Run, TranslationReadiness } from '../../types'
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
  setSelectedLanguage,
  readOnly = false,
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
  readOnly?: boolean
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
        {!readOnly ? <div className="action-card">
          <div className="language-inline-select">
            <span>翻译目标语言：</span>
            <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
          </div>
          <AssetSelect label="待翻译语言表" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} allowEmpty />
          <FileBox label="上传待翻译表格" onFile={onUploadSource} />
          <button className="btn btn-primary" data-testid="formal-translate" disabled={busy || Boolean(blockReason)} onClick={onTranslate}>开始正式翻译</button>
          {blockReason ? <div className="warn-line">{blockReason}</div> : null}
          <ActionStatus status={status} busy={busy} />
        </div> : <div className="muted-inline">历史终态快速任务仅供查看。</div>}
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
  onGoArchive,
  onOpenCurrentTask,
  canRunTasks = true,
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
  onOpenCurrentTask?: (task: CurrentDeliveryTask) => void
  canRunTasks?: boolean
}) {
  const history = useDeliveryHistory(project.id, project.updated_at, deliverables)
  const sections = history.data ? deliveryHistorySections(history.data) : null
  const loadError = history.error || error
  const isLoading = history.loading || loading
  const refresh = () => { onRefresh(); history.refresh() }
  return (
    <div className="card">
      <div className="card-title">
        <div className="left">最终交付</div>
        {sections ? <span className="muted-inline">{sections.current.length} 个当前结果 · {sections.past.length} 个历史版本</span> : null}
      </div>
      {isLoading && !history.data ? (
        <div className="delivery-empty" data-testid="delivery-loading">
          <div><strong>正在加载交付任务</strong><span>正在读取当前项目的翻译、QA 和公告交付记录。</span></div>
        </div>
      ) : null}
      {loadError ? (
        <div className="delivery-empty" data-testid="delivery-load-error">
          <div><strong>交付列表加载失败</strong><span>{loadError}</span></div>
          <button className="btn btn-primary btn-sm" onClick={refresh}>重新加载</button>
        </div>
      ) : null}
      {!isLoading && !loadError && !sections?.current.length && !sections?.past.length ? (
        <div className="delivery-empty" data-testid="delivery-empty">
          <div>
            <strong>还没有可下载的交付文件</strong>
            <span>先完成翻译或校对。QA 通过可生成标准交付；未通过且保留译文时，也可生成附带问题摘要的交付。</span>
          </div>
          <div className="row-actions">
            {canRunTasks ? <button className="btn btn-primary btn-sm" data-testid="delivery-empty-translate" onClick={onGoTranslate}>去翻译</button> : null}
            {canRunTasks ? <button className="btn btn-ghost btn-sm" data-testid="delivery-empty-qa" onClick={onGoQA}>去校对</button> : null}
            <button className="btn btn-ghost btn-sm" data-testid="delivery-empty-archive" onClick={onGoArchive}>看归档</button>
          </div>
        </div>
      ) : null}
      {busy || (status && status !== '准备就绪') ? <ActionStatus status={status} busy={busy} /> : null}
      {sections ? <section data-testid="delivery-current">
        <div className="card-title"><div className="left">当前任务结果</div></div>
        {!sections.current.length && sections.past.length ? <p className="muted-inline">暂无带任务标识的当前结果；旧记录仅在历史中查看。</p> : null}
        <div className="delivery-list delivery-list-compact">
        {sections.current.map((task) => {
          const version = currentDeliveryVersion(task, history.data!.versions)
          const hasIssues = deliveryHasQaIssues(task)
          const partial = task.qa_status === 'mixed' || Boolean(task.skipped_languages?.length)
          const qaLabel = deliveryQaLabel(task.qa_status, task.qa_hard_errors)
          const running = ['created', 'queued', 'running'].includes(task.status)
          const closed = ['canceled', 'abandoned', 'closed'].includes(task.status) || ['canceled', 'abandoned', 'closed'].includes(task.task_state || '')
          const readOnly = closed || task.status === 'delivered' || task.task_state === 'delivered'
          const currentSummary = deliverables.find((item) => item.run_id === task.run_id)
          const currentAnnouncement = task.task_kind === 'announcement' && version
            ? deliverables.find((item) => item.run_id === task.run_id && item.task_code === 'ANN') : undefined
          const files = [...(version?.files || []), ...(currentAnnouncement?.files.outputs || []), ...(currentAnnouncement?.files.qa_summary ? [currentAnnouncement.files.qa_summary] : [])]
          const missingSummary = !closed && task.can_generate && (currentDeliveryMissingQaSummary(task, currentSummary)
            || hasIssues && files.some((file) => file.filename.endsWith('.xlsx') && ['final', 'merged_final'].includes(file.kind)) && !files.some((file) => file.kind === 'qa_summary' && file.download_url))
          const canOpen = task.task_kind === 'announcement' ? project.announcement_tasks?.some((item) => item.id === task.task_id) : Boolean(deliveryProcessingRun(project, task))
          return (
            <div key={deliveryGroupKey(task)} className="delivery-card delivery-line" data-testid={`delivery-current-${task.run_id}`}>
              <div className="delivery-head">
                <div>
                  <strong>{task.input_label || deliveryTaskKindLabel[task.task_kind]} · {task.language}</strong>
                  <span title={`任务 ${task.task_id} · Run ${task.run_id}`}>{deliveryTaskKindLabel[task.task_kind]} · {currentSummary?.task_label || `任务 ${task.task_id.slice(-12)}`} · Run {task.run_id.slice(-8)}</span>
                </div>
                <span className={`tag ${hasIssues ? 'tag-warn' : qaLabel === 'QA 已通过' ? 'tag-done' : 'tag-doing'}`}>{readOnly ? '已结束' : running ? '处理中' : hasIssues ? '待处理' : files.length ? '已生成' : '待生成'}</span>
              </div>
              <div className={`delivery-outcome-strip ${hasIssues || qaLabel !== 'QA 已通过' ? 'warn' : 'ready'}`} data-testid={missingSummary ? 'delivery-missing-qa-summary' : hasIssues ? 'delivery-problem-warning' : undefined}>
                <strong>{qaLabel}</strong>
                <span>{readOnly ? '任务已结束；保留历史下载，不从交付页恢复执行。' : running ? '当前执行尚未完成；旧版本不代表本次结果。' : partial ? `未交付语言：${(task.skipped_languages || []).join(' / ') || '请查看 QA 摘要'}。当前下载不是完整多语言交付。` : hasIssues ? '请先处理当前问题；旧通过版本仅供历史参考。' : qaLabel === 'QA 已通过' ? '本次 QA 已通过，可生成或下载当前交付。' : '当前证据不完整，需回到任务重新 QA。'}</span>
                {readOnly && !closed && hasIssues && task.task_kind === 'translation' && currentSummary?.files.final?.filename.toLowerCase().endsWith('.xlsx') ? <span>如需继续修复，请到“校对”页选择成品，启动新的 QA 后修复；已交付记录保持不变。</span> : null}
                {readOnly && partial ? <span>未交付语言：{(task.skipped_languages || []).join(' / ') || '请查看 QA 摘要'}。当前下载不是完整多语言交付。</span> : null}
                {missingSummary ? <span>当前交付不完整，缺少 QA 摘要。请重新生成，补齐问题清单后再下载。</span> : null}
              </div>
              <div className="delivery-line-info">
                <div><span>本次 QA</span><strong>必修 {task.qa_hard_errors ?? '未知'} / 建议 {task.qa_soft_warnings ?? '未知'}</strong></div>
                <div><span>当前交付</span><strong>{version ? formatDateTime(version.generated_at) : '尚未生成'}</strong></div>
              </div>
              <div className="delivery-actions">
                {canRunTasks && !readOnly && (hasIssues || partial || running || !task.can_generate && !files.length) ? <button className="btn btn-primary btn-sm" disabled={busy || !onOpenCurrentTask || !canOpen} title={!canOpen ? '当前任务详情尚未同步，请刷新项目后再处理。' : undefined} onClick={() => onOpenCurrentTask?.(task)}>处理当前任务</button> : null}
                <DeliveryDownloadLinks files={files} />
                {canRunTasks && !closed && task.can_generate ? <button className={`btn ${hasIssues || files.length ? 'btn-ghost' : 'btn-primary'} btn-sm`} data-testid={`delivery-generate-${task.run_id}`} disabled={busy} onClick={async () => { const result = await onCreateDelivery(task.run_id); if (result) history.refresh() }}>
                  {missingSummary ? '重新生成并补齐摘要' : files.length ? '重新生成交付' : hasIssues ? '生成带问题交付' : '生成交付文件'}
                </button> : null}
              </div>
            </div>
          )
        })}
        </div>
      </section> : null}
      {sections?.past.length ? <details key={project.id} className="delivery-run-details" data-testid="delivery-history">
        <summary>历史版本（{sections.past.length}）· 只读查看与下载</summary>
        <div className="delivery-run-details-body delivery-list delivery-list-compact">
          {sections.past.map((version) => <HistoricalDelivery key={version.version_id} version={version} previousAvailable={sections.previousAvailable.has(version.version_id)} />)}
        </div>
      </details> : null}
    </div>
  )
}

function DeliveryDownloadLinks({ files }: { files: DeliveryFile[] }) {
  return <>{files.filter((file) => file.download_url).map((file) => <a key={`${file.kind}:${file.download_url}`} className="btn btn-ghost btn-sm" href={file.download_url} title={file.filename}>
    {file.kind === 'package' ? '下载交付包' : file.kind === 'qa_summary' ? '下载 QA 摘要' : file.kind === 'changes' ? '下载修改记录' : file.kind.startsWith('output_') ? `下载成品 ${file.kind.slice(7)}` : '下载最终译文'}
  </a>)}</>
}

function HistoricalDelivery({ version, previousAvailable }: { version: DeliveryVersion; previousAvailable: boolean }) {
  const qa = version.qa_snapshot
  return <div className="delivery-card delivery-line" data-testid={`delivery-version-${version.version_id}`}>
    <div className="delivery-head">
      <div>
        <strong>{deliveryTaskKindLabel[version.task_kind]} · {version.language}</strong>
        <span title={`版本 ${version.version_id} · 任务 ${version.task_id || '无'} · Run ${version.run_id}`}>版本 {version.version_id.slice(-8)} · {version.generated_at ? formatDateTime(version.generated_at) : '生成时间未知'} · Run {version.run_id.slice(-8) || '未知'}</span>
      </div>
      <span className={`tag ${previousAvailable ? 'tag-done' : ''}`}>{previousAvailable ? '上一可用版' : '历史版本'}</span>
    </div>
    <div className={`delivery-outcome-strip ${qa.status === 'passed' && qa.hard_errors === 0 ? 'ready' : 'warn'}`}>
      <strong>当时 {deliveryQaLabel(qa.status, qa.hard_errors)}</strong>
      <span>{version.history_complete ? `必修 ${qa.hard_errors ?? '未知'} / 建议 ${qa.soft_warnings ?? '未知'}` : '历史信息不完整：缺少当时 QA 快照或任务标识。'}</span>
      {!version.task_id ? <span>无任务 ID，不作为当前任务恢复依据。</span> : null}
      {version.language_results?.some((item) => item.status === 'skipped') ? <span>当时未交付：{version.language_results.filter((item) => item.status === 'skipped').map((item) => item.language).join(' / ')}</span> : null}
      {version.available === false ? <span>部分文件已缺失，仅可下载仍保留的文件。</span> : null}
    </div>
    <div className="delivery-actions"><DeliveryDownloadLinks files={version.files} /></div>
  </div>
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
  if (String(task.task_code || '').toUpperCase() === 'ALL' && task.skipped_languages?.length) return '部分交付'
  if (task.status === 'delivered') return task.delivered_with_issues ? '带问题已交付' : '已交付'
  if (task.delivered_with_issues) return '带问题可交付'
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
