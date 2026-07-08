import { useEffect, useState } from 'react'
import { artifactDownloadHref, artifactRole, newestArtifact, pickerArtifacts, runArtifacts } from '../../../domain/artifacts'
import { canSkipModelTranslation, latestRunOfKind } from '../../../domain/translationFlow'
import { languageSpec, supportedLanguages, type LanguageCode } from '../../../languages'
import { ActionStatus, AssetSelect, FileBox } from '../../shared/WorkflowPrimitives'
import type { ConfirmDialogOptions } from '../../modals/ConfirmModal'
import type { Artifact, Project, QualityIssue, Run, TranslationReadiness } from '../../../types'
import {
  IssueChips,
  IssueGuide,
  IssueSummary,
  issueHumanMessage,
  issueSourceLabel,
  issueTypeLabel,
  qaPendingIssueCount,
  qaRunActionText,
  qaRunSummaryText,
  qaRunTagClass,
  qaStatusBadge,
  severityLabel
} from '../QaIssuePanel'
import { TaskHistoryTable } from '../TaskHistoryTable'
import { WorkflowSideCard, WorkflowStepShell } from '../WorkflowStepShell'

export function StepQA({
  project,
  latestRun,
  sourceArtifact,
  translationReadiness,
  qualityIssues,
  qaArtifact,
  setQaArtifact,
  onDirectQA,
  onDirectQAQueue,
  onSkipQAArchive,
  allowSkipQAArchive = false,
  onManualFixes,
  onModelFixes,
  onUploadTranslation,
  busy,
  status,
  selectedLanguage,
  setSelectedLanguage,
  selectedLanguages,
  toggleSelectedLanguage,
  onGoDelivery,
  showHistory = true,
  confirm
}: {
  project: Project
  latestRun: Run | null
  sourceArtifact: Artifact | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  qaArtifact: Artifact | null
  setQaArtifact: (artifact: Artifact | null) => void
  onDirectQA: (artifact?: Artifact | null) => void
  onDirectQAQueue?: () => void
  onSkipQAArchive: (artifact?: Artifact | null) => void
  allowSkipQAArchive?: boolean
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  busy: boolean
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
  onGoDelivery?: () => void
  showHistory?: boolean
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
}) {
  const latestQaRun = latestRun?.kind === 'qa' ? latestRun : latestRunOfKind(project, 'qa')
  const projectQuality = latestQaRun?.metadata?.project_harness_quality as { hard_errors?: number; soft_warnings?: number } | undefined
  const projectHardErrors = projectQuality?.hard_errors ?? 0
  const qaIssues = latestRun?.id === latestQaRun?.id ? qualityIssues.filter((issue) => issue.severity === 'hard' || issue.severity === 'soft') : []
  const previousTranslationRun = latestRunOfKind(project, 'translation')
  const previousTranslationArtifact = previousTranslationRun
    ? newestArtifact(runArtifacts(project, previousTranslationRun.id), ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
    : null
  const effectiveQaArtifact = qaArtifact || previousTranslationArtifact || null
  const translationQaRun = previousTranslationRun && previousTranslationArtifact ? previousTranslationRun : null
  const qaStatusRun = latestQaRun && (!translationQaRun || latestQaRun.created_at >= translationQaRun.created_at) ? latestQaRun : translationQaRun
  const qaStatusArtifacts = qaStatusRun ? pickerArtifacts(qaStatusRun.artifacts?.length ? qaStatusRun.artifacts : runArtifacts(project, qaStatusRun.id)) : []
  const qaFinalDownload = newestArtifact(qaStatusArtifacts, ['qa_final_workbook'])
  const qaChangesDownload = newestArtifact(qaStatusArtifacts, ['qa_changes'])
  const qaRole = effectiveQaArtifact ? artifactRole(effectiveQaArtifact) : ''
  const selectedReadiness = effectiveQaArtifact && translationReadiness?.artifact_id === effectiveQaArtifact.id ? translationReadiness : null
  const canArchiveWithoutQA = Boolean(effectiveQaArtifact && (qaRole !== 'language_source' || canSkipModelTranslation(selectedReadiness)))
  const skipArchiveHint = !effectiveQaArtifact
    ? '先选择已有译文表。'
    : qaRole === 'language_source' && !selectedReadiness
      ? '系统正在检查这份语言表是否已有完整译文。'
      : qaRole === 'language_source' && !canSkipModelTranslation(selectedReadiness)
        ? '这份语言表还不是完整译文表，不能跳过 QA 直接归档。'
        : '只在外部已经完成校对，或临时需要先入库供公告反查时使用。'
  const handleSkipArchive = async () => {
    const artifact = effectiveQaArtifact
    if (!artifact || !canArchiveWithoutQA) return
    const confirmed = await confirm('跳过 QA 会把当前译文直接写入译文归档，系统不会检查术语、变量、中文残留。确认继续？', {
      title: '跳过 QA 直接归档',
      confirmLabel: '确认跳过',
      cancelLabel: '取消',
      tone: 'warn'
    })
    if (confirmed) onSkipQAArchive(artifact)
  }
  const originText = effectiveQaArtifact?.run_id && previousTranslationRun?.id === effectiveQaArtifact.run_id
    ? `上一翻译结果：${previousTranslationRun.id.slice(0, 8)}`
    : qaRole === 'language_source'
      ? sourceArtifact?.id === effectiveQaArtifact?.id && selectedReadiness
        ? `来自「判定输入」步骤已译表：${selectedReadiness.translated_rows}/${selectedReadiness.source_rows} 行已有译文`
        : selectedReadiness
        ? `此前导入的语言表：${selectedReadiness.translated_rows}/${selectedReadiness.source_rows} 行已有译文`
        : '此前导入的语言表；运行前会按译文表检查'
      : qaArtifact
        ? '直接导入的译文表格'
        : sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness)
          ? '已检测到当前语言表可进入校对，可直接选择运行'
          : '请选择要校对的译文表'
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const pendingIssueCount = qaPendingIssueCount(qaStatusRun, qaIssues)
  const qaStatus = qaRunSummaryText(qaStatusRun, pendingIssueCount)
  const qaNextAction = qaRunActionText(qaStatusRun, pendingIssueCount)
  const selectedLanguageText = selectedLanguages.map((code) => languageSpec(code).short).join(' / ')
  const currentLanguageText = languageSpec(selectedLanguage).short
  const qaTone = qaStatusRun?.status === 'passed' ? 'ready' : qaStatusRun?.status === 'failed' ? 'warn' : busy ? 'running' : 'neutral'
  const qaStatusLabel = qaStatusRun ? qaStatusBadge(qaStatusRun.status) : '等待运行'
  const qaActionStatus = status !== '准备就绪' ? status : ''
  const scrollToManualFixes = () => {
    document.querySelector('[data-testid="failed-row-editor"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  return (
    <WorkflowStepShell
      stepLabel="STEP 8"
      title="QA 校对任务"
      description="先确认校对输入，再运行 QA。未通过时先修复并重跑；急需时可带问题摘要交付。"
      status={qaStatusLabel}
      statusTone={qaTone}
      nextAction={qaNextAction}
      side={
        <>
          <div className={`qa-current-card ${qaStatusRun?.status === 'failed' ? 'qa-failed' : qaStatusRun?.status === 'passed' ? 'qa-passed' : ''}`}>
            <div className="qa-current-head">
              <div>
                <strong>QA 结论</strong>
                <span>{qaStatus}</span>
              </div>
              <span className={`tag ${qaRunTagClass(qaStatusRun)}`}>{qaStatusRun ? qaStatusBadge(qaStatusRun.status) : '未运行'}</span>
            </div>
            <div className="qa-current-grid compact-grid">
              <div><span>校对文件</span><strong>{effectiveQaArtifact ? effectiveQaArtifact.label : '未选择'}</strong></div>
              <div><span>文件来源</span><strong>{originText}</strong></div>
              <div><span>术语数量</span><strong>{glossaryCount} 条</strong></div>
              <div><span>建议动作</span><strong>{qaNextAction}</strong></div>
            </div>
            {qaStatusRun?.status === 'failed' ? (
              <div className="qa-blocker-line">
                已保留译文文件和 QA 摘要。建议先修复并重跑；急需交付时，交付文件会附带问题摘要。
              </div>
            ) : null}
            {(qaFinalDownload || qaChangesDownload || (qaStatusRun && ['passed', 'failed'].includes(qaStatusRun.status) && onGoDelivery)) ? (
              <div className="qa-result-actions">
                {qaFinalDownload ? <a className="btn btn-ghost btn-sm" data-testid="qa-download-final" href={artifactDownloadHref(qaFinalDownload, project.id)}>下载校对后译文</a> : null}
                {qaChangesDownload ? <a className="btn btn-ghost btn-sm" data-testid="qa-download-changes" href={artifactDownloadHref(qaChangesDownload, project.id)}>下载修改记录</a> : null}
                {onGoDelivery && qaStatusRun && ['passed', 'failed'].includes(qaStatusRun.status) ? (
                  <button className="btn btn-primary btn-sm" data-testid="qa-go-delivery" onClick={onGoDelivery}>
                    {qaStatusRun.status === 'failed' ? '带问题摘要交付' : '进入交付'}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
          <WorkflowSideCard title="建议处理" tone={qaStatusRun?.status === 'failed' ? 'warn' : 'neutral'}>
            <div className="workflow-action-stack">
              <button className="btn btn-primary btn-sm" disabled={busy || !qaIssues.length} onClick={onModelFixes}>模型修复并重跑 QA</button>
              <button className="btn btn-ghost btn-sm" disabled={!qaIssues.length} onClick={scrollToManualFixes}>手动逐条修复</button>
              <button className="btn btn-ghost btn-sm" disabled={!onGoDelivery || !qaStatusRun || !['passed', 'failed'].includes(qaStatusRun.status)} onClick={() => onGoDelivery?.()}>查看交付页</button>
            </div>
          </WorkflowSideCard>
          {qaActionStatus ? (
            <WorkflowSideCard title="任务提示" tone={/失败|error|not found|找不到|缺失/i.test(qaActionStatus) ? 'warn' : 'neutral'}>
              <div className="workflow-status-note">{busy ? <span className="loading" /> : null}{qaActionStatus}</div>
            </WorkflowSideCard>
          ) : null}
        </>
      }
    >
      <div className="qa-workspace workflow-block">
        <section className="qa-step-card">
          <div className="section-head">
            <div>
              <strong>1. 校对语言</strong>
              <span>可多选；当前执行 {currentLanguageText}</span>
            </div>
            <span className="tag">已选 {selectedLanguages.length || 1} 个</span>
          </div>
          <div className="lang-grid compact-lang-grid qa-language-grid">
            {supportedLanguages.map((lang) => {
              const isSelected = selectedLanguages.includes(lang.code)
              const isCurrent = selectedLanguage === lang.code
              return (
                <button
                  key={lang.code}
                  type="button"
                  className={`lang-chip ${isSelected ? 'selected' : ''} ${isCurrent ? 'current' : ''}`}
                  onClick={() => toggleSelectedLanguage(lang.code)}
                  onDoubleClick={() => setSelectedLanguage(lang.code)}
                  title={isCurrent ? '当前 QA 语言' : '点击勾选并设为当前语言'}
                >
                  <span className="lang-check">{isSelected ? '✓' : ''}</span>
                  {lang.label}
                  {isCurrent ? <small>当前</small> : null}
                </button>
              )
            })}
          </div>
          {selectedLanguages.length > 1 ? <div className="info-line compact">已选 {selectedLanguageText}；点击一次后工作台会按语言逐个 QA，已通过语言自动跳过。</div> : null}
        </section>

        <section className="qa-step-card">
          <div className="section-head">
            <div>
              <strong>2. 校对文件</strong>
              <span>优先接上一步翻译结果，也可选择已有译文表或上传新译文表格。</span>
            </div>
          </div>
          <div className="qa-entry-row">
            <button className="btn btn-ghost" disabled={!previousTranslationArtifact || busy} onClick={() => setQaArtifact(previousTranslationArtifact)}>使用上一翻译结果</button>
            <button className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={() => sourceArtifact && setQaArtifact(sourceArtifact)}>使用当前语言表</button>
          </div>
          <AssetSelect label="选择已译表 / 翻译结果" project={project} role={['translation_workbook', 'language_source']} value={effectiveQaArtifact} onChange={setQaArtifact} allowEmpty />
          <div className="qa-input-run-grid">
            <FileBox label="上传新的译文表格" onFile={onUploadTranslation} />
            <div className="qa-run-box">
              <div>
                <strong>3. 运行校对</strong>
                <span>{effectiveQaArtifact ? `将运行 ${currentLanguageText} QA` : '先选择或上传译文文件'}</span>
              </div>
              <button className="btn btn-primary" data-testid="run-qa" disabled={!effectiveQaArtifact || busy} onClick={() => {
                if (!qaArtifact && previousTranslationArtifact) setQaArtifact(previousTranslationArtifact)
                onDirectQA(effectiveQaArtifact)
              }}>运行 {currentLanguageText} QA</button>
              {(busy || status !== '准备就绪') ? <ActionStatus status={status} busy={busy} /> : null}
            </div>
          </div>
          {!effectiveQaArtifact ? <div className="warn-line">请选择“上一翻译结果”、此前导入的已译语言表，或上传新的译文表格后再运行 QA。</div> : null}
        </section>
        {allowSkipQAArchive ? <details className="manual-maintenance">
          <summary>临时跳过 QA 直接归档</summary>
          <div className="language-inline-select">
            <span>{skipArchiveHint}</span>
            <button className="btn btn-ghost" disabled={!canArchiveWithoutQA || busy} onClick={handleSkipArchive}>确认跳过 QA 并归档</button>
          </div>
        </details> : null}
      </div>
      {showHistory ? (
        <details className="history-collapsed">
          <summary>查看历史校对记录</summary>
          <TaskHistoryTable project={project} kind="qa" title="校对历史记录" />
        </details>
      ) : null}
      {qaIssues.length ? <FailedRowEditor issues={qaIssues} busy={busy} onModelFix={onModelFixes} onApply={onManualFixes} /> : null}
    </WorkflowStepShell>
  )
}

export function FailedRowEditor({
  issues,
  busy,
  onModelFix,
  onApply
}: {
  issues: QualityIssue[]
  busy: boolean
  onModelFix: () => void
  onApply: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
}) {
  const editable = issues.filter((issue) => issue.sheet && issue.row > 1)
  const visibleIssues = editable.slice(0, 50)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const issue of editable) next[issue.id] = drafts[issue.id] ?? issue.current_translation
    setDrafts(next)
  }, [issues.map((issue) => issue.id).join('|')])

  const fixes = editable
    .map((issue) => ({
      issue_id: issue.id,
      sheet: issue.sheet,
      row: issue.row,
      translation: (drafts[issue.id] ?? '').trim(),
      note: `${issue.source}:${issue.check_type}`
    }))
    .filter((fix) => fix.translation)

  if (!editable.length) {
    return <IssueSummary issues={issues} />
  }

  return (
    <div className="issue-summary">
      <div className="card-title"><div className="left">QA 问题摘要</div></div>
      <IssueGuide issues={issues} editableCount={editable.length} />
      <IssueChips issues={issues} />
      <div className="model-fix-bar">
        <div>
          <strong>推荐处理顺序</strong>
          <span>先用模型批量修复并重跑 QA；仍失败的行再人工逐条改。</span>
        </div>
        <button className="btn btn-primary btn-sm" disabled={busy || editable.length === 0} onClick={onModelFix}>🤖 模型修复并重跑 QA</button>
      </div>
      <details className="repair-panel" data-testid="failed-row-editor">
        <summary>展开可编辑问题（显示前 {visibleIssues.length} / {editable.length} 条）</summary>
        <div className="failed-editor">
          <div className="card-title">
            <div className="left">逐行修复</div>
            <button className="btn btn-primary btn-sm" data-testid="manual-fix-rerun" disabled={busy || fixes.length === 0} onClick={() => onApply(fixes)}>保存修复并重新 QA</button>
          </div>
          <div className="failed-rows">
            {visibleIssues.map((issue, index) => (
              <div key={`${issue.id}-${issue.sheet}-${issue.row}-${issue.check_type}-${issue.source}-${index}`} className="failed-row">
                <div className="failed-meta">
                  <span>{severityLabel(issue.severity)}</span>
                  <span>{issueTypeLabel(issue.check_type)}</span>
                  <span>{issue.sheet} 第 {issue.row} 行</span>
                  <span>{issueSourceLabel(issue.source)}</span>
                </div>
                <div className="failed-message">{issueHumanMessage(issue)}</div>
                <div className="failed-field">
                  <span>当前译文</span>
                  <div className="failed-current">{issue.current_translation || '-'}</div>
                </div>
                <label className="failed-edit">
                  <span>修改为</span>
                  <textarea
                    data-testid={`manual-fix-input-${issue.row}`}
                    value={drafts[issue.id] ?? issue.current_translation}
                    onChange={(event) => setDrafts((prev) => ({ ...prev, [issue.id]: event.target.value }))}
                  />
                </label>
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  )
}
