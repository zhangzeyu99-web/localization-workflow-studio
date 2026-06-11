import React, { useEffect, useState } from 'react'
import { announcementLanguages, languageChipTitle, languageSpec, normalizeLanguageArray, normalizeLanguageCode, supportedLanguages, type LanguageCode } from '../../languages'
import { artifactDownloadHref, artifactFileName, artifactLanguageLabel, artifactPickerLabel, isAnnouncementSourceDocument, isGeneratedAnnouncementTermsArtifact, pickerArtifacts } from '../../domain/artifacts'
import { aiProviderConfigurationReminder, isAiProviderReady, providerLabel } from '../../domain/providerSettings'
import { ActionStatus, ArtifactNote, FileBox, FileBoxWithTemplate, TranslationProgressBar } from '../shared/WorkflowPrimitives'
import { AiInputAuditPanel } from '../shared/AiInputAudit'
import type { AnnouncementLookupOptions, AnnouncementLookupResult, AnnouncementTask, AnnouncementTaskResult, AnnouncementTermRow, AppSettings, Artifact, Project, TranslationProgress } from '../../types'

export const announcementSteps = ['公告资料', '约束来源', '目标语言', '术语提取', '译文反查', '翻译准备', 'AI翻译', '校对回填', '交付']

export function activeAnnouncementTasks(tasks: AnnouncementTask[]): AnnouncementTask[] {
  return tasks.filter((task) => task.status !== 'canceled')
}

export function unfinishedAnnouncementTasks(tasks: AnnouncementTask[]): AnnouncementTask[] {
  return activeAnnouncementTasks(tasks).filter((task) => task.status !== 'delivered')
}

export function hasAnnouncementPreparedAiInput(task: AnnouncementTask | null): boolean {
  const ids = task?.metadata?.workpack_artifact_ids
  return Boolean(ids && typeof ids === 'object' && !Array.isArray(ids) && Object.keys(ids as Record<string, unknown>).length)
}

export function AnnouncementProjectPanel({
  tasks,
  holdTaskId,
  onStartAnnouncement,
  onStartTask,
  onBeginCancelHold,
  onCancelHold
}: {
  tasks: AnnouncementTask[]
  holdTaskId: string
  onStartAnnouncement: () => void
  onStartTask: (task: AnnouncementTask) => void
  onBeginCancelHold: (task: AnnouncementTask) => void
  onCancelHold: () => void
}) {
  const activeTasks = activeAnnouncementTasks(tasks)
  const latest = activeTasks[0]
  return (
    <div className="card tight announcement-project-panel">
      <div className="card-title">
        <div className="left">📣 公告任务 / 外文本</div>
        <button className="btn btn-ghost btn-sm" onClick={onStartAnnouncement}>进入公告工作流</button>
      </div>
      {!activeTasks.length ? (
        <div className="panel-desc">暂无公告任务。公告翻译归属于当前项目，用项目术语、QA归档和项目提示词约束游戏外文本。</div>
      ) : (
        <div className="announcement-task-list">
          {activeTasks.slice(0, 4).map((task) => {
            const isDelivered = task.status === 'delivered'
            return (
              <div
                key={task.id}
                className={`announcement-task-row ${holdTaskId === task.id ? 'cancel-hold' : ''}`}
                onPointerDown={(event) => { if (event.button === 0 && announcementTaskCanCancel(task)) onBeginCancelHold(task) }}
                onPointerUp={onCancelHold}
                onPointerLeave={onCancelHold}
                onPointerCancel={onCancelHold}
              >
                <div>
                  <strong>{task.title || task.id}</strong>
                  <span>{task.source_format?.toUpperCase() || '-'} · STEP {task.current_step || 1}/9 · {announcementStatusLabel(task.status)}</span>
                  <span>{announcementLanguageSummary(task)}</span>
                </div>
                <button className="btn btn-ghost btn-sm" onPointerDown={(event) => event.stopPropagation()} onClick={() => onStartTask(task)}>{isDelivered ? '查看交付' : '继续'}</button>
              </div>
            )
          })}
          {latest ? <div className="panel-desc">最近任务：{latest.title || latest.id}</div> : null}
        </div>
      )}
    </div>
  )
}

export function announcementStatusLabel(status?: string): string {
  const labels: Record<string, string> = {
    created: '已创建',
    constraints_ready: '约束已识别',
    languages_ready: '目标语言已确认',
    terms_ready: '术语已提取',
    lookup_ready: '译文已反查',
    prepared: '翻译准备完成',
    queued: '后台排队',
    running: '后台翻译中',
    needs_input: '需要确认/继续',
    translated: '译文已导入',
    applied: '已回填',
    delivered: '已交付',
    canceled: '已取消',
    failed: '失败',
  }
  return labels[status || ''] || status || '未开始'
}

export function announcementLanguageSummary(task: AnnouncementTask): string {
  const languages = normalizeLanguageArray(task.selected_languages || [])
  return languages.length ? `目标语言：${languages.map((lang) => languageSpec(lang).short).join(' / ')}` : '目标语言：待识别'
}

export function getAnnouncementTranslationProgress(task: AnnouncementTask | null): TranslationProgress | null {
  const progress = task?.metadata?.translation_progress as TranslationProgress | undefined
  return progress?.total_rows ? progress : null
}

export function isAnnouncementTranslationResumable(task: AnnouncementTask | null): boolean {
  if (!task) return false
  const progress = getAnnouncementTranslationProgress(task)
  const reason = String(task.metadata?.reason || '')
  if (['needs_input', 'canceled'].includes(task.status)) return true
  if (task.status === 'failed') return true
  if (task.status === 'prepared' && ['announcement_translation_canceled', 'background_job_interrupted', 'api_budget_confirmation_required'].includes(reason)) return true
  if (progress && progress.completed_rows < progress.total_rows) return true
  if (progress?.failed_batch) return true
  return false
}

function toNumber(value: unknown): number {
  const parsed = Number(value || 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function announcementHardBlockerCount(task: AnnouncementTask | null): number {
  if (!task) return 0
  const metadata = task.metadata || {}
  const counts = [toNumber(metadata.hard_blockers)]
  const qaIssues = metadata.qa_issues
  if (Array.isArray(qaIssues)) {
    counts.push(qaIssues.filter((issue) => String((issue as Record<string, unknown>)?.severity || 'hard').toLowerCase() === 'hard').length)
  }
  for (const language of task.languages || []) {
    counts.push(toNumber(language.metadata?.hard_blockers))
  }
  for (const artifact of task.artifacts || []) {
    if (['announcement_qa_summary', 'announcement_docx_qa_summary'].includes(artifact.kind)) {
      counts.push(toNumber(artifact.metadata?.hard_blockers))
    }
  }
  return Math.max(...counts)
}

export function announcementTranslateEndpoint(task: AnnouncementTask | null): 'translate/start' | 'translate/resume' {
  return isAnnouncementTranslationResumable(task) ? 'translate/resume' : 'translate/start'
}

export function AnnouncementWizard({
  project,
  busy,
  status,
  settings,
  assetArtifacts,
  onUploadAsset,
  onUploadConstraint,
  onUploadTermsFile,
  onUploadResponse,
  onCreateTask,
  onTaskAction,
  onBeginAnnouncementCancelHold,
  onCancelAnnouncementHold,
  announcementCancelHoldTaskId,
  initialTaskId,
  onBack
}: {
  project: Project
  busy: boolean
  status: string
  settings: AppSettings | null
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  assetArtifacts: Artifact[]
  announcementText: string
  setAnnouncementText: (value: string) => void
  lookupResult: AnnouncementLookupResult | null
  onUploadAsset: (file: File) => Promise<Artifact | null>
  onUploadConstraint: (file: File) => Promise<Artifact | null>
  onUploadTermsFile: (file: File) => Promise<Artifact | null>
  onUploadResponse: (file: File) => Promise<Artifact | null>
  onCreateTask: (payload: Record<string, unknown>) => Promise<AnnouncementTask | null>
  onTaskAction: (taskId: string, endpoint: string, payload?: Record<string, unknown>) => Promise<AnnouncementTaskResult | null>
  onLookup: (text: string, materialArtifactIds: string[], options: AnnouncementLookupOptions) => void
  onBeginAnnouncementCancelHold: (task: AnnouncementTask) => void
  onCancelAnnouncementHold: () => void
  announcementCancelHoldTaskId: string
  initialTaskId: string
  onBack: () => void
}) {
  const allTasks = activeAnnouncementTasks(project.announcement_tasks || [])
  const tasks = initialTaskId ? allTasks : unfinishedAnnouncementTasks(allTasks)
  const [step, setStep] = useState(1)
  const [taskId, setTaskId] = useState(initialTaskId || tasks[0]?.id || '')
  const activeTask = allTasks.find((task) => task.id === taskId) || null
  const [sourceArtifactId, setSourceArtifactId] = useState(activeTask?.source_artifact_id || '')
  const [constraintArtifactIds, setConstraintArtifactIds] = useState<string[]>(announcementTaskConstraintIds(activeTask))
  const [selectedLanguages, setSelectedLanguages] = useState<LanguageCode[]>(activeTask?.selected_languages?.length ? activeTask.selected_languages : [])
  const [responseArtifactIds, setResponseArtifactIds] = useState<string[]>([])
  const [aiSupplement, setAiSupplement] = useState(() => {
    const aiMeta = (activeTask?.metadata || {}).ai_supplement as Record<string, unknown> | undefined
    return aiMeta?.enabled !== false
  })
  const [aiSupplementResponseArtifactId, setAiSupplementResponseArtifactId] = useState('')
  const artifacts = project.artifacts || []
  const sourceCandidates = pickerArtifacts([...assetArtifacts, ...artifacts.filter((artifact) => artifact.kind === 'asset')].filter(isAnnouncementSourceDocument))
  const hiddenAnnouncementTermsArtifacts = artifacts.filter(isGeneratedAnnouncementTermsArtifact)
  const constraintCandidates = pickerArtifacts(artifacts.filter((artifact) => artifact.kind === 'language_table' && !isGeneratedAnnouncementTermsArtifact(artifact)))
  const selectableConstraintIds = new Set(constraintCandidates.map((artifact) => artifact.id))
  const activeConstraintArtifactIds = constraintArtifactIds.filter((id) => selectableConstraintIds.has(id))
  const activeMeta = (activeTask?.metadata || {}) as Record<string, unknown>
  const detectedLanguages = normalizeLanguageArray(activeMeta.detected_languages)
  const effectiveLanguages = selectedLanguages
  const providerConfigurationReminder = aiProviderConfigurationReminder(settings)
  const providerReady = isAiProviderReady(settings)
  const showLanguageSubflows = Boolean(activeTask && step >= 6 && step <= 8)

  useEffect(() => {
    if (initialTaskId && allTasks.some((task) => task.id === initialTaskId)) {
      setTaskId(initialTaskId)
      return
    }
    if (taskId && !allTasks.some((task) => task.id === taskId)) {
      setTaskId(tasks[0]?.id || '')
      return
    }
    if (!taskId && tasks[0]) setTaskId(tasks[0].id)
  }, [initialTaskId, allTasks.length, tasks.length, taskId, activeTask?.status])

  useEffect(() => {
    if (!activeTask) return
    setStep(activeTask.current_step || 1)
    setSourceArtifactId(activeTask.source_artifact_id || '')
    setConstraintArtifactIds(announcementTaskConstraintIds(activeTask))
    setSelectedLanguages(activeTask.selected_languages?.length ? activeTask.selected_languages : normalizeLanguageArray((activeTask.metadata || {}).detected_languages))
    const aiMeta = (activeTask.metadata || {}).ai_supplement as Record<string, unknown> | undefined
    setAiSupplement(aiMeta?.enabled !== false)
    setAiSupplementResponseArtifactId(String(aiMeta?.response_artifact_id || ''))
  }, [activeTask?.id, activeTask?.updated_at])

  useEffect(() => {
    if (activeTask || taskId) return
    setStep(1)
    setSourceArtifactId('')
    setConstraintArtifactIds([])
    setSelectedLanguages([])
    setResponseArtifactIds([])
    setAiSupplementResponseArtifactId('')
  }, [activeTask?.id, taskId])

  function toggleConstraint(id: string) {
    setConstraintArtifactIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id])
  }

  function toggleLanguage(code: LanguageCode) {
    setSelectedLanguages((prev) => prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code])
  }

  async function createTaskFromCurrent() {
    const task = await onCreateTask({
      source_artifact_id: sourceArtifactId,
      language_table_artifact_ids: activeConstraintArtifactIds,
      constraint_artifact_ids: activeConstraintArtifactIds,
      languages: selectedLanguages,
      include_project_archive: true,
      output_policy: 'same_format'
    })
    if (task) {
      setTaskId(task.id)
      setStep(2)
    }
  }

  async function run(endpoint: string, nextStep?: number, extra: Record<string, unknown> = {}) {
    if (!activeTask) return
    const result = await onTaskAction(activeTask.id, endpoint, {
      language_table_artifact_ids: activeConstraintArtifactIds,
      constraint_artifact_ids: activeConstraintArtifactIds,
      languages: effectiveLanguages,
      include_project_archive: true,
      response_artifact_ids: responseArtifactIds,
      ai_supplement: aiSupplement,
      ai_supplement_response_artifact_id: aiSupplementResponseArtifactId || undefined,
      ...extra
    })
    if (result?.task) setTaskId(result.task.id)
    if (result && nextStep) setStep(Math.max(nextStep, Number(result.task?.current_step || 0)))
  }

  async function importExtractedTermsFile(file: File) {
    if (!activeTask) return
    const artifact = await onUploadTermsFile(file)
    if (!artifact) return
    await run('import-terms', 4, { terms_artifact_id: artifact.id })
  }

  async function saveEditedTerms(terms: AnnouncementTermRow[], languages: LanguageCode[]) {
    await run('import-terms', 4, { terms, languages })
  }

  return (
    <div className="wizard announcement-wizard">
      <div className="proj-head">
        <div>
          <h2>📣 公告翻译 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">单文档多语言外文本工作流：先提取公告术语，再按 QA 归档优先反查译文，最后走 AI 翻译、QA 回填和交付。不会使用谷歌机翻。</div>
        </div>
        <button className="btn btn-ghost" onClick={onBack}>← 返回项目概览</button>
      </div>

      <div className="steps-nav announcement-steps">
        {announcementSteps.map((title, index) => (
          <button key={title} className={`step-item ${index + 1 === step ? 'active' : activeTask && (activeTask.current_step || 1) > index + 1 ? 'done' : ''}`} onClick={() => setStep(index + 1)}>
            <span className="num">{index + 1}</span>{title}
          </button>
        ))}
      </div>
      {busy || (status && status !== '准备就绪') ? <ActionStatus status={status} busy={busy} /> : null}
      {activeTask ? (
        <div
          className={`announcement-current-task ${announcementCancelHoldTaskId === activeTask.id ? 'cancel-hold' : ''}`}
          onPointerDown={(event) => { if (event.button === 0 && announcementTaskCanCancel(activeTask)) onBeginAnnouncementCancelHold(activeTask) }}
          onPointerUp={onCancelAnnouncementHold}
          onPointerLeave={onCancelAnnouncementHold}
          onPointerCancel={onCancelAnnouncementHold}
        >
          <span>当前公告任务：{activeTask.title || activeTask.id}</span>
          <em>STEP {activeTask.current_step || 1}/9 · {announcementStatusLabel(activeTask.status)}{announcementTaskCanCancel(activeTask) ? ' · 长按取消' : ''}</em>
        </div>
      ) : null}

      <div className="announcement-shell">
        <section className="wizard-panel announcement-panel">
          {showLanguageSubflows ? (
            <AnnouncementLanguageSubflows
              task={activeTask}
              effectiveLanguages={effectiveLanguages}
              detectedLanguages={detectedLanguages}
              onToggleLanguage={toggleLanguage}
            />
          ) : null}
          {!activeTask && step > 1 ? (
            <AnnouncementTaskRequiredState step={step} title={announcementSteps[step - 1]} onBackToStart={() => setStep(1)} />
          ) : step === 1 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 1</span>公告资料</div>
              <div className="panel-desc">上传一个待翻译公告文档。v1 支持 DOCX / TXT / XLSX；默认交付同格式，同时保留 Excel 中转表和 QA 摘要。</div>
              <div className="upload-row">
                <FileBox label="上传公告源文档（DOCX / TXT / XLSX）" onFile={async (file) => { const artifact = await onUploadAsset(file); if (artifact) setSourceArtifactId(artifact.id) }} />
                <div className="asset-list">
                  <div className="ai-header">选择公告源文档</div>
                  {!sourceCandidates.length ? <div className="warn-line">暂无源文档，请先上传。</div> : null}
                  {sourceCandidates.map((artifact) => (
                    <label key={artifact.id} className="check-row">
                      <input type="radio" name="announcement-source" checked={sourceArtifactId === artifact.id} onChange={() => setSourceArtifactId(artifact.id)} />
                      <span>{artifactPickerLabel(artifact)}<em>{artifactFileName(artifact)}</em></span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="row-actions">
                <button className="btn btn-primary" disabled={busy || !sourceArtifactId} onClick={createTaskFromCurrent}>{activeTask ? '用当前选择新建任务' : '创建公告任务'}</button>
                {activeTask ? <button className="btn btn-ghost" onClick={() => setStep(2)}>继续当前任务</button> : null}
              </div>
            </>
          ) : step === 2 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 2</span>约束来源</div>
              <div className="panel-desc">本步只选择二次翻译的约束来源：项目 QA 归档默认参与；如有完整语言表，再上传或勾选它用于反查生成公告术语表。</div>
              <div className="constraint-source-grid">
                <div className="constraint-source-panel is-primary">
                  <div className="constraint-source-title">项目 QA 归档</div>
                  <p>默认使用当前项目里已经 QA 通过的译文和项目术语。冲突时优先级高于上传语言表。</p>
                  <span className="tag tag-done">自动参与</span>
                </div>
                <div className="constraint-source-panel">
                  <div className="constraint-source-title">完整语言表 / 术语交付表</div>
                  <p>可选。用于从公告原文反查已有翻译，生成本任务公告术语表；已生成的公告术语表请到 STEP 4 导入。</p>
                  <FileBoxWithTemplate label="上传完整语言表（XLSX）" onFile={async (file) => { const artifact = await onUploadConstraint(file); if (artifact) setConstraintArtifactIds((prev) => [...new Set([artifact.id, ...prev])]) }} templateKind="announcement-language-table" />
                </div>
              </div>
              <div className="asset-list compact-list">
                <div className="ai-header">可选语言表</div>
                {!constraintCandidates.length ? <div className="muted-left">当前没有可选完整语言表；可以只用项目 QA 归档继续。</div> : null}
                {hiddenAnnouncementTermsArtifacts.length ? <div className="muted-left">已隐藏 {hiddenAnnouncementTermsArtifacts.length} 个已生成公告术语表；如需复用，请到 STEP 4 导入。</div> : null}
                {constraintCandidates.map((artifact) => (
                  <label key={artifact.id} className="check-row">
                    <input type="checkbox" checked={constraintArtifactIds.includes(artifact.id)} onChange={() => toggleConstraint(artifact.id)} />
                    <span>{artifactPickerLabel(artifact)}<em>{artifactFileName(artifact)}</em></span>
                  </label>
                ))}
              </div>
              <div className="workflow-note-grid">
                <div><strong>约束优先级</strong><span>项目 QA 归档 &gt; 完整语言表</span></div>
                <div><strong>已选语言表</strong><span>{activeConstraintArtifactIds.length} 个</span></div>
                <div><strong>当前任务</strong><span>{activeTask ? activeTask.title || activeTask.id : '-'}</span></div>
              </div>
              <div className="row-actions"><button className="btn btn-primary" disabled={!activeTask || busy} onClick={() => run('inspect-constraints', 3)}>识别语言与约束</button></div>
            </>
          ) : step === 3 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 3</span>目标语言</div>
              <div className="panel-desc">系统从约束文件和项目归档识别目标语言；识别到的语言默认勾选，也可以手动勾选或取消。</div>
              <div className="announcement-language-chip-grid">
                {announcementLanguages.map((lang) => {
                  const selected = effectiveLanguages.includes(lang.code)
                  const detected = detectedLanguages.includes(lang.code)
                  return (
                    <label key={lang.code} className={`announcement-language-chip ${selected ? 'selected' : ''} ${detected ? 'detected' : 'manual'}`}>
                      <input type="checkbox" checked={selected} onChange={() => toggleLanguage(lang.code)} />
                      <span><strong>{languageChipTitle(lang)}</strong><em>{detected ? '已识别' : '手动'} · {selected ? '已选' : '未选'}</em></span>
                    </label>
                  )
                })}
              </div>
              <div className="row-actions"><button className="btn btn-primary" disabled={!activeTask || busy || !effectiveLanguages.length} onClick={() => run('inspect-constraints', 4, { confirm_languages: true })}>确认目标语言</button></div>
            </>
          ) : step === 4 ? (
            <AnnouncementTermsStep
              activeTask={activeTask}
              busy={busy}
              effectiveLanguages={effectiveLanguages}
              onExtract={(enabled, responseArtifactId) => run('extract-terms', 4, { ai_supplement: enabled, ai_supplement_response_artifact_id: responseArtifactId || undefined })}
              onImportFile={importExtractedTermsFile}
              onUploadAiSupplementResponse={async (file) => { const artifact = await onUploadResponse(file); if (artifact) setAiSupplementResponseArtifactId(artifact.id) }}
              onSaveTerms={saveEditedTerms}
              aiSupplement={aiSupplement}
              setAiSupplement={setAiSupplement}
              aiSupplementResponseArtifactId={aiSupplementResponseArtifactId}
            />
          ) : step === 5 ? (
            <AnnouncementActionStep title="译文反查" step={5} desc="按目标语言从项目 QA 归档和语言表反查译文，QA 归档优先；缺失术语会标记但不阻断翻译准备。" activeTask={activeTask} busy={busy} actionLabel="反查术语译文" onAction={() => run('lookup-translations', 6)} />
          ) : step === 6 ? (
            <>
              <AnnouncementActionStep title="翻译准备" step={6} desc="按语言生成中转表、manifest、prompt snapshot 和 workpack。后续可直接调用 AI provider 或下载 workpack 外部翻译。" activeTask={activeTask} busy={busy} actionLabel="生成翻译准备包" onAction={() => run('prepare', 7)} />
              <div className="muted-empty-card gap-top">译文反查完成后，点击“生成翻译准备包”会生成中转表、prompt 和 workpack。这些是给 AI 和 QA 用的过程材料，正常用户不需要手动查看。</div>
            </>
          ) : step === 7 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 7</span>AI 翻译</div>
              <div className="panel-desc">点击“AI翻译”后会在后台调用已配置的 AI 翻译公告正文，进度会显示在下方。不会使用谷歌机翻或在线机翻聚合器。</div>
              {getAnnouncementTranslationProgress(activeTask) ? <TranslationProgressBar progress={getAnnouncementTranslationProgress(activeTask)!} /> : null}
              {providerConfigurationReminder ? <div className="warn-line">需要先配置 API：{providerConfigurationReminder}</div> : null}
              {activeTask?.metadata?.reason === 'background_job_interrupted' ? <div className="warn-line">后台翻译曾中断；再点“AI翻译”会从已完成批次继续，不会全部重跑。</div> : null}
              {activeTask?.metadata?.reason === 'api_budget_confirmation_required' ? <div className="warn-line">预计 API token 超过提醒阈值；确认后可继续后台翻译。</div> : null}
              <div className="workflow-note-grid compact-grid">
                <div><strong>AI</strong><span>{providerReady ? `${providerLabel(settings)} 已配置` : '未配置 API key'}</span></div>
                <div><strong>目标语言</strong><span>{effectiveLanguages.map((lang) => languageSpec(lang).short).join(' / ') || '-'}</span></div>
              </div>
              <div className="row-actions">
                <button
                  className="btn btn-primary"
                  disabled={!activeTask || busy || !providerReady}
                  onClick={() => {
                    const needsBudgetConfirm = activeTask?.metadata?.reason === 'api_budget_confirmation_required'
                    const confirmed = needsBudgetConfirm ? window.confirm('该公告翻译预计 API token 用量超过提醒阈值。确认后会从已完成批次继续。是否继续？') : false
                    if (needsBudgetConfirm && !confirmed) return
                    run(announcementTranslateEndpoint(activeTask), undefined, { confirm_api_budget: confirmed })
                  }}
                >AI翻译</button>
                {['queued', 'running'].includes(activeTask?.status || '') ? (
                  <button className="btn btn-ghost" disabled={!activeTask || busy} onClick={() => run('translate/cancel', 7)}>暂停</button>
                ) : null}
              </div>
              {!hasAnnouncementPreparedAiInput(activeTask) && activeTask ? (
                <div className="muted-empty-card gap-top">还没有翻译准备包。请先回 STEP 6 点击“生成翻译准备包”。</div>
              ) : null}
              <details className="delivery-advanced">
                <summary>过程文件与审计（可选）</summary>
                <div className="panel-desc">这些是中转表、workpack、prompt 和 AI 输入审计，正常翻译不需要操作。</div>
                {hasAnnouncementPreparedAiInput(activeTask) ? (
                  <AiInputAuditPanel endpoint={`/api/announcement-tasks/${activeTask!.id}/ai-input-summary`} title="公告正文翻译 AI 输入" buttonLabel="查看 AI 输入" />
                ) : null}
                <ArtifactLinks artifacts={activeTask?.artifacts || []} kinds={["announcement_workpack", "prompt_snapshot", "announcement_translation_workbook"]} />
                <details className="delivery-advanced">
                  <summary>外部 AI response 导入（备用）</summary>
                  <div className="panel-desc">只有在没有可用 API、或要把 workpack 发给外部 AI/供应商处理时才需要。已配置 API 时不用导入。</div>
                  <div className="upload-row">
                    <FileBox label="上传 ai_response_<lang>.jsonl" onFile={async (file) => { const artifact = await onUploadResponse(file); if (artifact) setResponseArtifactIds((prev) => [...new Set([artifact.id, ...prev])]) }} />
                    <div className="workflow-note-grid compact-grid">
                      <div><strong>已上传 response</strong><span>{responseArtifactIds.length} 个</span></div>
                    </div>
                  </div>
                  <div className="row-actions">
                    <button className="btn btn-ghost" disabled={!activeTask || busy || !responseArtifactIds.length} onClick={() => run('import-ai', 8)}>导入 AI response</button>
                  </div>
                </details>
              </details>
            </>
          ) : step === 8 ? (
            <AnnouncementActionStep
              title="校对回填"
              step={8}
              desc="按语言校验 ID、顺序、变量、标签、术语、中文残留和格式指纹；系统会先自动修复，未清零的问题会写入 QA 摘要，不再阻塞交付包生成。"
              activeTask={activeTask}
              busy={busy}
              actionLabel="QA 并回填同格式文件"
              onAction={() => run('apply', 9)}
              fixActionLabel="自动修复 Hard blocker"
              onFixAction={() => run('fix-hard-blockers', 8)}
            />
          ) : (
            <AnnouncementDeliveryStep
              activeTask={activeTask}
              busy={busy}
              onDeliver={(force = false) => run('deliver', 9, { date_stamp: new Date().toISOString().slice(0, 10).replace(/-/g, ''), force })}
            />
          )}

          {activeTask && step === 9 ? <AnnouncementTaskArtifacts task={activeTask} /> : null}
        </section>
      </div>
    </div>
  )
}

export function AnnouncementTaskRequiredState({ step, title, onBackToStart }: { step: number; title: string; onBackToStart: () => void }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP {step}</span>{title}</div>
      <div className="empty-action-card" data-testid="announcement-task-required">
        <div>
          <strong>先创建公告任务</strong>
          <span>公告翻译按单个源文档推进。请先在 STEP 1 上传公告源文档并创建任务，后续步骤才会保存约束、语言、术语和交付产物。</span>
        </div>
        <button className="btn btn-primary btn-sm" onClick={onBackToStart}>回到公告资料</button>
      </div>
    </>
  )
}


export function AnnouncementTermsStep({
  activeTask,
  busy,
  effectiveLanguages,
  onExtract,
  onImportFile,
  onUploadAiSupplementResponse,
  onSaveTerms,
  aiSupplement,
  setAiSupplement,
  aiSupplementResponseArtifactId
}: {
  activeTask: AnnouncementTask | null
  busy: boolean
  effectiveLanguages: LanguageCode[]
  onExtract: (aiSupplement: boolean, aiSupplementResponseArtifactId: string) => void
  onImportFile: (file: File) => void
  onUploadAiSupplementResponse: (file: File) => void
  onSaveTerms: (terms: AnnouncementTermRow[], languages: LanguageCode[]) => void
  aiSupplement: boolean
  setAiSupplement: (value: boolean) => void
  aiSupplementResponseArtifactId: string
}) {
  const [draftTerms, setDraftTerms] = useState<AnnouncementTermRow[]>([])
  const languages = announcementTermLanguages(activeTask, effectiveLanguages)
  const meta = activeTask?.metadata || {}
  const exportArtifact = activeTask?.artifacts?.find((artifact) => artifact.id === meta.terms_artifact_id)
    || activeTask?.artifacts?.find((artifact) => artifact.kind === 'announcement_terms_workbook')
  const aiPacketArtifact = activeTask?.artifacts?.find((artifact) => artifact.kind === 'announcement_ai_supplement_packet')
  const aiReportArtifact = activeTask?.artifacts?.find((artifact) => artifact.kind === 'announcement_ai_supplement_report')
  const aiMeta = (meta.ai_supplement && typeof meta.ai_supplement === 'object' ? meta.ai_supplement : {}) as Record<string, unknown>
  const languageText = languages.map((lang) => languageSpec(lang).short).join(' / ') || '-'
  const extracted = activeTask?.status === 'terms_ready' || Number(activeTask?.current_step || 0) >= 5 || Boolean(meta.terms_summary)
  const hasTerms = draftTerms.length > 0
  const termsResultText = hasTerms ? `${draftTerms.length} 条` : extracted ? '未命中，可手动补充' : '未提取'
  const aiStatus = aiSupplement
    ? aiMeta.provider_status === 'provider_response'
      ? 'API 已复查'
      : aiMeta.provider_status === 'provider_error'
        ? 'API 失败，已保留本地结果'
        : aiPacketArtifact
          ? '已生成检查包'
          : '默认开启'
    : '已关闭'

  useEffect(() => {
    setDraftTerms(announcementTermsFromTask(activeTask))
  }, [activeTask?.id, activeTask?.updated_at])

  function updateTerm(index: number, patch: Partial<AnnouncementTermRow>) {
    setDraftTerms((prev) => prev.map((term, termIndex) => termIndex === index ? { ...term, ...patch } : term))
  }

  function updateTranslation(index: number, language: LanguageCode, value: string) {
    setDraftTerms((prev) => prev.map((term, termIndex) => {
      if (termIndex !== index) return term
      return { ...term, translations: { ...(term.translations || {}), [language]: value } }
    }))
  }

  function addTerm() {
    setDraftTerms((prev) => [...prev, { id: '', source: '', translations: {} }])
  }

  function removeTerm(index: number) {
    setDraftTerms((prev) => prev.filter((_, termIndex) => termIndex !== index))
  }

  if (!activeTask) {
    return (
      <>
        <div className="panel-title"><span className="badge">STEP 4</span>术语提取</div>
        <div className="panel-desc">从公告原文中提取本次需要的术语，生成任务内临时术语表；可导出、上传已有提取结果模拟、编辑后保存，不自动写回项目术语库。</div>
        <div className="warn-line">请先在 STEP 1 创建公告任务。</div>
      </>
    )
  }

  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>术语提取</div>
      <div className="panel-desc">本步只做一件事：从公告原文生成任务内临时术语表。检查表格后保存，下一步再反查译文；不会写回项目术语库。</div>
      <div className="announcement-terms-guide">
        <div>
          <strong>生成临时公告术语表</strong>
          <span>先从公告原文提取术语；如果没有命中，也可以手动新增或导入已有结果。</span>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={() => onExtract(aiSupplement, aiSupplementResponseArtifactId)}>{aiSupplement ? '提取术语并 AI 复查' : '仅本地提取术语'}</button>
      </div>
      <div className="announcement-terms-summary">
        <div><strong>源格式</strong><span>{activeTask.source_format?.toUpperCase() || '-'}</span></div>
        <div><strong>目标语言</strong><span>{languageText}</span></div>
        <div><strong>提取结果</strong><span>{termsResultText}</span></div>
        <div><strong>AI 复查</strong><span>{aiStatus}</span></div>
      </div>
      {!hasTerms && extracted ? (
        <div className="announcement-terms-empty">
          <div>
            <strong>没有命中可确认术语</strong>
            <span>这不是失败。可以手动新增术语、导入已提取术语表，或直接进入 STEP 5 做译文反查。</span>
          </div>
          <div className="row-actions wrap">
            <button className="btn btn-primary" disabled={busy} onClick={addTerm}>+ 新增术语</button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => onExtract(aiSupplement, aiSupplementResponseArtifactId)}>重新提取</button>
          </div>
        </div>
      ) : null}
      <div className="announcement-terms-editor-head">
        <div>
          <strong>临时术语表</strong>
          <span>{hasTerms ? '可直接编辑下方表格；保存后会重新生成导出表，不会写入项目术语库。' : '暂无术语行；可新增、导入，或直接继续下一步。'}</span>
        </div>
        <div className="row-actions wrap">
          <button className="btn btn-primary" disabled={busy || !draftTerms.length} onClick={() => onSaveTerms(draftTerms, languages)}>保存编辑</button>
          <button className="btn btn-ghost" disabled={busy} onClick={addTerm}>+ 新增术语</button>
          {exportArtifact ? <a className="btn btn-ghost" href={artifactDownloadHref(exportArtifact)}>导出 XLSX</a> : null}
        </div>
      </div>
      <details className="asset-list gap-top optional-panel" open={!draftTerms.length || Boolean(aiPacketArtifact || aiReportArtifact)}>
        <summary>更多操作：导入已有术语 / AI 复查设置 / 审计产物</summary>
        <div className="announcement-more-grid">
          <div>
            <FileBoxWithTemplate label="上传已提取术语表（XLSX）" onFile={onImportFile} templateKind="announcement-terms" />
          </div>
          <div className="asset-list compact-asset-list">
            <label className="check-row">
              <input type="checkbox" checked={aiSupplement} onChange={(event) => setAiSupplement(event.target.checked)} />
              <span>默认启用 AI 漏词复查<em>API 已配置时自动复查；没配置时只生成检查包，不阻断本地提取。</em></span>
            </label>
            <div className="row-actions wrap gap-top">
              {aiPacketArtifact ? <a className="btn btn-ghost btn-sm" href={artifactDownloadHref(aiPacketArtifact)}>下载检查包</a> : null}
              {aiReportArtifact ? <a className="btn btn-ghost btn-sm" href={artifactDownloadHref(aiReportArtifact)}>下载 AI 报告</a> : null}
            </div>
            <div className="gap-top">
              <FileBox label="上传外部 AI 结果 JSON（可选）" onFile={onUploadAiSupplementResponse} />
            </div>
          </div>
        </div>
      </details>
      {!draftTerms.length ? (
        <div className="muted-empty-card gap-top">暂无术语表行。可点击“新增术语”补充，或在“更多操作”里上传 announcement_terms.xlsx。</div>
      ) : (
        <div className="announcement-terms-table-wrap gap-top">
          <table className="announcement-terms-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>CN</th>
                {languages.map((language) => <th key={language}>{languageSpec(language).targetHeader}</th>)}
                <th>命中</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {draftTerms.map((term, index) => (
                <tr key={`${index}-${term.id || ''}`}>
                  <td><input value={term.id || ''} onChange={(event) => updateTerm(index, { id: event.target.value })} /></td>
                  <td><input value={term.source || ''} onChange={(event) => updateTerm(index, { source: event.target.value })} /></td>
                  {languages.map((language) => (
                    <td key={language}><input value={(term.translations || {})[language] || ''} onChange={(event) => updateTranslation(index, language, event.target.value)} /></td>
                  ))}
                  <td>{term.hit_count ?? '-'}</td>
                  <td><button className="btn btn-ghost btn-sm" onClick={() => removeTerm(index)}>删除</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export function announcementTermsFromTask(task: AnnouncementTask | null): AnnouncementTermRow[] {
  const terms = task?.metadata?.terms
  if (!Array.isArray(terms)) return []
  return terms.map((item, index) => {
    const row = item as Record<string, unknown>
    const translations = (row.translations && typeof row.translations === 'object' ? row.translations : {}) as Record<string, unknown>
    const normalizedTranslations: Record<string, string> = {}
    for (const [key, value] of Object.entries(translations)) {
      const language = normalizeLanguageCode(key)
      if (language) normalizedTranslations[language] = String(value || '')
    }
    return {
      id: String(row.id || row.term_key || index + 1),
      source: String(row.source || row.cn || ''),
      translations: normalizedTranslations,
      hit_count: typeof row.hit_count === 'number' ? row.hit_count : undefined,
      first_position: typeof row.first_position === 'number' ? row.first_position : undefined
    }
  })
}

export function announcementTermLanguages(task: AnnouncementTask | null, effectiveLanguages: LanguageCode[]): LanguageCode[] {
  const found = new Set<LanguageCode>()
  effectiveLanguages.forEach((language) => found.add(language))
  normalizeLanguageArray(task?.selected_languages || []).forEach((language) => found.add(language))
  normalizeLanguageArray((task?.metadata || {}).languages).forEach((language) => found.add(language))
  for (const term of announcementTermsFromTask(task)) {
    Object.keys(term.translations || {}).forEach((language) => {
      const code = normalizeLanguageCode(language)
      if (code) found.add(code)
    })
  }
  return supportedLanguages.map((language) => language.code).filter((code) => found.has(code))
}

export function announcementTaskCanCancel(task: AnnouncementTask): boolean {
  return !['delivered', 'canceled'].includes(task.status || '')
}

export function AnnouncementDeliveryStep({ activeTask, busy, onDeliver }: { activeTask: AnnouncementTask | null; busy: boolean; onDeliver: (force?: boolean) => void }) {
  const deliveryArtifacts = (activeTask?.artifacts || []).filter((artifact) => ['announcement_delivery_package', 'announcement_docx_delivery_package'].includes(artifact.kind))
  const delivered = Boolean(activeTask?.status === 'delivered' && deliveryArtifacts.length)
  const hardBlockers = announcementHardBlockerCount(activeTask)
  const qaSummaryArtifacts = pickerArtifacts((activeTask?.artifacts || []).filter((artifact) => ['announcement_qa_summary', 'announcement_docx_qa_summary'].includes(artifact.kind)))
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 9</span>交付</div>
      <div className="panel-desc">生成公告交付总包：只包含按语言分目录的成品和 QA 摘要；中转表、manifest、workpack 留在过程产物区。</div>
      {!activeTask ? <div className="warn-line">请先在 STEP 1 创建公告任务。</div> : null}
      <AnnouncementTaskSnapshot task={activeTask} />
      {hardBlockers > 0 && !delivered ? (
        <div className="warn-line">
          当前还有 {hardBlockers} 个 Hard blocker。系统会把问题写入 QA 摘要；如需继续验收，可以直接生成带 QA 摘要的交付包。
        </div>
      ) : null}
      {qaSummaryArtifacts.length && hardBlockers > 0 ? (
        <div className="row-actions">
          {qaSummaryArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact)}>下载 QA 摘要</a>)}
        </div>
      ) : null}
      {delivered ? <div className="ok-line">已生成公告交付包，可在下方下载；不会重复生成新交付。</div> : null}
      <div className="row-actions">
        {!delivered && hardBlockers <= 0 ? <button className="btn btn-primary" disabled={!activeTask || busy} onClick={() => onDeliver(false)}>生成交付总包</button> : null}
        {!delivered && hardBlockers > 0 ? (
          <button
            className="btn btn-primary"
            disabled={!activeTask || busy}
            onClick={() => {
              if (window.confirm(`当前还有 ${hardBlockers} 个 Hard blocker。确认生成带 QA 摘要的交付包？`)) onDeliver(true)
            }}
          >
            生成带 QA 摘要的交付包
          </button>
        ) : null}
      </div>
      {delivered ? (
        <details className="delivery-advanced">
          <summary>更多</summary>
          <button
            className="btn btn-ghost btn-sm"
            disabled={busy}
            onClick={() => {
              if (window.confirm('已存在公告交付包。确认重新生成会新增一版交付记录。是否继续？')) onDeliver(true)
            }}
          >
            重新生成交付总包
          </button>
        </details>
      ) : null}
    </>
  )
}

export function AnnouncementActionStep({
  title,
  step,
  desc,
  activeTask,
  busy,
  actionLabel,
  onAction,
  fixActionLabel,
  onFixAction,
}: {
  title: string
  step: number
  desc: string
  activeTask: AnnouncementTask | null
  busy: boolean
  actionLabel: string
  onAction: () => void
  fixActionLabel?: string
  onFixAction?: () => void
}) {
  const hardBlockers = announcementHardBlockerCount(activeTask)
  const qaSummaryArtifacts = pickerArtifacts((activeTask?.artifacts || []).filter((artifact) => ['announcement_qa_summary', 'announcement_docx_qa_summary'].includes(artifact.kind)))
  return (
    <>
      <div className="panel-title"><span className="badge">STEP {step}</span>{title}</div>
      <div className="panel-desc">{desc}</div>
      {!activeTask ? <div className="warn-line">请先在 STEP 1 创建公告任务。</div> : null}
      <AnnouncementTaskSnapshot task={activeTask} />
      {step === 8 && hardBlockers > 0 ? (
        <div className="warn-line">检测到 {hardBlockers} 个 Hard blocker。系统已保留回填文件，可以下载 QA 摘要查看问题；也可以继续到 STEP 9 生成带 QA 摘要的交付包。</div>
      ) : null}
      {step === 8 && qaSummaryArtifacts.length ? (
        <div className="row-actions">
          {qaSummaryArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact)}>下载 QA 摘要</a>)}
        </div>
      ) : null}
      <div className="row-actions">
        <button className="btn btn-primary" disabled={!activeTask || busy} onClick={onAction}>{actionLabel}</button>
        {hardBlockers > 0 && onFixAction ? <button className="btn btn-ghost" disabled={!activeTask || busy} onClick={onFixAction}>{fixActionLabel || '自动修复 Hard blocker'}</button> : null}
      </div>
    </>
  )
}

export function AnnouncementLanguageSubflows({
  task,
  effectiveLanguages,
  detectedLanguages,
  onToggleLanguage
}: {
  task: AnnouncementTask | null
  effectiveLanguages: LanguageCode[]
  detectedLanguages: LanguageCode[]
  onToggleLanguage: (code: LanguageCode) => void
}) {
  if (!task) return null
  return (
    <div className="announcement-subflow-strip">
      <div className="ai-header">语言子流程</div>
      <div className="announcement-subflow-row">
        {announcementLanguages.map((lang) => {
          const child = task.languages?.find((item) => item.language === lang.code)
          const selected = effectiveLanguages.includes(lang.code)
          if (!selected && !child) return null
          return (
            <button key={lang.code} className={`announcement-subflow-card ${selected ? 'selected' : ''} ${child ? child.status : 'is-empty'}`} onClick={() => onToggleLanguage(lang.code)}>
              <strong>{lang.label}</strong>
              <span>{child ? `STEP ${child.current_step}/9` : selected ? '已选择' : '未选择'}</span>
              <em>{child?.status || (detectedLanguages.includes(lang.code) ? '检测到约束' : '待选择')}</em>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function AnnouncementTaskSnapshot({ task }: { task: AnnouncementTask | null }) {
  if (!task) return null
  const meta = task.metadata || {}
  const hardBlockers = announcementHardBlockerCount(task)
  return (
    <div className="workflow-note-grid">
      <div><strong>任务状态</strong><span>{task.status} · STEP {task.current_step}/9</span></div>
      <div><strong>源格式</strong><span>{task.source_format?.toUpperCase() || '-'}</span></div>
      <div><strong>目标语言</strong><span>{(task.selected_languages || []).map((lang) => languageSpec(lang).short).join(' / ') || '-'}</span></div>
      <div><strong>术语数</strong><span>{String((meta.terms_summary as Record<string, unknown> | undefined)?.terms ?? '-')}</span></div>
      <div><strong>缺失术语</strong><span>{String((meta.lookup_summary as Record<string, unknown> | undefined)?.missing_terms ?? '-')}</span></div>
      <div><strong>Hard blocker</strong><span>{hardBlockers ? String(hardBlockers) : String(meta.hard_blockers ?? '-')}</span></div>
    </div>
  )
}

export function AnnouncementTaskArtifacts({ task }: { task: AnnouncementTask }) {
  const artifacts = task.artifacts || []
  if (!artifacts.length) return null
  const finalKinds = new Set(['announcement_delivery_package', 'announcement_docx_delivery_package'])
  const qaKinds = new Set(['announcement_output_file', 'announcement_docx_output_docx', 'announcement_qa_summary', 'announcement_docx_qa_summary'])
  const finalArtifacts = pickerArtifacts(artifacts.filter((artifact) => finalKinds.has(artifact.kind)))
  const qaArtifacts = pickerArtifacts(artifacts.filter((artifact) => qaKinds.has(artifact.kind)))
  const processArtifacts = pickerArtifacts(artifacts.filter((artifact) => !finalKinds.has(artifact.kind) && !qaKinds.has(artifact.kind)))
  const hasDelivery = finalArtifacts.length > 0
  const languages = normalizeLanguageArray(task.selected_languages || []).map((lang) => languageSpec(lang).short).join(' / ') || '-'
  return (
    <div className="card tight announcement-artifacts">
      <div className="card-title"><div className="left">公告交付</div></div>
      <div className="delivery-card compact-delivery">
        <div className="delivery-head">
          <div>
            <strong>{task.title || '公告任务'}</strong>
            <span>{languages}</span>
          </div>
          <span className={`tag ${task.status === 'delivered' ? 'tag-done' : 'tag-doing'}`}>{task.status === 'delivered' ? '可交付' : announcementStatusLabel(task.status)}</span>
        </div>
        <div className="delivery-brief">
          <div><span>任务进度</span><strong>STEP {task.current_step || 1}/9 · {announcementStatusLabel(task.status)}</strong></div>
          <div><span>交付结果</span><strong>{hasDelivery ? '已生成公告交付包' : '待生成'}</strong></div>
        </div>
        <div className="delivery-actions">
          {finalArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-primary btn-sm" href={artifactDownloadHref(artifact)}>下载公告交付包</a>)}
          {qaArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact)}>{announcementDownloadLabel(artifact)}</a>)}
        </div>
      </div>
      {processArtifacts.length ? (
        <details className="asset-list delivery-advanced">
          <summary className="ai-header">高级：过程文件（{processArtifacts.length}）</summary>
          <div className="row-actions wrap">
            {processArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact)}>{artifactPickerLabel(artifact)}</a>)}
          </div>
        </details>
      ) : null}
    </div>
  )
}

export function announcementArtifactTypeLabel(artifact: Artifact): string {
  if (artifact.kind.includes('delivery_package')) return '公告交付 ZIP'
  if (artifact.kind.includes('qa_summary')) return 'QA 摘要'
  if (artifact.kind.includes('output')) return '公告成品'
  if (artifact.kind.includes('workpack')) return '过程文件'
  if (artifact.kind.includes('manifest')) return '过程文件'
  if (artifact.kind.includes('prompt')) return '过程文件'
  if (artifact.kind.includes('ai_supplement_packet')) return 'AI 补充包'
  if (artifact.kind.includes('ai_supplement_response')) return 'AI 补充响应'
  if (artifact.kind.includes('ai_supplement_report')) return 'AI 补充报告'
  if (artifact.kind.includes('translation_workbook')) return '中转表'
  if (artifact.kind.includes('terms')) return '公告术语表'
  return '过程文件'
}

export function announcementDownloadLabel(artifact: Artifact): string {
  if (artifact.kind.includes('qa_summary')) return '下载 QA 摘要'
  if (artifact.kind.includes('output')) {
    const language = artifactLanguageLabel(artifact)
    return `下载${language ? ` ${language} ` : ' '}成品`
  }
  return `下载${announcementArtifactTypeLabel(artifact)}`
}

export function ArtifactLinks({ artifacts, kinds }: { artifacts: Artifact[]; kinds: string[] }) {
  const filtered = artifacts.filter((artifact) => kinds.includes(artifact.kind))
  return (
    <div className="asset-list">
      <div className="ai-header">准备产物下载（可选）</div>
      <div className="panel-desc">正常走 API 翻译时不用下载；需要人工检查、外部协作或复盘审计时再下载。</div>
      {!filtered.length ? <div className="warn-line">准备产物尚未生成，请先完成 STEP 6。</div> : null}
      {filtered.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
    </div>
  )
}

export function announcementTaskConstraintIds(task: AnnouncementTask | null): string[] {
  const meta = task?.metadata || {}
  const values = [...((meta.language_table_artifact_ids as string[] | undefined) || []), ...((meta.constraint_artifact_ids as string[] | undefined) || [])]
  return [...new Set(values.filter(Boolean))]
}
