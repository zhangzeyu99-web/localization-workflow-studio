import { useEffect, useState } from 'react'
import { CheckCircle2, PackageCheck, ShieldAlert, Wrench } from 'lucide-react'
import { artifactDownloadHref, artifactKindLabel, artifactLanguageLabel, artifactRole, newestArtifact, pickerArtifacts, runArtifacts } from '../../../domain/artifacts'
import { canSkipModelTranslation, latestRunOfKind } from '../../../domain/translationFlow'
import { qaOutcomePresentation } from '../../../domain/workflowPresentation'
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
  severityLabel
} from '../QaIssuePanel'
import { TaskHistoryTable } from '../TaskHistoryTable'
import { WorkflowStepShell } from '../WorkflowStepShell'

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
  onCancelQa,
  onSkipQAArchive,
  allowSkipQAArchive = false,
  onManualFixes,
  onModelFixes,
  onUploadTranslation,
  busy,
  status,
  selectedLanguage,
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
  onCancelQa?: (run?: Run | null) => void
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
  const qaArtifactLabel = effectiveQaArtifact
    ? `${artifactKindLabel(effectiveQaArtifact)}${artifactLanguageLabel(effectiveQaArtifact) ? `（${artifactLanguageLabel(effectiveQaArtifact)}）` : ''}`
    : '未选择'
  const translationQaRun = previousTranslationRun && previousTranslationArtifact ? previousTranslationRun : null
  const qaStatusRun = latestQaRun && (!translationQaRun || latestQaRun.created_at >= translationQaRun.created_at) ? latestQaRun : translationQaRun
  const qaStatusArtifacts = qaStatusRun ? pickerArtifacts(qaStatusRun.artifacts?.length ? qaStatusRun.artifacts : runArtifacts(project, qaStatusRun.id)) : []
  const qaFinalDownload = newestArtifact(qaStatusArtifacts, ['qa_final_workbook'])
  const qaChangesDownload = newestArtifact(qaStatusArtifacts, ['qa_changes'])
  const qaRole = effectiveQaArtifact ? artifactRole(effectiveQaArtifact) : ''
  const selectedReadiness = effectiveQaArtifact && translationReadiness?.artifact_id === effectiveQaArtifact.id ? translationReadiness : null
  const canArchiveWithoutQA = Boolean(effectiveQaArtifact && (qaRole !== 'language_source' || canSkipModelTranslation(selectedReadiness)))
  const qaSourceLabel = effectiveQaArtifact?.run_id && previousTranslationRun?.id === effectiveQaArtifact.run_id
    ? '上一翻译结果'
    : qaRole === 'language_source'
      ? '已译语言表'
      : qaArtifact
        ? '上传译文'
        : '未选择'
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
  const pendingIssueCount = qaPendingIssueCount(qaStatusRun, qaIssues)
  const qaOutcome = qaOutcomePresentation(qaStatusRun, pendingIssueCount, Boolean(qaFinalDownload))
  const selectedLanguageText = selectedLanguages.map((code) => languageSpec(code).short).join(' / ')
  const currentLanguageText = languageSpec(selectedLanguage).short
  // QA runs as a background job now: "running" comes from the run itself, not
  // from the short-lived interactive busy flag.
  const qaActive = Boolean(qaStatusRun && qaStatusRun.kind === 'qa' && ['queued', 'running'].includes(qaStatusRun.status))
  const qaCancelRequested = Boolean(qaActive && qaStatusRun?.metadata?.cancel_requested_at)
  const qaTone = busy || qaActive ? 'running' : qaOutcome.tone
  const scrollToManualFixes = () => {
    document.querySelector('[data-testid="failed-row-editor"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  return (
    <WorkflowStepShell
      stepLabel="步骤 8/9"
      title="QA 校对"
      description="检查译文并处理问题。"
      status={qaOutcome.label}
      statusTone={qaTone}
      nextAction={qaOutcome.nextAction}
      showStatus={false}
    >
      <div className={`qa-outcome-panel ${qaOutcome.tone}`} data-testid="qa-outcome-panel">
        <div className="qa-current-head">
          <span className="qa-outcome-icon">
            {qaOutcome.tone === 'ready' ? <CheckCircle2 size={19} aria-hidden="true" /> : qaOutcome.tone === 'warn' || qaOutcome.tone === 'blocked' ? <ShieldAlert size={19} aria-hidden="true" /> : <PackageCheck size={19} aria-hidden="true" />}
          </span>
          <div className="qa-outcome-copy">
            <strong>{qaOutcome.label}</strong>
            <span>{qaOutcome.summary}</span>
          </div>
        </div>
        <div className="qa-current-grid compact">
          <div><span>文件</span><strong>{qaArtifactLabel}</strong></div>
          <div><span>来源</span><strong>{qaSourceLabel}</strong></div>
          <div><span>问题</span><strong>{qaStatusRun ? `${pendingIssueCount} 个待处理` : '尚未检查'}</strong></div>
        </div>
        <div className="qa-result-actions">
          {qaStatusRun?.status === 'failed' ? <button className="btn btn-primary btn-sm" disabled={busy || !qaIssues.length} onClick={onModelFixes}><Wrench size={14} aria-hidden="true" />修复并重跑</button> : null}
          {qaStatusRun?.status === 'failed' ? <button className="btn btn-ghost btn-sm" disabled={!qaIssues.length} onClick={scrollToManualFixes}>手动修复</button> : null}
          {qaFinalDownload ? <a className="btn btn-ghost btn-sm" data-testid="qa-download-final" href={artifactDownloadHref(qaFinalDownload, project.id)}>下载译文</a> : null}
          {qaChangesDownload ? <a className="btn btn-ghost btn-sm" data-testid="qa-download-changes" href={artifactDownloadHref(qaChangesDownload, project.id)}>修改记录</a> : null}
          {onGoDelivery && qaStatusRun && ['passed', 'failed'].includes(qaStatusRun.status) ? (
            <button className={`btn btn-sm ${qaStatusRun.status === 'failed' ? 'qa-risk-action' : 'btn-primary'}`} data-testid="qa-go-delivery" onClick={onGoDelivery}>
              <PackageCheck size={14} aria-hidden="true" />{qaStatusRun.status === 'failed' ? '带问题交付' : '标准交付'}
            </button>
          ) : null}
        </div>
      </div>
      <details className="qa-input-details" open={!qaStatusRun}>
        <summary>校对输入</summary>
        <div className="qa-workspace workflow-block">
        <section className="qa-step-card">
          <div className="section-head">
            <div>
              <strong>语言</strong>
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
                  title={isCurrent ? '当前语言' : '选择语言'}
                >
                  <span className="lang-check">{isSelected ? '✓' : ''}</span>
                  {lang.label}
                  {isCurrent ? <small>当前</small> : null}
                </button>
              )
            })}
          </div>
          {selectedLanguages.length > 1 ? <div className="info-line compact">依次校对：{selectedLanguageText}</div> : null}
        </section>

        <section className="qa-step-card">
          <div className="section-head">
            <div>
              <strong>译文文件</strong>
            </div>
          </div>
          <div className="qa-entry-row">
            <button className="btn btn-ghost" disabled={!previousTranslationArtifact || busy} onClick={() => setQaArtifact(previousTranslationArtifact)}>上一翻译结果</button>
            <button className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={() => sourceArtifact && setQaArtifact(sourceArtifact)}>当前语言表</button>
          </div>
          <AssetSelect label="选择译文" project={project} role={['translation_workbook', 'language_source']} value={effectiveQaArtifact} onChange={setQaArtifact} allowEmpty />
          <div className="qa-input-run-grid">
            <FileBox label="上传译文" onFile={onUploadTranslation} />
            <div className="qa-run-box">
              <div>
                <strong>运行 QA</strong>
                <span>{effectiveQaArtifact ? currentLanguageText : '需先选择译文'}</span>
              </div>
              <button className="btn btn-primary" data-testid="run-qa" disabled={!effectiveQaArtifact || busy || qaActive} onClick={() => {
                if (!qaArtifact && previousTranslationArtifact) setQaArtifact(previousTranslationArtifact)
                onDirectQA(effectiveQaArtifact)
              }}>运行 {currentLanguageText} QA</button>
              {qaActive && onCancelQa ? (
                <button className="btn btn-ghost" data-testid="cancel-qa" disabled={busy || qaCancelRequested} onClick={() => onCancelQa(qaStatusRun)}>
                  {qaCancelRequested ? '正在取消…' : '取消 QA'}
                </button>
              ) : null}
              {(busy || qaActive || status !== '准备就绪') ? <ActionStatus status={status} busy={busy || qaActive} /> : null}
            </div>
          </div>
          {!effectiveQaArtifact ? <div className="warn-line">请选择译文文件。</div> : null}
        </section>
        {allowSkipQAArchive ? <details className="manual-maintenance">
          <summary>临时跳过 QA 直接归档</summary>
          <div className="language-inline-select">
            <span>{skipArchiveHint}</span>
            <button className="btn btn-ghost" disabled={!canArchiveWithoutQA || busy} onClick={handleSkipArchive}>确认跳过 QA 并归档</button>
          </div>
        </details> : null}
        </div>
      </details>
      {showHistory ? (
        <details className="history-collapsed">
          <summary>查看历史校对记录</summary>
          <TaskHistoryTable project={project} kind="qa" title="校对历史记录" />
        </details>
      ) : null}
      {qaIssues.length ? <FailedRowEditor issues={qaIssues} busy={busy} onApply={onManualFixes} /> : null}
    </WorkflowStepShell>
  )
}

export function FailedRowEditor({
  issues,
  busy,
  onApply
}: {
  issues: QualityIssue[]
  busy: boolean
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
