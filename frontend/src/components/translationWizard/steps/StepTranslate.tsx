import { artifactDownloadHref, artifactKindLabel, artifactPickerLabel, newestArtifact, pickerArtifacts, runArtifacts } from '../../../domain/artifacts'
import { projectPromptForLanguage } from '../../../domain/projectAssets'
import { canSkipModelTranslation, effectiveBatchSize, estimateBatches, findVisibleTranslationRun, getTranslationProgress, isTranslationRunResumable, matchesTranslationRun } from '../../../domain/translationFlow'
import { languageSpec, type LanguageCode } from '../../../languages'
import { ActionStatus, AssetSelect, TranslationProgressBar } from '../../shared/WorkflowPrimitives'
import { AiInputAuditPanel } from '../../shared/AiInputAudit'
import type { AppSettings, Artifact, LargeTextRunState, Project, QualityIssue, Run, TranslationProgress, TranslationReadiness } from '../../../types'
import { formalTranslationBlockReason, translationReadinessBlockReason } from '../translationGuards'
import { TaskRunSummary } from '../TaskRunSummary'
import { WorkflowFactList, WorkflowSideCard, WorkflowStepShell } from '../WorkflowStepShell'

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
  selectedLanguages
}: {
  project: Project
  settings: AppSettings | null
  status: string
  onTranslate: () => void
  onTranslateQueue?: () => void
  onCancelTranslate: () => void
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
  selectedLanguages: LanguageCode[]
}) {
  const lang = languageSpec(selectedLanguage)
  const selectedLanguageText = selectedLanguages.map((code) => languageSpec(code).short).join(' / ')
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
  const languageProgressItems = selectedLanguages.map((code) => {
    const run = findVisibleTranslationRun(project, code, sourceArtifact?.id, 'translation_run')
    const itemProgress = getTranslationProgress(run)
    const percent = itemProgress ? Math.max(0, Math.min(100, Number(itemProgress.percent || 0))) : null
    const blocked = Boolean(itemProgress?.failed_batch || run?.status === 'failed')
    const active = Boolean(run && ['queued', 'running'].includes(run.status))
    const done = Boolean(run?.status === 'passed')
    const finishing = Boolean(active && itemProgress && itemProgress.total_rows > 0 && itemProgress.completed_rows >= itemProgress.total_rows)
    const label = blocked
      ? '需继续/修复'
      : active
        ? finishing ? '校验归档中' : '翻译中'
        : done
          ? '已完成'
          : run
            ? '可继续'
            : code === selectedLanguage
              ? '当前待启动'
              : '待处理'
    return { code, run, progress: itemProgress, percent, blocked, done, active, label }
  })
  const activeTranslation = Boolean(currentTranslationRun && ['queued', 'running'].includes(currentTranslationRun.status))
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
  const canEnterQa = Boolean(alreadyTranslated || qaInputArtifact || (progress && progress.total_rows > 0 && progress.completed_rows >= progress.total_rows))
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
      stepLabel="STEP 7"
      title={`${lang.short} AI 翻译`}
      description="确认输入、启动或续跑 AI 翻译；已有译文的表格直接进入 QA。"
      status={readinessState.label}
      statusTone={statusTone}
      nextAction={nextAction}
      side={
        <>
          <WorkflowSideCard title="下一步" tone={canEnterQa ? 'ready' : blockReason ? 'blocked' : 'neutral'}>
            <p>{canEnterQa ? '翻译结果已可用于 QA，下一步检查术语、变量和中文残留。' : blockReason || '准备好输入后启动 AI 翻译，系统会自动拆批并保存进度。'}</p>
            <button className="btn btn-primary btn-sm" disabled={!canEnterQa || busy} onClick={enterQa}>进入 QA 校对</button>
          </WorkflowSideCard>
          <WorkflowSideCard title="输入与门槛">
            <WorkflowFactList items={[
              { label: '语言表', value: sourceArtifact ? artifactPickerLabel(sourceArtifact) : '未选择' },
              { label: '项目术语库', value: `${glossaryCount} 条` },
              { label: `${lang.short} 提示词`, value: projectPromptForLanguage(project, selectedLanguage) ? '已生成' : '未生成' },
              { label: '后台批次', value: progress?.total_batches ? `${progress.completed_batches}/${progress.total_batches} 批` : `${estimatedBatches || '-'} 批估算` },
            ]} />
          </WorkflowSideCard>
          <WorkflowSideCard title="本步产物" tone={translationArtifacts.length ? 'ready' : 'neutral'}>
            <div className="artifact-grid compact-artifact-grid">
              {translationArtifacts.map((artifact) => <a key={artifact.id} className="artifact" href={artifactDownloadHref(artifact, project.id)}>{artifactPickerLabel(artifact)}<span>{artifactKindLabel(artifact)}</span></a>)}
              {!translationArtifacts.length ? <div className="muted-left">翻译完成后这里会出现可用于 QA 的译文表。</div> : null}
            </div>
          </WorkflowSideCard>
        </>
      }
    >
      {selectedLanguages.length > 1 ? (
        <div className="translation-language-progress">
          <div className="section-head">
            <div>
              <strong>多语言处理进度</strong>
              <span>已选 {selectedLanguageText}；点击一次后工作台会按语言排队执行。每种语言独立保存进度，失败后只续跑对应语言。</span>
            </div>
          </div>
          <div className="translation-language-grid">
            {languageProgressItems.map((item) => (
              <div key={item.code} className={`translation-language-card ${item.code === selectedLanguage ? 'current' : ''} ${item.blocked ? 'blocked' : ''} ${item.done ? 'done' : ''}`}>
                <strong>{languageSpec(item.code).short}</strong>
                <span>{item.label}</span>
                <em>{item.progress ? `${item.progress.completed_rows}/${item.progress.total_rows} 行 · ${item.percent?.toFixed(0)}%` : '尚未生成进度'}</em>
              </div>
            ))}
          </div>
          <div className="info-line compact">操作方式：点击“开始多语言翻译”，工作台会自动逐个处理已选语言；无需反复回「目标语言」步骤手动切换。</div>
        </div>
      ) : null}
      <div className="action-card workflow-block">
        <AssetSelect label="语言表输入" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} />
        <div className={`translation-readiness-box ${readinessState.tone}`}>
          <div className="readiness-head">
            <strong>译文检查</strong>
            <span>{readinessState.label}</span>
          </div>
          <p>{readinessText}</p>
        </div>
        <LargeTextPanel run={currentTranslationRun} readiness={readiness} selectedLanguageCount={selectedLanguages.length} />
        <div className="translation-batch-panel compact">
          <div className="batch-control-head">
            <div>
              <strong>{alreadyTranslated ? '分流结果' : '后台编排'}</strong>
              <span>{alreadyTranslated ? '已识别为完整译文表，本步骤不调用 AI。' : '系统按预设自动拆批、限流、重试和断点续跑。'}</span>
            </div>
            <em>{alreadyTranslated ? '下一步：QA 校对' : progress?.total_batches ? `后台实际 ${progress.total_batches} 批 · 当前第 ${progress.current_batch || '-'} 批` : `${batchSize} 行/批 · 启动前估算 ${estimatedBatches || '-'} 批`}</em>
          </div>
        </div>
        <div className="translation-actions">
          {alreadyTranslated ? (
            <>
              <div className="ok-line">检测到这份表已有译文：无需 AI 翻译，默认进入 QA；如确需跳过 QA，可在「QA 校对」步骤使用“临时跳过 QA 直接归档”。</div>
              <button className="btn btn-primary" disabled={busy} onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>跳到校对</button>
            </>
          ) : (
            <>
              <button className="btn btn-primary" disabled={busy || activeTranslation || Boolean(blockReason)} onClick={onTranslate}>{resumable ? '继续 AI 翻译' : '开始 AI 翻译'}</button>
              {activeTranslation ? <button className="btn btn-ghost" disabled={busy} onClick={onCancelTranslate}>暂停</button> : null}
            </>
          )}
          {blockReason && !alreadyTranslated ? <div className="warn-line inline-warning">{blockReason}</div> : null}
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
        {finishingTranslation ? <div className="info-line compact">译文批次已完成，正在做 QA 校验和结果归档。完成后会自动接到「QA 校对」步骤；请不要在此时重复启动。</div> : null}
        {currentTranslationRun?.metadata?.reason === 'api_budget_confirmation_required' ? (
          <div className="warn-line">预计 API token 超过提醒阈值；点击“继续后台翻译”会二次确认预算，并从已完成批次继续。</div>
        ) : null}
        {currentTranslationRun?.metadata?.reason === 'background_job_interrupted' ? (
          <div className="warn-line">上次后台任务被中断；点击“继续后台翻译”可从已落盘批次恢复。</div>
        ) : null}
        {progress?.failed_batch && currentTranslationRun ? <BatchDebugLinks runId={currentTranslationRun.id} batchIndex={progress.failed_batch} /> : null}
        {currentTranslationRun ? (
          <AiInputAuditPanel endpoint={`/api/runs/${currentTranslationRun.id}/ai-input-summary`} title={`${lang.short} 本次翻译 AI 输入`} buttonLabel="查看本次 AI 输入" />
        ) : (
          <div className="muted-left">开始翻译后，可查看本次 AI 实际收到的项目要求、术语命中和样例行。</div>
        )}
      </div>
      <div className="translation-guard-strip">
        <span>项目术语库 <strong>{glossaryCount} 条</strong></span>
        <span>{lang.short} 提示词 <strong>{projectPromptForLanguage(project, selectedLanguage) ? '已生成' : '未生成'}</strong></span>
        <span>校对门槛 <strong>QA 通过后交付</strong></span>
      </div>
      {currentTranslationRun ? <TaskRunSummary run={currentTranslationRun} issues={qualityIssues} /> : null}
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
