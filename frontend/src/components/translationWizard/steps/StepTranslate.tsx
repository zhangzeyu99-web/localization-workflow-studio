import { artifactDownloadHref, artifactKindLabel, artifactPickerLabel, newestArtifact, pickerArtifacts, runArtifacts } from '../../../domain/artifacts'
import { projectPromptForLanguage } from '../../../domain/projectAssets'
import { canSkipModelTranslation, effectiveBatchSize, estimateBatches, findVisibleTranslationRun, getTranslationProgress, isTranslationRunResumable, matchesTranslationRun, multilingualWorkflowItems } from '../../../domain/translationFlow'
import { languageSpec, type LanguageCode } from '../../../languages'
import { ActionStatus, AssetSelect, TranslationProgressBar } from '../../shared/WorkflowPrimitives'
import { LineProofreadTimeline, ReferenceAuditPanel } from '../../shared/StatusPrimitives'
import { AiInputAuditPanel } from '../../shared/AiInputAudit'
import type { AppSettings, Artifact, LargeTextRunState, Project, QualityIssue, ReferenceAuditState, Run, TranslationProgress, TranslationReadiness } from '../../../types'
import { formalTranslationBlockReason, translationReadinessBlockReason } from '../translationGuards'
import { LINE_PROOFREAD_HINT, LINE_PROOFREAD_LABEL, lineProofreadSummaryText } from '../../../uiText'
import type { LineProofreadState } from '../../../types'
import { TaskRunSummary } from '../TaskRunSummary'
import { WorkflowFactList, WorkflowSideCard, WorkflowStepShell } from '../WorkflowStepShell'
import { MultilingualWorkflowBoard } from '../MultilingualWorkflowBoard'

function LargeTextPanel({ run, readiness, selectedLanguageCount }: { run?: Run | null; readiness?: TranslationReadiness | null; selectedLanguageCount: number }) {
  const state = run?.metadata?.large_text as LargeTextRunState | undefined
  const preflight = state?.preflight
  const estimatedCells = readiness ? readiness.source_rows * Math.max(1, selectedLanguageCount) : preflight?.estimated_target_cells
  const large = Boolean(preflight?.large_pack || (estimatedCells && estimatedCells > 25000) || (readiness && readiness.source_rows > 5000) || selectedLanguageCount > 4)
  const cache = state?.cache_lint
  return (
    <div className={`large-text-panel ${large ? 'large' : ''}`} data-testid="large-text-panel">
      <div className="readiness-head">
        <strong>大文本处理</strong>
        <span>{large ? '已启用自动门禁' : '普通规模'}</span>
      </div>
      <p>{preflight ? `${preflight.unique_items || 0} 条唯一文本 / ${preflight.estimated_target_cells || 0} 个目标单元 / 长文本 ${preflight.long_text_items || 0} 条` : `预计 ${estimatedCells || '-'} 个目标单元`}</p>
      {cache ? <p>cache-lint: {cache.status || '-'}{typeof cache.hard_blockers === 'number' ? ` / hard ${cache.hard_blockers}` : ''}</p> : <p>启动后会记录 preflight 和 cache-lint。</p>}
    </div>
  )
}

export function StepTranslate({
  project,
  settings,
  status,
  onTranslate,
  onTranslateQueue,
  onCancelTranslate,
  busy,
  latestRun,
  qualityIssues,
  translationReadiness,
  sourceArtifact,
  termArtifact,
  setSourceArtifact,
  setTermArtifact,
  setQaArtifact,
  setStep,
  selectedLanguage,
  setSelectedLanguage,
  selectedLanguages,
  lineProofread,
  setLineProofread
}: {
  project: Project
  settings: AppSettings | null
  status: string
  onTranslate: () => void
  onTranslateQueue?: () => void
  onCancelTranslate: (run?: Run | null) => void
  busy: boolean
  latestRun: Run | null
  qualityIssues: QualityIssue[]
  translationReadiness: TranslationReadiness | null
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  lineProofread: boolean
  setLineProofread: (value: boolean) => void
}) {
  const lang = languageSpec(selectedLanguage)
  const multiLanguageMode = selectedLanguages.length > 1
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const batchSize = effectiveBatchSize(settings)
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === batchSize ? translationReadiness : null
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project, readiness)
  const currentLanguageAlreadyTranslated = canSkipModelTranslation(readiness)
  const alreadyTranslated = currentLanguageAlreadyTranslated && !multiLanguageMode
  const estimatedBatches = estimateBatches(readiness?.source_rows, batchSize)
  const latestMatchingRun = latestRun && matchesTranslationRun(latestRun, selectedLanguage, sourceArtifact?.id, 'translation_run') ? latestRun : null
  const currentTranslationRun = latestMatchingRun || findVisibleTranslationRun(project, selectedLanguage, sourceArtifact?.id, 'translation_run')
  const progress = getTranslationProgress(currentTranslationRun)
  const termAudit = (progress?.term_audit || currentTranslationRun?.metadata?.term_audit) as TranslationProgress['term_audit'] | undefined
  const termAuditWarning = currentTranslationRun?.metadata?.reason === 'glossary_candidates_not_confirmed'
    ? String(currentTranslationRun.metadata?.user_message || '候选术语尚未确认，当前翻译已暂停；请回「术语候选」步骤确认术语，或再次启动并确认继续无术语翻译。')
    : currentTranslationRun?.metadata?.reason === 'selected_term_artifact_empty'
      ? String(currentTranslationRun.metadata?.user_message || '已选择本次术语表，但没有读取到可用术语；请检查术语表格式和目标语言列。')
    : termAudit?.warning === 'no_term_hits'
      ? '本次 workpack 没有命中术语；如果你已提供术语表，请检查术语是否已加入项目术语库或作为本次术语表输入。'
      : ''
  const languageProgressItems = multilingualWorkflowItems(project, selectedLanguages, sourceArtifact?.id)
  const multilingualActive = multiLanguageMode && languageProgressItems.some((item) => item.state === 'running')
  const multilingualHasResults = multiLanguageMode && languageProgressItems.every((item) => item.state === 'ready' || item.state === 'issues')
  const multilingualStarted = multiLanguageMode && languageProgressItems.some((item) => item.run)
  const multilingualRetryCount = languageProgressItems.filter((item) => item.state === 'pending' || item.state === 'blocked').length
  const lineProofreadState = currentTranslationRun?.metadata?.line_proofread as LineProofreadState | undefined
  const referenceAuditState = currentTranslationRun?.metadata?.reference_audit as ReferenceAuditState | undefined
  const activeTranslation = multiLanguageMode ? multilingualActive : Boolean(currentTranslationRun && ['queued', 'running'].includes(currentTranslationRun.status))
  const finishingTranslation = Boolean(activeTranslation && progress && progress.total_rows > 0 && progress.completed_rows >= progress.total_rows)
  const resumable = Boolean(currentTranslationRun && isTranslationRunResumable(currentTranslationRun))
  const invalidIdText = readiness?.invalid_id_rows ? ` / 空 ID ${readiness.invalid_id_rows}` : ''
  const readinessBatchText = progress?.total_batches
    ? ` / 后台实际拆分 ${progress.total_batches} 批`
    : readiness
      ? ` / 启动前估算 ${readiness.estimated_batches} 批`
      : ''
  const readinessText = readiness
    ? `${readiness.source_rows} 行原文 / ${readiness.translated_rows} 行已有译文 / 空译文 ${readiness.empty_target_rows} / 中文残留 ${readiness.cjk_target_rows}${invalidIdText}${readinessBatchText}`
    : '选择语言表后自动检查'
  const readinessState = !sourceArtifact
    ? { label: '未选择语言表', tone: 'idle' }
    : !readiness
      ? { label: '正在检查', tone: 'checking' }
      : translationReadinessBlockReason(readiness)
        ? { label: '需要修正表结构', tone: 'todo' }
      : alreadyTranslated
        ? { label: '可直接校对', tone: 'ready' }
        : { label: '需要翻译', tone: 'todo' }
  const scopedTranslateStatus = /交付|delivery/i.test(status) ? '' : status
  const showTranslateStatus = Boolean(scopedTranslateStatus) && (busy
    || Boolean(progress)
    || /provider|API|workpack|batch|QA|\u7ffb\u8bd1|\u6821\u5bf9/i.test(scopedTranslateStatus))
  const translationArtifacts = pickerArtifacts(currentTranslationRun?.artifacts?.length ? currentTranslationRun.artifacts : runArtifacts(project, currentTranslationRun?.id))
    .filter((artifact) => ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'].includes(artifact.kind))
  const qaInputArtifact = newestArtifact(translationArtifacts, ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
  const canEnterQa = multiLanguageMode
    ? multilingualHasResults
    : Boolean(alreadyTranslated || qaInputArtifact || (progress && progress.total_rows > 0 && progress.completed_rows >= progress.total_rows))
  const enterQa = () => {
    setQaArtifact(qaInputArtifact || sourceArtifact)
    setStep(8)
  }
  const statusTone = activeTranslation ? 'running' : canEnterQa ? 'ready' : blockReason ? 'blocked' : readinessState.tone === 'todo' ? 'warn' : 'neutral'
  const nextAction = activeTranslation
    ? '等待当前批次完成'
    : canEnterQa
      ? '进入 QA 校对'
      : blockReason
        ? '先处理输入或配置'
        : '点击开始 AI 翻译'
  return (
    <WorkflowStepShell
      stepLabel="步骤 7/9"
      title="AI 翻译"
      description="确认输入并开始翻译。"
      status={readinessState.label}
      statusTone={statusTone}
      nextAction={nextAction}
      side={
        <WorkflowSideCard title="本次输入" tone={canEnterQa ? 'ready' : blockReason ? 'blocked' : 'neutral'}>
          <WorkflowFactList items={[
            { label: '文件', value: sourceArtifact ? artifactPickerLabel(sourceArtifact) : '未选择' },
            { label: '语言', value: lang.short },
            { label: '术语', value: `${glossaryCount} 条` },
            { label: '历史译文', value: referenceAuditState ? `${Number(referenceAuditState.archive_entries || 0)} 条` : `${project.stats.archived_rows || 0} 条` },
          ]} />
        </WorkflowSideCard>
      }
    >
      {selectedLanguages.length > 1 ? (
        <MultilingualWorkflowBoard
          project={project}
          languages={selectedLanguages}
          inputArtifactId={sourceArtifact?.id}
          selectedLanguage={selectedLanguage}
          onSelectLanguage={setSelectedLanguage}
        />
      ) : null}
      <div className="action-card workflow-block">
        <AssetSelect label="输入文件" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} />
        <div className="translation-input-summary">
          <div><span>状态</span><strong>{readinessState.label}</strong></div>
          <div><span>规模</span><strong>{readiness ? `${readiness.source_rows} 行` : '-'}</strong></div>
          <div><span>批次</span><strong>{progress?.total_batches ? `${progress.completed_batches}/${progress.total_batches}` : estimatedBatches || '-'}</strong></div>
        </div>
        {!alreadyTranslated ? (
          <label className="line-proofread-toggle" data-testid="line-proofread-toggle">
            <input
              type="checkbox"
              checked={lineProofread}
              disabled={busy || activeTranslation}
              onChange={(event) => setLineProofread(event.target.checked)}
            />
            <span>
              <strong>{LINE_PROOFREAD_LABEL}</strong>
              <em>{LINE_PROOFREAD_HINT}</em>
            </span>
          </label>
        ) : null}
        {lineProofread || lineProofreadState ? (
          <div data-testid={lineProofreadState ? 'line-proofread-summary' : undefined}>
            <LineProofreadTimeline state={lineProofreadState} enabled={lineProofread} />
            {lineProofreadState ? <span className="sr-only">{lineProofreadSummaryText(lineProofreadState)}</span> : null}
          </div>
        ) : null}
        <div className="translation-actions">
          {canEnterQa ? (
            <button className="btn btn-primary" disabled={busy} onClick={enterQa}>进入 QA</button>
          ) : alreadyTranslated ? (
            <>
              <div className="ok-line">已检测到完整译文。</div>
              <button className="btn btn-primary" disabled={busy} onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>进入 QA</button>
            </>
          ) : (
            <>
              <button
                className="btn btn-primary"
                data-testid={multiLanguageMode ? 'multilingual-translate' : 'single-language-translate'}
                disabled={busy || activeTranslation || Boolean(blockReason)}
                onClick={multiLanguageMode ? (onTranslateQueue || onTranslate) : onTranslate}
              >
                {multiLanguageMode
                  ? multilingualStarted
                    ? `继续处理 ${multilingualRetryCount || selectedLanguages.length} 种未完成语言`
                    : `开始翻译全部 ${selectedLanguages.length} 种语言`
                  : resumable ? '继续 AI 翻译' : '开始 AI 翻译'}
              </button>
              {activeTranslation ? <button className="btn btn-ghost" disabled={busy} onClick={() => onCancelTranslate(currentTranslationRun)}>暂停</button> : null}
            </>
          )}
          {blockReason && !alreadyTranslated ? (
            <div className="warn-line inline-warning">
              {blockReason}
              {(!sourceArtifact || translationReadinessBlockReason(readiness)) ? (
                <div className="row-actions wrap">
                  <button className="btn btn-ghost btn-sm" type="button" data-testid="translate-block-goto-source" onClick={() => setStep(4)}>返回判定输入</button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        {showTranslateStatus ? <ActionStatus status={scopedTranslateStatus} busy={busy} /> : null}
        {progress ? <TranslationProgressBar progress={progress} languageLabel={lang.short} /> : null}
        {termAuditWarning ? (
          <div className="warn-line">
            {termAuditWarning}
            <div className="row-actions wrap">
              <button className="btn btn-ghost btn-sm" type="button" onClick={() => setStep(5)}>返回确认术语</button>
            </div>
          </div>
        ) : null}
        {finishingTranslation ? <div className="info-line compact">正在校验并保存结果。</div> : null}
        {currentTranslationRun?.metadata?.reason === 'api_budget_confirmation_required' ? (
          <div className="warn-line">预计 API token 超过提醒阈值；点击“继续后台翻译”会二次确认预算，并从已完成批次继续。</div>
        ) : null}
        {currentTranslationRun?.metadata?.reason === 'background_job_interrupted' ? (
          <div className="warn-line">上次后台任务被中断；点击“继续后台翻译”可从已落盘批次恢复。</div>
        ) : null}
        {progress?.failed_batch && currentTranslationRun ? <BatchDebugLinks runId={currentTranslationRun.id} batchIndex={progress.failed_batch} /> : null}
        <details className="translation-details">
          <summary>查看处理详情</summary>
          <div className="translation-details-body">
            <div className="muted-left">{readinessText}</div>
            <LargeTextPanel run={currentTranslationRun} readiness={readiness} selectedLanguageCount={selectedLanguages.length} />
            <div className="translation-batch-panel compact">
              <div className="batch-control-head">
                <div><strong>后台批次</strong></div>
                <em>{alreadyTranslated ? '无需翻译' : progress?.total_batches ? `${progress.completed_batches}/${progress.total_batches} 批` : `预计 ${estimatedBatches || '-'} 批`}</em>
              </div>
            </div>
            <ReferenceAuditPanel state={referenceAuditState} />
            {translationArtifacts.length ? (
              <div className="artifact-grid compact-artifact-grid">
                {translationArtifacts.map((artifact) => <a key={artifact.id} className="artifact" href={artifactDownloadHref(artifact, project.id)}>{artifactPickerLabel(artifact)}<span>{artifactKindLabel(artifact)}</span></a>)}
              </div>
            ) : null}
            {currentTranslationRun ? <AiInputAuditPanel endpoint={`/api/runs/${currentTranslationRun.id}/ai-input-summary`} title={`${lang.short} 本次翻译 AI 输入`} buttonLabel="查看本次 AI 输入" /> : null}
            <div className="translation-guard-strip">
              <span>提示词 <strong>{projectPromptForLanguage(project, selectedLanguage) ? '已生成' : '未生成'}</strong></span>
              <span>术语 <strong>{glossaryCount} 条</strong></span>
            </div>
            {currentTranslationRun ? <TaskRunSummary run={currentTranslationRun} issues={qualityIssues} /> : null}
          </div>
        </details>
      </div>
    </WorkflowStepShell>
  )
}

export function BatchDebugLinks({ runId, batchIndex }: { runId: string; batchIndex: number }) {
  return (
    <div className="row-actions wrap">
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/request`}>下载失败批次输入</a>
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/error`}>下载错误报告</a>
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/raw-response`}>下载问题批次</a>
    </div>
  )
}
