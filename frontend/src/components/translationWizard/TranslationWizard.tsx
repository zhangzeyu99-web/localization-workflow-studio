import React, { useEffect, useState } from 'react'
import { API } from '../../apiClient'
import { artifactDownloadHref, artifactKindLabel, artifactPickerLabel, artifactRole, newestArtifact, pickerArtifacts, runArtifacts } from '../../domain/artifacts'
import { formatDate, formatDateTime, shortRunId } from '../../domain/format'
import { normalizeGlossaryNote, projectPromptForLanguage } from '../../domain/projectAssets'
import { aiProviderConfigurationReminder, providerLabel } from '../../domain/providerSettings'
import { canSkipModelTranslation, effectiveBatchSize, estimateBatches, findVisibleTranslationRun, getTranslationProgress, isTranslationRunResumable, latestRunOfKind, matchesTranslationRun, translationInputMode, translationNextStep, translationReadinessUserMessage } from '../../domain/translationFlow'
import { languageQuery, languageSpec, supportedLanguages, unsupportedLanguages, normalizeLanguageCode, type LanguageCode } from '../../languages'
import { ProjectMetaTable } from '../project/ProjectMeta'
import { ActionStatus, ArtifactNote, AssetSelect, CheckItem, FileBox, FileBoxWithTemplate, GlossaryPreview, LanguageSelector, SelectedInput, TranslationProgressBar } from '../shared/WorkflowPrimitives'
import { AiInputAuditPanel } from '../shared/AiInputAudit'
import type { AppSettings, Artifact, DeliverableTask, DeliveryFile, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, HistoryKind, LargeTextRunState, Project, ProjectHarness, ProjectMaterialAnalysis, QualityIssue, Run, TranslationProgress, TranslationReadiness } from '../../types'

export const steps = ['项目资料', 'AI 分析', '术语表', '判定输入', '术语候选', '目标语言', 'AI 翻译', 'QA 校对', '交付']

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
          <div><strong>质量门槛</strong><span>必须修复问题为 0 才能交付</span></div>
        </div>
      </div>
      <TaskHistoryTable project={project} kind="translation" title="🕒 翻译历史记录" />
      {latestRun && latestRun.kind === 'translation' ? <TaskRunSummary run={latestRun} /> : null}
    </>
  )
}

export function DeliveryTab({
  project,
  deliverables,
  busy,
  status,
  onCreateDelivery,
  onGoTranslate,
  onGoQA,
  onGoArchive
}: {
  project: Project
  deliverables: DeliverableTask[]
  busy: boolean
  status: string
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
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
      {!deliverables.length ? (
        <div className="delivery-empty" data-testid="delivery-empty">
          <div>
            <strong>还没有可下载的交付文件</strong>
            <span>先完成翻译或校对并通过 QA；通过后这里会显示最终译文和修改记录。</span>
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
          const resultLabel = hasPackage ? '已生成公告交付包' : hasDelivery ? (hasChanges ? '已生成最终译文 + 修改记录' : '已生成最终译文') : '待生成'
          return (
            <div key={task.run_id} className="delivery-card delivery-line">
              <div className="delivery-head">
                <div>
                  <strong>{deliveryTaskTitle(task)}</strong>
                  <span>{deliveryTaskSubtitle(task)}</span>
                </div>
                <span className={`tag ${hasQaIssues ? 'tag-warn' : task.status === 'passed' ? 'tag-done' : 'tag-doing'}`}>{deliveryStatusLabel(task)}</span>
              </div>
              {hasQaIssues ? (
                <div className="warn-line" data-testid="delivery-problem-warning">
                  这份任务还有 QA 问题。建议先复查并修复；急需交付时，交付文件会附带问题摘要。
                </div>
              ) : null}
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
                {!hasDelivery ? <button className="btn btn-primary btn-sm" data-testid={`delivery-generate-${task.run_id}`} disabled={busy} onClick={() => onCreateDelivery(task.run_id)}>生成交付文件</button> : null}
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
  if (task.status === 'delivered') return '可交付'
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

export function providerName(settings: AppSettings | null): string {
  return providerLabel(settings)
}

export function formalTranslationBlockReason(settings: AppSettings | null, sourceArtifact: Artifact | null, project?: Project, readiness?: TranslationReadiness | null): string {
  if (!sourceArtifact) return '请先上传或选择待翻译语言表。'
  const readinessBlock = translationReadinessBlockReason(readiness)
  if (readinessBlock) return readinessBlock
  const configurationReminder = aiProviderConfigurationReminder(settings)
  if (configurationReminder) return configurationReminder
  return ''
}

export function translationReadinessBlockReason(readiness?: TranslationReadiness | null): string {
  if (!readiness) return ''
  if (translationInputMode(readiness) === 'invalid') return translationReadinessUserMessage(readiness)
  if (Number(readiness.invalid_id_rows || 0) > 0) {
    const samples = readiness.invalid_id_samples?.length ? ` 示例：${readiness.invalid_id_samples.join(', ')}` : ''
    return `语言表有 ${readiness.invalid_id_rows} 行缺少可回写 ID；请先补齐非空 ID。${samples}`
  }
  if (readiness.reason === 'no_source_rows') return '语言表未检测到原文行。'
  return ''
}

export function Wizard(props: {
  project: Project
  step: number
  setStep: (step: number) => void
  intro: string
  setIntro: (value: string) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  qaArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  sourceInputNotice?: TranslationReadiness | null
  invalidSourceArtifactIds?: string[]
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  qualityIssues: QualityIssue[]
  deliverables: DeliverableTask[]
  generatedDeliveryRunId?: string
  generatedDeliveryFiles?: DeliveryFile[]
  settings: AppSettings | null
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  onBack: () => void
  onUploadSource: (file: File) => void
  onUploadTerm: (file: File) => void
  onUploadAsset: (file: File) => void
  onAnalyze: () => void
  onGlossaryExtract: (artifact?: Artifact | null) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onTranslate: () => void
  onTranslateQueue?: () => void
  onCancelTranslate: () => void
  onDirectQA: (artifact?: Artifact | null) => void
  onDirectQAQueue?: () => void
  onSkipQAArchive: (artifact?: Artifact | null) => void
  allowSkipQAArchive?: boolean
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
  onCreateMergedDelivery?: () => void
  onFinishDelivery: () => void
  onFreq: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  busy: boolean
}) {
  const { project, step, setStep } = props
  const sourceReadiness = props.sourceArtifact && props.translationReadiness?.artifact_id === props.sourceArtifact.id ? props.translationReadiness : null
  const stepTranslationRun = props.latestRun && matchesTranslationRun(props.latestRun, props.selectedLanguage, props.sourceArtifact?.id, 'translation_run') ? props.latestRun : null
  const stepTranslationActive = step === 7 && Boolean(stepTranslationRun && ['queued', 'running'].includes(stepTranslationRun.status))
  const stepDeliveryFiles = step === 9
    ? wizardDeliveryFiles(project, props.latestRun, props.deliverables, props.generatedDeliveryRunId, props.generatedDeliveryFiles)
    : []
  const stepDeliveryReady = step !== 9 || stepDeliveryFiles.length > 0
  const goNext = () => {
    if (stepTranslationActive) return
    if (step === 4 && translationInputMode(props.sourceInputNotice) === 'invalid') {
      setStep(4)
      return
    }
    if (step === 4 && sourceReadiness) {
      setStep(Math.min(9, translationNextStep(sourceReadiness)))
      return
    }
    if ((step === 5 || step === 6 || step === 7) && translationInputMode(sourceReadiness) === 'ready_for_qa') {
      setStep(8)
      return
    }
    setStep(Math.min(9, step + 1))
  }
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>🚀 新翻译任务 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">完成 9 个步骤即可输出译文，过程中的术语、提示词和产物将回写到本项目。</div>
        </div>
        <button className="btn btn-ghost" onClick={props.onBack}>← 返回项目概览</button>
      </div>
      <div className="steps-nav">
        {steps.map((title, index) => (
          <button key={title} data-testid={`step-${index + 1}`} className={`step-item ${index + 1 === step ? 'active' : index + 1 < step ? 'done' : ''}`} onClick={() => setStep(index + 1)}>
            <span className="num">{index + 1}</span>{title}
          </button>
        ))}
      </div>
      {step !== 7 ? <ActionStatus status={props.status} busy={props.busy} /> : null}
      <div className="step-panel active">
        {step === 1 ? <StepIntro {...props} /> : null}
        {step === 2 ? <StepAnalyze {...props} /> : null}
        {step === 3 ? <StepTerm {...props} /> : null}
        {step === 4 ? <StepSource {...props} /> : null}
        {step === 5 ? <StepFreqV2 {...props} /> : null}
        {step === 6 ? <StepLang {...props} /> : null}
        {step === 7 ? <StepTranslate {...props} /> : null}
        {step === 8 ? <StepQA {...props} showHistory={false} onGoDelivery={() => props.setStep(9)} /> : null}
        {step === 9 ? <StepDone {...props} /> : null}
      </div>
      <div className="actions">
        <button className="btn btn-ghost" disabled={step === 1} onClick={() => setStep(step - 1)}>← 上一步</button>
        <button
          className="btn btn-primary"
          disabled={props.busy || stepTranslationActive || (step === 9 && !stepDeliveryReady)}
          onClick={step === 9 ? props.onFinishDelivery : goNext}
          title={step === 9 && !stepDeliveryReady ? '请先生成交付文件，下载入口出现后再完成。' : undefined}
        >
          {step === 9 ? '🏁 完成' : stepTranslationActive ? '等待翻译完成' : '下一步 →'}
        </button>
      </div>
    </>
  )
}

export function StepIntro({
  project,
  intro,
  setIntro,
  assetArtifacts,
  onUploadAsset
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  assetArtifacts: Artifact[]
  onUploadAsset: (file: File) => void
}) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 1</span>确认项目资料与参考素材</div>
      <div className="panel-desc">已从项目描述带入基础信息；这里只需要补充本次任务特有的风格、玩法、角色或素材。</div>
      <textarea value={intro} onChange={(event) => setIntro(event.target.value)} placeholder={'游戏名：《星际边境》\n类型：科幻 SLG\n目标用户：欧美移动端玩家\n玩法：基地建造 + 英雄养成 + 联盟战争'} />
      <div className="field-foot">
        <span>{intro.trim().length} 字</span>
        <span className={intro.trim().length > 20 || project.description ? 'ok' : 'warn'}>{intro.trim().length > 20 || project.description ? '✓ 信息可用于生成提示词' : '⚠ 建议补充更多信息'}</span>
      </div>
      <div className="upload-row">
        <FileBox label="上传 Markdown / 文档 / 图片 / PDF / 音视频素材" onFile={onUploadAsset} />
        {assetArtifacts.length ? (
          <div className="asset-list">
            <div className="ai-header">已归档参考素材</div>
            {assetArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
          </div>
        ) : null}
      </div>
    </>
  )
}

function projectMaterialAnalysis(project: Project): ProjectMaterialAnalysis | null {
  const packet = project.profile?.material_packet
  if (!packet || typeof packet !== 'object') return null
  const record = packet as Record<string, unknown>
  return {
    summary: record.summary as ProjectMaterialAnalysis['summary'],
    materials: record.materials as ProjectMaterialAnalysis['materials'],
    language_table_candidates: record.language_table_candidates as ProjectMaterialAnalysis['language_table_candidates'],
    warning: String(project.profile?.analysis_warning || '')
  }
}


function materialTypeLabel(value: unknown): string {
  const key = String(value || '').toLowerCase()
  const labels: Record<string, string> = {
    markdown: '\u9879\u76ee brief',
    text: '\u6587\u672c\u8d44\u6599',
    document: '\u6587\u6863\u8d44\u6599',
    spreadsheet: '\u8868\u683c\u8d44\u6599',
    image: '\u56fe\u7247\u8d44\u6599',
    video: '\u89c6\u9891\u8d44\u6599',
    json: 'JSON \u8d44\u6599',
  }
  return labels[key] || '\u8d44\u6599'
}

function materialStatusLabel(value: unknown): string {
  const key = String(value || '').toLowerCase()
  if (key.startsWith('vision_analyzed')) return '\u5df2\u505a\u753b\u9762\u5206\u6790'
  if (key.startsWith('parsed')) return '\u5df2\u8bfb\u53d6'
  if (key.startsWith('language_table')) return '\u5df2\u8bc6\u522b\u8bed\u8a00\u8868'
  if (key.startsWith('archived_only')) return '\u5df2\u5f52\u6863\uff0c\u672a\u8fdb\u5165 AI \u5206\u6790'
  if (key.includes('unsupported')) return '\u6682\u672a\u652f\u6301\u89e3\u6790'
  if (!key || key === '\u672a\u89e3\u6790') return '\u672a\u89e3\u6790'
  return '\u5df2\u5904\u7406'
}

function StepAnalyzeMaterialStatus({ project }: { project: Project }) {
  const analysis = projectMaterialAnalysis(project)
  if (!analysis) return null
  const summary = analysis.summary || {}
  const materials = analysis.materials || []
  const imageDone = materials.filter((item) => item.material_type === 'image' && item.status === 'vision_analyzed').length
  const imageTotal = materials.filter((item) => item.material_type === 'image').length
  const videoDone = materials.filter((item) => item.material_type === 'video' && String(item.status || '').startsWith('vision_analyzed')).length
  const videoTotal = materials.filter((item) => item.material_type === 'video').length
  const languageTables = analysis.language_table_candidates?.length || 0
  const unsupported = materials.filter((item) => String(item.status || '').startsWith('archived_only') || item.warning).length
  const warnings = materials.map((item) => item.warning).filter(Boolean).slice(0, 3)
  return (
    <>
      <div className="status-grid">
        <div className="metric-card">
          <div className="metric-label">资料读取</div>
          <strong>{summary.parsed ?? 0}/{summary.total ?? 0}</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">语言表识别</div>
          <strong>{languageTables} 个</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">图片视觉分析</div>
          <strong>{imageTotal ? `${imageDone}/${imageTotal}` : '-'}</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">视频画面分析</div>
          <strong>{videoTotal ? `${videoDone}/${videoTotal}` : '-'}</strong>
        </div>
        <div className="metric-card">
          <div className="metric-label">未完整分析</div>
          <strong>{unsupported || '-'}</strong>
        </div>
        {analysis.warning ? <div className="inline-warning span-all">{analysis.warning}</div> : null}
        {warnings.length ? <div className="muted-left span-all">{warnings.join('；')}</div> : null}
      </div>
      <div className="material-read-list">
        <div className="ai-header">资料读取明细</div>
        {materials.length ? materials.slice(0, 8).map((item, index) => {
          const status = String(item.status || '未解析')
          const entered = Boolean(item.excerpt) && (status.startsWith('parsed') || status.startsWith('vision_analyzed'))
          return (
            <div className="material-read-row" key={`${item.artifact_id || index}`}>
              <strong>{item.filename || item.label || `资料 ${index + 1}`}</strong>
              <span>{item.material_type || 'unknown'} · {status}</span>
              <em>{entered ? '已进入 AI' : '未进入 AI'}</em>
            </div>
          )
        }) : <div className="muted-left">暂无资料读取明细。请先上传资料并运行 AI 分析。</div>}
        {materials.length > 8 ? <div className="muted-left">还有 {materials.length - 8} 个资料，可在 AI 输入摘要里查看。</div> : null}
      </div>
    </>
  )
}

export function StepAnalyze({
  onAnalyze,
  project,
  busy,
  assetArtifacts,
  selectedLanguage
}: {
  onAnalyze: () => void
  project: Project
  busy: boolean
  assetArtifacts: Artifact[]
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  const hasPrompt = Boolean(projectPromptForLanguage(project, selectedLanguage))
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 2</span>AI 分析项目资料</div>
      <div className="panel-desc">读取 STEP 1 投入的资料，生成项目元信息和翻译提示词。已上传 {assetArtifacts.length} 个资料；重复资料会在资料包里去重。</div>
      <div className="step-brief-card">
        <div>
          <strong>{hasPrompt ? '已生成项目提示词' : '尚未生成项目提示词'}</strong>
          <span>后续 AI 翻译和 QA 会读取这里生成的项目信息；人工编辑后也会影响后续任务。</span>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>{hasPrompt ? '重新分析项目资料' : '启动 AI 分析'}</button>
      </div>
      <StepAnalyzeMaterialStatus project={project} />
      <details className="history-collapsed">
        <summary>查看本次 AI 输入摘要</summary>
        <AiInputAuditPanel endpoint={`/api/projects/${project.id}/ai-input-summary`} title="项目资料 AI 输入摘要" />
      </details>
      <div className="ai-card"><div className="ai-header">当前 {lang.short} 提示词</div><pre>{projectPromptForLanguage(project, selectedLanguage) || '尚未生成'}</pre></div>
      <ProjectMetaTable project={project} />
    </>
  )
}

export function StepTerm({
  project,
  onUploadTerm,
  termArtifact,
  setTermArtifact,
  glossaryPreview,
  onGlossaryPreview,
  onGlossaryImport,
  busy,
  selectedLanguage,
  status
}: {
  project: Project
  onUploadTerm: (file: File) => void
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  busy: boolean
  selectedLanguage: LanguageCode
  status: string
}) {
  const lang = languageSpec(selectedLanguage)
  const templateError = /术语表格式有误|导入模板|重新上传/.test(status)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 3</span>导入已确认术语表</div>
      <div className="panel-desc">这里只导入人工维护过的术语模板。完整语言表不要放这里，请到 STEP 4 上传并判定，待翻译表会在 STEP 5 扫描候选。</div>
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} />
        <FileBoxWithTemplate
          label="上传已确认术语表 xlsx/csv/json"
          onFile={onUploadTerm}
          templateKind="glossary"
          highlightTemplate={templateError}
          templateNote={templateError ? '格式有误，请重新上传。先下载模板，按列填写后再上传。' : '先下载模板，按列填写后再上传。'}
        />
        {templateError ? <div className="warn-line">术语表格式有误，请重新上传；建议先下载右侧模板后按列填写。</div> : null}
        <div className="row-actions">
          <button className="btn btn-ghost" disabled={!termArtifact || busy} onClick={onGlossaryPreview}>预览术语</button>
          <button className="btn btn-primary" disabled={!termArtifact || busy} onClick={onGlossaryImport}>导入到项目术语</button>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx&${languageQuery(selectedLanguage)}`}>导出 {lang.short} 术语</a>
        </div>
      </div>
      {termArtifact ? <ArtifactNote artifact={termArtifact} /> : null}
      {glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} selectedLanguage={selectedLanguage} /> : null}
    </>
  )
}

export function StepSource({
  project,
  onUploadSource,
  sourceArtifact,
  setSourceArtifact,
  selectedLanguage,
  translationReadiness,
  sourceInputNotice,
  invalidSourceArtifactIds = [],
  setQaArtifact,
  setStep
}: {
  project: Project
  onUploadSource: (file: File) => void
  sourceArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  selectedLanguage: LanguageCode
  translationReadiness?: TranslationReadiness | null
  sourceInputNotice?: TranslationReadiness | null
  invalidSourceArtifactIds?: string[]
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
}) {
  const displayProject = invalidSourceArtifactIds.length
    ? { ...project, artifacts: (project.artifacts || []).filter((artifact) => !invalidSourceArtifactIds.includes(artifact.id)) }
    : project
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id ? translationReadiness : null
  const notice = readiness || sourceInputNotice || null
  const mode = translationInputMode(notice)
  const tone = mode === 'ready_for_qa' ? 'ready' : mode === 'invalid' ? 'todo' : mode === 'needs_translation' ? 'checking' : 'idle'
  const modeLabel = mode === 'ready_for_qa'
    ? '已译校对表'
    : mode === 'needs_translation'
      ? '待翻译语言表'
      : mode === 'invalid'
        ? '格式需要修正'
        : '等待检查'
  const nextActionText = mode === 'ready_for_qa'
    ? '下一步：直接进入 STEP 8 校对；QA 通过后写入译文归档并生成交付。'
    : mode === 'needs_translation'
      ? '下一步：进入 STEP 5 扫描术语候选，再进入 AI 翻译。'
      : mode === 'invalid'
        ? '下一步：重新上传正确文件；这份错误文件已被忽略，不会继续参与流程。'
        : '上传或选择文件后，系统会判断它是待翻译表还是已译校对表。'
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>判断输入类型</div>
      <div className="panel-desc">这里不直接翻译。系统先判断你上传的是“待翻译语言表”还是“已译校对表”，再决定后面走术语候选、AI 翻译，还是直接 QA 校对。</div>
      <div className="action-card input-type-card">
        <div className="input-source-grid">
          <AssetSelect label="使用已有语言表 / 已译表" project={displayProject} role="language_source" value={sourceArtifact && invalidSourceArtifactIds.includes(sourceArtifact.id) ? null : sourceArtifact} onChange={setSourceArtifact} />
          <FileBoxWithTemplate label="上传待翻译表 / 已译校对表" onFile={onUploadSource} templateKind="language-table" />
        </div>
        {notice ? (
          <div className={`translation-readiness-box ${tone}`}>
            <div className="readiness-head">
              <strong>判定结果：{modeLabel}</strong>
              <span>{translationReadinessUserMessage(notice)}</span>
            </div>
            <p>{notice.source_rows || 0} 行原文 / {notice.translated_rows || 0} 行已有译文 / 空译文 {notice.empty_target_rows || 0} / 中文残留 {notice.cjk_target_rows || 0}</p>
            <div className="branch-next-line">{nextActionText}</div>
            {mode === 'ready_for_qa' && sourceArtifact ? (
              <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button>
            ) : null}
            {mode === 'invalid' ? <div className="warn-line">请按模板修正后重新上传。旧的错误文件不会继续显示在可选语言表里。</div> : null}
          </div>
        ) : (
          <div className="translation-readiness-box idle">
            <div className="readiness-head">
              <strong>等待上传</strong>
              <span>支持待翻译表，也支持已译表</span>
            </div>
            <p>待翻译表：目标语言列为空或含中文残留，后续会走 STEP 5-7。已译表：目标语言列已有完整译文，后续直接去 STEP 8 校对。</p>
          </div>
        )}
      </div>
      {sourceArtifact ? <ArtifactNote artifact={sourceArtifact} /> : null}
    </>
  )
}

export function StepFreqV2({
  onGlossaryExtract,
  onFreq,
  sourceArtifact,
  translationReadiness,
  assetArtifacts,
  latestRun,
  glossaryBatches,
  glossaryCandidates,
  busy,
  onUpdateCandidate,
  onResolveCandidates,
  onTranslateMissingCandidates,
  selectedLanguage,
  setQaArtifact,
  setStep
}: {
  project: Project
  onGlossaryExtract: (artifact?: Artifact | null) => void
  onFreq: () => void
  sourceArtifact: Artifact | null
  translationReadiness?: TranslationReadiness | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  selectedLanguage: LanguageCode
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
}) {
  const lang = languageSpec(selectedLanguage)
  const [expanded, setExpanded] = useState(false)
  const backfill = latestRun?.kind === 'glossary' ? latestRun.metadata?.glossary_backfill as Record<string, unknown> | undefined : undefined
  const activeBatch = glossaryBatches[0] || null
  const pendingCandidates = glossaryCandidates.filter((candidate) => candidate.status === 'pending')
  const needsTranslation = pendingCandidates.filter((candidate) => !candidate.target?.trim())
  const readyCandidates = pendingCandidates.filter((candidate) => candidate.target?.trim())
  const reviewPreview = expanded ? pendingCandidates : pendingCandidates.slice(0, 12)
  const candidates = Number(backfill?.candidates ?? 0)
  const uniqueCandidates = Number(backfill?.unique_candidates ?? candidates)
  const existing = Number(backfill?.skipped_existing ?? 0)
  const aiSupplement = (backfill?.ai_supplement && typeof backfill.ai_supplement === 'object' ? backfill.ai_supplement : {}) as Record<string, unknown>
  const aiSupplementStatus = String(aiSupplement.status || '')
  const aiSupplementReason = String(aiSupplement.reason || '')
  const aiSupplementText = aiSupplementStatus === 'passed'
    ? `补充 ${Number(aiSupplement.added ?? 0)} 条`
    : aiSupplementReason === 'api_key_missing'
      ? '未配置 API，已跳过'
      : aiSupplementReason === 'test_provider'
        ? '测试模式，已跳过'
        : aiSupplementStatus === 'provider_error'
          ? 'API 失败，保留本地结果'
          : aiSupplementReason
            ? `已跳过：${aiSupplementReason}`
            : '待自动检查'
  const accepted = activeBatch?.counts?.accepted ?? glossaryCandidates.filter((candidate) => candidate.status === 'accepted').length
  const rejected = activeBatch?.counts?.rejected ?? glossaryCandidates.filter((candidate) => candidate.status === 'rejected').length
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id ? translationReadiness : null
  const inputMode = translationInputMode(readiness)
  const blocked = !sourceArtifact || inputMode === 'ready_for_qa' || inputMode === 'invalid'
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 5</span>从待翻译语言表扫描高频术语候选</div>
      <div className="panel-desc">输入是 STEP 4 判定为“待翻译”的语言表；项目资料只辅助生成 brief 和提示词。扫描结果先进入候选，人工确认后才加入项目术语库。</div>
      {inputMode === 'ready_for_qa' ? (
        <div className="translation-readiness-box ready">
          <div className="readiness-head">
            <strong>这份表已有完整译文</strong>
            <span>不需要扫描术语候选；请直接进入校对，QA 通过后写入译文归档并生成交付。</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button>
        </div>
      ) : inputMode === 'invalid' || !sourceArtifact ? (
        <div className="translation-readiness-box todo">
          <div className="readiness-head">
            <strong>请先回 STEP 4 上传正确语言表</strong>
            <span>{translationReadinessUserMessage(readiness)}</span>
          </div>
        </div>
      ) : null}
      <div className="row-actions action-card">
        <span className="asset-meta">语言表：{sourceArtifact?.label || '未选择'}</span>
        <span className="asset-meta">参考素材：{assetArtifacts.length} 个</span>
        <button className="btn btn-primary" disabled={blocked || busy} onClick={() => onGlossaryExtract(sourceArtifact)}>🔎 扫描术语候选</button>
      </div>
      <details className="manual-maintenance compact-maintenance">
        <summary>高级：候选补译 / 扫描规则</summary>
        <div className="language-inline-select">
          <span>正常情况下只需要点击“扫描术语候选”。空译文候选可在人工审核前补译；扫描规则用于排查候选过多或过少。</span>
          <button className="btn btn-ghost" disabled={!activeBatch || !needsTranslation.length || busy} onClick={() => activeBatch && onTranslateMissingCandidates(activeBatch.id)}>补译空候选</button>
          <button className="btn btn-ghost" onClick={onFreq}>查看扫描规则</button>
        </div>
      </details>
      {backfill ? (
        <>
          <div className="scan-explain">
            <strong>本次扫描结果</strong>
            <span>本地扫描 {candidates} 个候选，按中文去重后 {uniqueCandidates} 个；已在库 {existing} 个；AI 补漏：{aiSupplementText}；待人工确认 {pendingCandidates.length} 个。</span>
          </div>
          <div className="workflow-note-grid compact-grid">
            <div><strong>待补译</strong><span>{needsTranslation.length}</span></div>
            <div><strong>AI 补漏</strong><span>{aiSupplementText}</span></div>
            <div><strong>待审核</strong><span>{readyCandidates.length}</span></div>
            <div><strong>已加入</strong><span>{accepted}</span></div>
            <div><strong>已跳过</strong><span>{rejected}</span></div>
          </div>
          <div className="confirm-panel">
            <div className="confirm-head">
              <div>
                <strong>候选批次审核</strong>
                <span>{activeBatch ? `批次：${activeBatch.label}` : '暂无扫描批次'}。空 {lang.targetHeader} 不能加入；可先补译或手工编辑，再加入项目术语库。</span>
              </div>
              <div className="confirm-actions">
                <button className="btn btn-ghost btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'reject')}>全部跳过</button>
                <button className="btn btn-primary btn-sm" disabled={!activeBatch || !readyCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, readyCandidates, 'accept')}>全部加入已完成项</button>
              </div>
            </div>
            {reviewPreview.length ? (
              <div className="table-scroll">
                <table className="pending-term-table">
                  <thead><tr><th>状态</th><th>ID</th><th>CN</th><th>{lang.targetHeader}</th><th>{lang.altHeader}</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
                  <tbody>
                    {reviewPreview.map((term) => (
                      <PendingTermReviewRowV2
                        key={term.id}
                        candidate={term}
                        batchId={activeBatch?.id || ''}
                        busy={busy}
                        onUpdateCandidate={onUpdateCandidate}
                        onResolveCandidates={onResolveCandidates}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-inline">暂无待审核词条，可以继续下一步。</div>
            )}
            {pendingCandidates.length > 12 ? (
              <div className="review-table-foot">
                <span>{expanded ? `已展开全部 ${pendingCandidates.length} 条。` : `当前展示前 ${reviewPreview.length} 条，展开后可查看并编辑全部 ${pendingCandidates.length} 条。`}</span>
                <button className="btn btn-ghost btn-sm" disabled={!pendingCandidates.length} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起' : `展开全部 ${pendingCandidates.length} 条`}</button>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  )
}

export function PendingTermReviewRowV2({
  candidate,
  batchId,
  busy,
  onUpdateCandidate,
  onResolveCandidates
}: {
  candidate: GlossaryCandidate
  batchId: string
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: candidate.term_key || '',
    source: candidate.source || '',
    target: candidate.target || '',
    target_alt: candidate.target_alt || '',
    category: candidate.category || '',
    note: normalizeGlossaryNote(candidate.note)
  })

  useEffect(() => {
    setDraft({
      term_key: candidate.term_key || '',
      source: candidate.source || '',
      target: candidate.target || '',
      target_alt: candidate.target_alt || '',
      category: candidate.category || '',
      note: normalizeGlossaryNote(candidate.note)
    })
    setEditing(false)
  }, [candidate.id, candidate.term_key, candidate.source, candidate.target, candidate.target_alt, candidate.category, candidate.note])

  const canAcceptDraft = Boolean(draft.target.trim())
  const canAcceptCandidate = Boolean(candidate.target?.trim())

  async function save(confirmAfter = false) {
    await onUpdateCandidate(candidate, draft)
    setEditing(false)
    if (confirmAfter && canAcceptDraft) onResolveCandidates(batchId, [candidate], 'accept')
  }

  function cell(key: keyof typeof draft) {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  const statusLabel = canAcceptCandidate ? '待审核' : '待补译'
  return (
    <tr>
      <td><span className={`term-kind ${canAcceptCandidate ? 'filled' : 'new'}`}>{statusLabel}</span></td>
      <td>{cell('term_key')}</td>
      <td>{cell('source')}</td>
      <td>{cell('target')}</td>
      <td>{cell('target_alt')}</td>
      <td>{cell('category')}</td>
      <td>{cell('note')}</td>
      <td>
        <div className="term-review-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => save(false)}>保存</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId || !canAcceptDraft} onClick={() => save(true)}>保存并加入</button>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(false)}>取消</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(true)}>编辑</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId || !canAcceptCandidate} onClick={() => onResolveCandidates(batchId, [candidate], 'accept')}>加入</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId} onClick={() => onResolveCandidates(batchId, [candidate], 'reject')}>跳过</button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

export function StepLang({
  selectedLanguage,
  setSelectedLanguage,
  selectedLanguages,
  toggleSelectedLanguage,
  sourceArtifact,
  translationReadiness,
  setQaArtifact,
  setStep
}: {
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
  sourceArtifact?: Artifact | null
  translationReadiness?: TranslationReadiness | null
  setQaArtifact?: (artifact: Artifact | null) => void
  setStep?: (step: number) => void
}) {
  const readyForQa = Boolean(sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness))
  const selectedLabels = selectedLanguages.map((code) => languageSpec(code).short).join(' / ')
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 6</span>选择目标语言</div>
      <div className="panel-desc">目标语言优先从 STEP 4 的表头自动识别；识别到的语言会默认勾选。后续翻译 / QA 仍按语言拆成单语言任务执行。</div>
      {readyForQa ? (
        <div className="translation-readiness-box ready">
          <div className="readiness-head">
            <strong>已译表已完成语言判定</strong>
            <span>无需进入 AI 翻译</span>
          </div>
          <p>当前表已经有完整译文，已选目标语言为 {selectedLabels || languageSpec(selectedLanguage).short}。建议直接进入 STEP 8 校对。</p>
          {sourceArtifact && setQaArtifact && setStep ? <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button> : null}
        </div>
      ) : null}
      <div className="lang-grid">
        {supportedLanguages.map((lang) => (
          <button
            key={lang.code}
            type="button"
            className={`lang-chip ${selectedLanguages.includes(lang.code) ? 'selected' : ''} ${selectedLanguage === lang.code ? 'current' : ''}`}
            onClick={() => toggleSelectedLanguage(lang.code)}
            onDoubleClick={() => setSelectedLanguage(lang.code)}
            title={selectedLanguage === lang.code ? '当前预览 / 当前执行语言' : '点击勾选并设为当前语言'}
          >
            <span className="lang-check">{selectedLanguages.includes(lang.code) ? '✓' : ''}</span>
            {lang.label}
            {selectedLanguage === lang.code ? <small>当前</small> : null}
          </button>
        ))}
        {unsupportedLanguages.map((lang) => (
          <button key={lang} className="lang-chip disabled" disabled title="暂未支持">{lang} · 未支持</button>
        ))}
      </div>
    </>
  )
}

function WorkflowStepShell({
  stepLabel,
  title,
  description,
  status,
  statusTone = 'neutral',
  nextAction,
  children,
  side
}: {
  stepLabel: string
  title: string
  description: string
  status: string
  statusTone?: 'neutral' | 'ready' | 'warn' | 'blocked' | 'running'
  nextAction: string
  children: React.ReactNode
  side: React.ReactNode
}) {
  return (
    <div className="workflow-step-shell">
      <div className="workflow-step-head">
        <div>
          <span className="badge">{stepLabel}</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        <div className={`workflow-step-status ${statusTone}`}>
          <span>当前状态</span>
          <strong>{status}</strong>
          <em>{nextAction}</em>
        </div>
      </div>
      <div className="workflow-step-grid">
        <div className="workflow-primary">{children}</div>
        <aside className="workflow-side">{side}</aside>
      </div>
    </div>
  )
}

function WorkflowSideCard({
  title,
  children,
  tone = 'neutral'
}: {
  title: string
  children: React.ReactNode
  tone?: 'neutral' | 'ready' | 'warn' | 'blocked'
}) {
  return (
    <section className={`workflow-side-card ${tone}`}>
      <strong>{title}</strong>
      {children}
    </section>
  )
}

function WorkflowFactList({ items }: { items: { label: string; value: React.ReactNode }[] }) {
  return (
    <div className="workflow-fact-list">
      {items.map((item) => (
        <div key={item.label}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
        </div>
      ))}
    </div>
  )
}

function DeliveryFileLinks({ files, projectId }: { files: DeliveryFile[]; projectId: string }) {
  if (!files.length) return <div className="muted-left">暂无可下载文件。</div>
  return (
    <div className="workflow-file-list">
      {files.map((file, index) => (
        <a key={`${file.kind}-${file.filename}-${index}`} className="workflow-file-link" href={deliveryFileHref(file, projectId)}>
          <span>{deliveryFileLabel(file)}</span>
          <strong>{file.filename}</strong>
        </a>
      ))}
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
  const translateAction = multiLanguageMode && onTranslateQueue ? onTranslateQueue : onTranslate
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
    ? String(currentTranslationRun.metadata?.user_message || '候选术语尚未确认，当前翻译已暂停；请回 STEP 5 确认术语，或再次启动并确认继续无术语翻译。')
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
          <div className="info-line compact">操作方式：点击“开始多语言翻译”，工作台会自动逐个处理已选语言；无需反复回 STEP 6 手动切换。</div>
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
              <div className="ok-line">检测到这份表已有译文：无需 AI 翻译，默认进入 QA；如确需跳过 QA，可在 STEP 8 使用“临时跳过 QA 直接归档”。</div>
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
        {finishingTranslation ? <div className="info-line compact">译文批次已完成，正在做 QA 校验和结果归档。完成后会自动接到 STEP 8；请不要在此时重复启动。</div> : null}
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
  showHistory = true
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
  const handleSkipArchive = () => {
    const artifact = effectiveQaArtifact
    if (!artifact || !canArchiveWithoutQA) return
    const confirmed = window.confirm('跳过 QA 会把当前译文直接写入译文归档，系统不会检查术语、变量、中文残留。确认继续？')
    if (confirmed) onSkipQAArchive(artifact)
  }
  const originText = effectiveQaArtifact?.run_id && previousTranslationRun?.id === effectiveQaArtifact.run_id
    ? `上一翻译结果：${previousTranslationRun.id.slice(0, 8)}`
    : qaRole === 'language_source'
      ? sourceArtifact?.id === effectiveQaArtifact?.id && selectedReadiness
        ? `来自 STEP 4 已译表：${selectedReadiness.translated_rows}/${selectedReadiness.source_rows} 行已有译文`
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
  const multiQaMode = selectedLanguages.length > 1
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
      description="生成最终交付文件，并在当前页面直接下载；完成后回到项目概览交付页。"
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
                <p>仍有 {pendingIssueCount || '若干'} 个 QA 问题未清零；交付文件会附带问题摘要和修改记录，便于后续复查。</p>
                <button className="btn btn-ghost btn-sm" onClick={() => setStep(8)}>回到校对修复</button>
              </>
            ) : (
              <p>{generated ? '交付文件已经生成，可直接下载；底部“完成”会回到项目交付页。' : '系统会把最终译文、修改记录和必要的 QA 摘要打到交付目录。'}</p>
            )}
          </WorkflowSideCard>
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
              {busy ? '生成中...' : generated ? '重新生成交付文件' : '生成交付文件'}
            </button>
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

function findWizardDeliveryRun(project: Project, latestRun: Run | null): Run | null {
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

function wizardDeliveryFiles(
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

export function TaskHistoryTable({ project, kind, title }: { project: Project; kind: HistoryKind; title: string }) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const runs = kind === 'all' ? (project.runs || []) : (project.runs || []).filter((run) => run.kind === kind)
  const selectedRun = runs.find((run) => run.id === selectedRunId) || null
  return (
    <div className="card history-card">
      <div className="card-title">
        <div className="left">{title}</div>
      </div>
      <table className="history-table">
        <thead>
          <tr><th>日期</th><th>任务名称</th><th>目标语言</th><th>处理量</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const artifacts = runArtifacts(project, run.id)
            const download = downloadableArtifact(artifacts, kind)
            const task = runTaskSummary(project, run)
            return (
              <tr key={run.id}>
                <td>{formatDate(run.created_at)}</td>
                <td>{task.taskType} · {task.taskLabel}</td>
                <td>{run.language ? languageSpec(normalizeLanguageCode(run.language) || 'en').short : '-'}</td>
                <td>{runProcessedLabel(run)}</td>
                <td><span className={`tag ${run.status === 'passed' ? 'tag-done' : run.status === 'failed' ? 'tag-warn' : 'tag-doing'}`}>{run.status}</span></td>
                <td>
                  <div className="link-actions">
                    <button className="link-button" onClick={() => setSelectedRunId(selectedRunId === run.id ? null : run.id)}>查看</button>
                    {download ? <a href={artifactDownloadHref(download, project.id)}>{kind === 'qa' ? '下载校对结果' : '下载已译表'}</a> : <span className="muted-inline" title="该任务暂无可下载结果">无下载</span>}
                  </div>
                </td>
              </tr>
            )
          })}
          {!runs.length ? <tr><td colSpan={6} className="muted">暂无历史记录。</td></tr> : null}
        </tbody>
      </table>
      {selectedRun ? <RunDetail project={project} run={selectedRun} kind={kind} /> : null}
    </div>
  )
}

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
        <span>{run.id}</span>
      </div>
      <div className="history-detail-grid">
        <div><strong>任务类型</strong><span>{task.taskType}</span></div>
        <div><strong>任务ID</strong><span>{task.taskLabel}</span></div>
        <div><strong>状态</strong><span>{run.status}</span></div>
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

export function qaPendingIssueCount(run: Run | null | undefined, issues: QualityIssue[] = []): number {
  if (!run) return 0
  const summary = (run.metadata?.quality_summary || {}) as { hard_errors?: number }
  const hardFromSummary = Number(summary.hard_errors || 0)
  const visibleHardCount = issues.filter((issue) => issue.severity === 'hard').length
  return hardFromSummary || visibleHardCount
}

export function qaStatusBadge(status: string): string {
  if (status === 'passed') return '已通过'
  if (status === 'failed') return '未通过'
  if (status === 'running' || status === 'queued') return '运行中'
  if (status === 'needs_input') return '需处理'
  return status || '未运行'
}

export function qaRunTagClass(run: Run | null | undefined): string {
  if (!run) return 'tag-doing'
  if (run.status === 'passed') return 'tag-done'
  if (run.status === 'failed') return 'tag-warn'
  return 'tag-doing'
}

export function qaRunSummaryText(run: Run | null | undefined, pendingIssueCount = 0): string {
  if (!run) return '尚未运行 QA。请选择译文表后点击“运行 QA”。'
  if (run.status === 'passed') return 'QA 已通过，可以进入交付页生成最终文件。'
  if (run.status === 'failed') return `QA 未通过：发现 ${pendingIssueCount || '若干'} 个问题。建议先修复并重跑；急需时可带问题摘要交付。`
  if (run.status === 'queued' || run.status === 'running') return 'QA 正在运行，请等待当前任务完成。'
  if (run.status === 'needs_input') return 'QA 需要补充输入后继续。'
  return `当前状态：${run.status}`
}

export function qaRunActionText(run: Run | null | undefined, pendingIssueCount = 0): string {
  if (!run) return '运行 QA'
  if (run.status === 'passed') return '去交付页生成最终文件'
  if (run.status === 'failed') return pendingIssueCount ? '先修复；急需时交付' : '查看 QA 报告后交付'
  if (run.status === 'queued' || run.status === 'running') return '等待任务完成'
  return '按提示补齐输入'
}

export function runDeliveryState(run: Run, visibleArtifacts: Artifact[]): string {
  if (visibleArtifacts.some((artifact) => artifact.kind === 'qa_final_workbook' || artifact.role === 'translation_workbook')) return '可生成最终交付'
  if (run.status === 'passed') return '已通过，等待生成交付文件'
  if (run.status === 'needs_input') return '需要补充输入'
  if (run.status === 'failed') return 'QA 未通过，可带问题摘要交付'
  return '处理中'
}

export function TaskRunSummary({
  run,
  issues = [],
  projectHardErrors
}: {
  run: Run
  issues?: QualityIssue[]
  projectHardErrors?: number
}) {
  const title = run.kind === 'qa' ? '最近校对任务' : run.kind === 'translation' ? '最近翻译任务' : '最近任务'
  const issueCount = qaPendingIssueCount(run, issues)
  const issueText = run.kind === 'qa'
    ? (run.status === 'passed' ? 'QA 已通过，可交付' : issueCount ? `QA 未通过，待处理 ${issueCount} 条` : qaStatusBadge(run.status))
    : (issueCount ? `待处理问题 ${issueCount} 条` : '无待处理问题')
  const projectGate = typeof projectHardErrors === 'number' ? `，项目规则必须修复 ${projectHardErrors}` : ''
  return (
    <div className="task-summary">
      <div>
        <strong>{title}</strong>
        <span>{new Date(run.created_at).toLocaleString()}</span>
      </div>
      <div>
        <span className={`tag ${qaRunTagClass(run)}`}>{qaStatusBadge(run.status)}</span>
        <span>{issueText}{projectGate}</span>
      </div>
    </div>
  )
}

export function IssueSummary({ issues }: { issues: QualityIssue[] }) {
  return (
    <div className="issue-summary">
      <div className="card-title"><div className="left">QA 问题摘要</div></div>
      <IssueGuide issues={issues} editableCount={0} />
      <IssueChips issues={issues} />
      <div className="muted-left">这些问题缺少可直接编辑的表格行定位；请查看 QA 报告，或重新生成带行号的问题列表后再批量修复。</div>
    </div>
  )
}

export function IssueChips({ issues }: { issues: QualityIssue[] }) {
  const counts = issues.reduce<Record<string, number>>((acc, issue) => {
    const key = issueTypeLabel(issue.check_type || issue.source)
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6)
  return (
    <div className="issue-chips">
      {top.map(([name, count]) => <span key={name}>{name}: {count}</span>)}
    </div>
  )
}

export function IssueGuide({ issues, editableCount }: { issues: QualityIssue[]; editableCount: number }) {
  const hard = issues.filter((issue) => issue.severity === 'hard').length
  const soft = issues.filter((issue) => issue.severity !== 'hard').length
  return (
    <div className="issue-guide">
      <div>
        <strong>当前不能作为最终交付</strong>
        <span>{hard} 个必须修复，{soft} 个建议修复；其中 {editableCount} 个可在网页直接改后重跑 QA。</span>
      </div>
      <p>这些是规则 QA 抓到的问题。模拟翻译通常会产生大量术语缺失；正式接入 GPT / Claude 后会按提示词和术语快照翻译，问题量会下降，但不会承诺自动清零，最终仍以“必须修复问题 = 0”作为交付标准。</p>
    </div>
  )
}

export function issueTypeLabel(value: string): string {
  const key = String(value || '').toLowerCase()
  const labels: Record<string, string> = {
    term_missing: '术语未命中',
    term_partial_hit: '术语只命中一部分',
    ui_length_overflow: '界面长度超限',
    title_case_overuse: '大小写风格异常',
    placeholder_mismatch: '变量占位符错误',
    tag_mismatch: '标签不一致',
    newline_mismatch: '换行不一致',
    raw_cn: '译文残留中文',
    global_harness: '通用 QA 规则',
    project_harness: '项目规则',
    semantic_qa: '模型语义校对'
  }
  return labels[key] || value || '质量问题'
}

export function severityLabel(value: string): string {
  return String(value).toLowerCase() === 'hard' ? '必须修复' : '建议修复'
}

export function issueSourceLabel(value: string): string {
  const key = String(value || '').toLowerCase()
  if (key === 'global_harness') return '通用规则'
  if (key === 'project_harness') return '项目规则'
  if (key === 'semantic_qa') return '模型校对'
  return value || 'QA'
}

export function issueHumanMessage(issue: QualityIssue): string {
  const sourceTerm = issue.message.match(/for ['"](.+?)['"]/)?.[1]
  const expected = issue.message.match(/expected one of \[(.+?)\]/)?.[1]?.replace(/['"]/g, '').trim()
  if (issue.check_type === 'term_missing' && sourceTerm && expected) {
    return `原文术语「${sourceTerm}」未按项目术语表翻译，建议使用：${expected}。`
  }
  if (issue.check_type === 'term_partial_hit' && sourceTerm && expected) {
    return `原文术语「${sourceTerm}」只翻出了一部分，建议完整使用：${expected}。`
  }
  if (issue.check_type === 'ui_length_overflow') return '译文可能超出按钮、弹窗或移动端 UI 宽度，需要缩短。'
  if (issue.check_type === 'title_case_overuse') return '译文大小写风格可能过度标题化，需要改成更自然的界面文案。'
  return issue.message || issueTypeLabel(issue.check_type)
}
