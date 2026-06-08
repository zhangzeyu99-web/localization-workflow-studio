import React, { useEffect, useState } from 'react'
import { API } from '../../apiClient'
import { artifactKindLabel, artifactPickerLabel, artifactRole, newestArtifact, pickerArtifacts, runArtifacts } from '../../domain/artifacts'
import { formatDate, formatDateTime, shortRunId } from '../../domain/format'
import { normalizeGlossaryNote, projectPromptForLanguage } from '../../domain/projectAssets'
import { canSkipModelTranslation, effectiveBatchSize, estimateBatches, findVisibleTranslationRun, getTranslationProgress, isTranslationRunResumable, latestRunOfKind, matchesTranslationRun } from '../../domain/translationFlow'
import { languageQuery, languageSpec, supportedLanguages, unsupportedLanguages, normalizeLanguageCode, type LanguageCode } from '../../languages'
import { ProjectMetaTable } from '../project/ProjectMeta'
import { ActionStatus, ArtifactNote, AssetSelect, CheckItem, FileBox, GlossaryPreview, LanguageSelector, SelectedInput, TranslationProgressBar } from '../shared/WorkflowPrimitives'
import type { AppSettings, Artifact, DeliverableTask, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, HistoryKind, Project, ProjectHarness, QualityIssue, Run, TranslationProgress, TranslationReadiness } from '../../types'

export const steps = ['项目资料', 'AI 分析', '术语表', '语言表', '高频词', '目标语言', '模型翻译', '自动校对', '交付']

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
          <FileBox label="上传待翻译 workbook" onFile={onUploadSource} />
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
  onCreateDelivery: (runId: string) => void
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
          const hasDelivery = Boolean(finalFile?.download_url && changesFile?.download_url)
          return (
            <div key={task.run_id} className="delivery-card delivery-line">
              <div className="delivery-head">
                <div>
                  <strong>{deliveryTaskTitle(task)}</strong>
                  <span>{deliveryTaskSubtitle(task)}</span>
                </div>
                <span className={`tag ${task.status === 'passed' ? 'tag-done' : 'tag-doing'}`}>{deliveryStatusLabel(task)}</span>
              </div>
              <div className="delivery-line-info">
                <div><span>任务进度</span><strong>{deliveryProgressLabel(task)}</strong></div>
                <div><span>交付结果</span><strong>{hasDelivery ? '已生成 2 个 Excel' : '待生成'}</strong></div>
              </div>
              <div className="delivery-actions">
                {finalFile?.download_url ? <a className="btn btn-primary btn-sm" href={finalFile.download_url}>下载最终译文</a> : null}
                {changesFile?.download_url ? <a className="btn btn-ghost btn-sm" href={changesFile.download_url}>下载修改记录</a> : null}
                {!hasDelivery ? <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onCreateDelivery(task.run_id)}>生成交付文件</button> : null}
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
  if (task.status === 'passed' && Number(task.qa_hard_errors || 0) === 0) return '可交付'
  if (task.status === 'failed') return '未通过'
  return task.status || '处理中'
}

export function deliveryProgressLabel(task: DeliverableTask): string {
  const total = Number(task.source_rows || task.processed_rows || 0)
  const done = Number(task.processed_rows || task.translated_rows || 0)
  const qa = `QA 必修 ${task.qa_hard_errors ?? 0} / 建议 ${task.qa_soft_warnings ?? 0}`
  return total > 0 ? `${done}/${total} 行 · ${qa}` : qa
}

export function providerName(settings: AppSettings | null): string {
  if (!settings) return '未加载'
  if (settings.provider === 'openai') return 'GPT'
  if (settings.provider === 'anthropic') return 'Claude'
  if (settings.provider === 'test-fake') return 'Test Fake'
  return settings.provider || '未配置'
}

export function formalTranslationBlockReason(settings: AppSettings | null, sourceArtifact: Artifact | null, project?: Project, readiness?: TranslationReadiness | null): string {
  if (!sourceArtifact) return '请先上传或选择待翻译语言表。'
  if (!settings) return '模型配置尚未加载。'
  const readinessBlock = translationReadinessBlockReason(readiness)
  if (readinessBlock) return readinessBlock
  if (!['openai', 'openai-chat', 'anthropic', 'test-fake'].includes(String(settings.provider))) return '请先在设置里选择 GPT、GPT 中转站或 Claude。'
  if (settings.provider !== 'test-fake' && !settings.api_key) return `${providerName(settings)} API key 未配置，正式翻译已阻断。`
  return ''
}

export function translationReadinessBlockReason(readiness?: TranslationReadiness | null): string {
  if (!readiness) return ''
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
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  qualityIssues: QualityIssue[]
  settings: AppSettings | null
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  onBack: () => void
  onUploadSource: (file: File) => void
  onUploadTerm: (file: File) => void
  onUploadAsset: (file: File) => void
  onAnalyze: () => void
  onGlossaryExtract: () => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onTranslate: () => void
  onCancelTranslate: () => void
  onDirectQA: () => void
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  onFreq: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  busy: boolean
}) {
  const { project, step, setStep } = props
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
        {step === 8 ? <StepQA {...props} /> : null}
        {step === 9 ? <StepDone {...props} /> : null}
      </div>
      <div className="actions">
        <button className="btn btn-ghost" disabled={step === 1} onClick={() => setStep(step - 1)}>← 上一步</button>
        <button className="btn btn-primary" disabled={props.busy} onClick={() => setStep(Math.min(9, step + 1))}>{step === 9 ? '🏁 完成' : '下一步 →'}</button>
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
        <span className={intro.trim().length > 20 || project.description ? 'ok' : 'warn'}>{intro.trim().length > 20 || project.description ? '✓ 信息可用于生成 prompt' : '⚠ 建议补充更多信息'}</span>
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
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 2</span>AI 分析与专属提示词生成</div>
      <div className="panel-desc">基于文字资料、已归档素材和项目资产生成提示词、项目规则与元信息。生成后会自动保存到当前项目。当前素材：{assetArtifacts.length} 个。</div>
      <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>🤖 启动 AI 分析</button>
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
  selectedLanguage
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
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 3</span>导入游戏术语表</div>
      <div className="panel-desc">可使用已有术语表、上传新文件、预览后导入，也可跳过由 Step 5 生成。</div>
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} />
        <FileBox label="上传术语表 xlsx/csv/json" onFile={onUploadTerm} />
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
  selectedLanguage
}: {
  project: Project
  onUploadSource: (file: File) => void
  sourceArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>导入待翻译内容</div>
      <div className="panel-desc">可选择已有语言表，也可上传新的 Excel 语言表；默认字段：ID | cn | {lang.targetHeader}。</div>
      <div className="action-card">
        <AssetSelect label="使用已有语言表" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} />
        <FileBox label="上传 language.xlsx" onFile={onUploadSource} />
      </div>
      {sourceArtifact ? <ArtifactNote artifact={sourceArtifact} /> : null}
    </>
  )
}

export function StepFreqV2({
  onGlossaryExtract,
  onFreq,
  sourceArtifact,
  assetArtifacts,
  latestRun,
  glossaryBatches,
  glossaryCandidates,
  busy,
  onUpdateCandidate,
  onResolveCandidates,
  onTranslateMissingCandidates,
  selectedLanguage
}: {
  project: Project
  onGlossaryExtract: () => void
  onFreq: () => void
  sourceArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  selectedLanguage: LanguageCode
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
  const accepted = activeBatch?.counts?.accepted ?? glossaryCandidates.filter((candidate) => candidate.status === 'accepted').length
  const rejected = activeBatch?.counts?.rejected ?? glossaryCandidates.filter((candidate) => candidate.status === 'rejected').length
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 5</span>高频词扫描 & 术语候选审核</div>
      <div className="panel-desc">先扫描语言表中的高频中文词；缺少 {lang.short} 的候选需要显式补译或人工填写，审核加入后才进入项目术语库。</div>
      <div className="row-actions action-card">
        <span className="asset-meta">语言表：{sourceArtifact?.label || '未选择'}</span>
        <span className="asset-meta">参考素材：{assetArtifacts.length} 个</span>
        <button className="btn btn-primary" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>🔎 开始扫描</button>
        <button className="btn btn-ghost" disabled={!activeBatch || !needsTranslation.length || busy} onClick={() => activeBatch && onTranslateMissingCandidates(activeBatch.id)}>补齐缺失译文</button>
        <button className="btn btn-ghost" onClick={onFreq}>💡 查看补充策略</button>
      </div>
      {backfill ? (
        <>
          <div className="scan-explain">
            <strong>本次扫描结果</strong>
            <span>扫描 {candidates} 个候选，按中文去重后 {uniqueCandidates} 个；已在库 {existing} 个；待补译 {needsTranslation.length} 个；待审核 {readyCandidates.length} 个。</span>
          </div>
          <div className="workflow-note-grid compact-grid">
            <div><strong>待补译</strong><span>{needsTranslation.length}</span></div>
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

export function StepLang({ selectedLanguage, setSelectedLanguage }: { selectedLanguage: LanguageCode; setSelectedLanguage: (language: LanguageCode) => void }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 6</span>选择目标语言</div>
      <div className="panel-desc">选择本次任务的目标语言；每次 run 仍按单语言执行，多语言任务会拆成多个单语言流程。</div>
      <div className="lang-grid">
        {supportedLanguages.map((lang) => (
          <button
            key={lang.code}
            className={`lang-chip ${selectedLanguage === lang.code ? 'selected' : ''}`}
            onClick={() => setSelectedLanguage(lang.code)}
          >
            {lang.label}
          </button>
        ))}
        {unsupportedLanguages.map((lang) => (
          <button key={lang} className="lang-chip disabled" disabled title="暂未支持">{lang} · 未支持</button>
        ))}
      </div>
    </>
  )
}

export function StepTranslate({
  project,
  settings,
  status,
  onTranslate,
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
  selectedLanguage
}: {
  project: Project
  settings: AppSettings | null
  status: string
  onTranslate: () => void
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
}) {
  const lang = languageSpec(selectedLanguage)
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const batchSize = effectiveBatchSize(settings)
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === batchSize ? translationReadiness : null
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project, readiness)
  const alreadyTranslated = canSkipModelTranslation(readiness)
  const estimatedBatches = estimateBatches(readiness?.source_rows, batchSize)
  const latestMatchingRun = latestRun && matchesTranslationRun(latestRun, selectedLanguage, sourceArtifact?.id, 'translation_run') ? latestRun : null
  const currentTranslationRun = latestMatchingRun || findVisibleTranslationRun(project, selectedLanguage, sourceArtifact?.id, 'translation_run')
  const progress = getTranslationProgress(currentTranslationRun)
  const activeTranslation = Boolean(currentTranslationRun && ['queued', 'running'].includes(currentTranslationRun.status))
  const resumable = Boolean(currentTranslationRun && isTranslationRunResumable(currentTranslationRun))
  const invalidIdText = readiness?.invalid_id_rows ? ` / 空 ID ${readiness.invalid_id_rows}` : ''
  const readinessText = readiness
    ? `${readiness.source_rows} 行原文 / ${readiness.translated_rows} 行已有译文 / 空译文 ${readiness.empty_target_rows} / 中文残留 ${readiness.cjk_target_rows}${invalidIdText} / 预计 ${readiness.estimated_batches} 批`
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
  const showTranslateStatus = busy
    || Boolean(progress)
    || /provider|API|workpack|batch|QA|\u7ffb\u8bd1|\u6821\u5bf9/i.test(status)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 7</span>{lang.short} 模型翻译</div>
      <div className="panel-desc">先检查语言表是否已有目标译文；已有译文则跳过模型翻译并进入校对，空译文或中文残留才生成 workpack 分批调用 GPT / Claude。</div>
      <div className="action-card">
        <AssetSelect label="语言表输入" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} />
        <div className={`translation-readiness-box ${readinessState.tone}`}>
          <div className="readiness-head">
            <strong>译文检查</strong>
            <span>{readinessState.label}</span>
          </div>
          <p>{readinessText}</p>
        </div>
        <div className="translation-batch-panel compact">
          <div className="batch-control-head">
            <div>
              <strong>后台编排</strong>
              <span>系统按预设自动拆批、限流、重试和断点续跑。</span>
            </div>
            <em>{batchSize} 行/批 · 预计 {estimatedBatches || '-'} 批</em>
          </div>
        </div>
        <div className="translation-actions">
          {alreadyTranslated ? (
            <>
              <div className="ok-line">检测到这份表已有可校对译文，不需要重新走整表翻译；残留问题交给 QA 处理。</div>
              <button className="btn btn-primary" disabled={busy} onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>跳到校对</button>
            </>
          ) : (
            <>
              <button className="btn btn-primary" disabled={busy || activeTranslation || Boolean(blockReason)} onClick={onTranslate}>{resumable ? '↻ 继续后台翻译' : `⚡ 开始 ${lang.short} 正式翻译`}</button>
              {activeTranslation ? <button className="btn btn-ghost" disabled={busy} onClick={onCancelTranslate}>暂停/取消后台任务</button> : null}
            </>
          )}
          {blockReason && !alreadyTranslated ? <div className="warn-line inline-warning">{blockReason}</div> : null}
        </div>
        {showTranslateStatus ? <ActionStatus status={status} busy={busy} /> : null}
        {progress ? <TranslationProgressBar progress={progress} /> : null}
        {currentTranslationRun?.metadata?.reason === 'api_budget_confirmation_required' ? (
          <div className="warn-line">预计 API token 超过提醒阈值；点击“继续后台翻译”会二次确认预算，并从已完成批次继续。</div>
        ) : null}
        {currentTranslationRun?.metadata?.reason === 'background_job_interrupted' ? (
          <div className="warn-line">上次后台任务被中断；点击“继续后台翻译”可从已落盘批次恢复。</div>
        ) : null}
        {progress?.failed_batch && currentTranslationRun ? <BatchDebugLinks runId={currentTranslationRun.id} batchIndex={progress.failed_batch} /> : null}
      </div>
      <div className="translation-guard-strip">
        <span>项目术语库 <strong>{glossaryCount} 条</strong></span>
        <span>{lang.short} 提示词 <strong>{projectPromptForLanguage(project, selectedLanguage) ? '已生成' : '未生成'}</strong></span>
        <span>校对门槛 <strong>QA 通过后交付</strong></span>
      </div>
      {currentTranslationRun ? <TaskRunSummary run={currentTranslationRun} issues={qualityIssues} /> : null}
    </>
  )
}

export function BatchDebugLinks({ runId, batchIndex }: { runId: string; batchIndex: number }) {
  return (
    <div className="row-actions wrap">
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/request`}>下载失败批次输入</a>
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/error`}>下载错误报告</a>
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/raw-response`}>下载原始响应</a>
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
  onManualFixes,
  onModelFixes,
  onUploadTranslation,
  busy,
  status,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  latestRun: Run | null
  sourceArtifact: Artifact | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  qaArtifact: Artifact | null
  setQaArtifact: (artifact: Artifact | null) => void
  onDirectQA: () => void
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  busy: boolean
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const latestQaRun = latestRun?.kind === 'qa' ? latestRun : latestRunOfKind(project, 'qa')
  const projectQuality = latestQaRun?.metadata?.project_harness_quality as { hard_errors?: number; soft_warnings?: number } | undefined
  const projectHardErrors = projectQuality?.hard_errors ?? 0
  const qaIssues = latestRun?.id === latestQaRun?.id ? qualityIssues.filter((issue) => issue.severity === 'hard' || issue.severity === 'soft') : []
  const previousTranslationRun = latestRunOfKind(project, 'translation')
  const previousTranslationArtifact = previousTranslationRun
    ? newestArtifact(runArtifacts(project, previousTranslationRun.id), ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
    : null
  const qaRole = qaArtifact ? artifactRole(qaArtifact) : ''
  const selectedReadiness = qaArtifact && translationReadiness?.artifact_id === qaArtifact.id ? translationReadiness : null
  const originText = qaArtifact?.run_id && previousTranslationRun?.id === qaArtifact.run_id
    ? `上一翻译结果：${previousTranslationRun.id.slice(0, 8)}`
    : qaRole === 'language_source'
      ? selectedReadiness
        ? `此前导入的语言表：${selectedReadiness.translated_rows}/${selectedReadiness.source_rows} 行已有译文`
        : '此前导入的语言表；运行前会按译文表检查'
      : qaArtifact
        ? '直接导入的译文 workbook'
        : sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness)
          ? '已检测到当前语言表可进入校对，可直接选择运行'
          : '请选择要校对的译文表'
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const qaStatus = latestQaRun ? latestQaRun.status : '未运行'
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 8</span>校对任务</div>
      <div className="panel-desc">这里是校对入口：可以接上一步翻译结果，也可以选择之前导入且已有译文的语言表，或上传一份新的译文 workbook。</div>
      <div className="action-card">
        <div className="language-inline-select">
          <span>校对目标语言：</span>
          <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
        </div>
        <div className="qa-entry-row">
          <button className="btn btn-ghost" disabled={!previousTranslationArtifact || busy} onClick={() => setQaArtifact(previousTranslationArtifact)}>使用上一翻译结果</button>
          <button className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={() => sourceArtifact && setQaArtifact(sourceArtifact)}>使用当前语言表</button>
        </div>
        <AssetSelect label="选择已译表 / 翻译结果" project={project} role={['translation_workbook', 'language_source']} value={qaArtifact} onChange={setQaArtifact} allowEmpty />
        <FileBox label="上传新的译文 workbook" onFile={onUploadTranslation} />
        <button className="btn btn-primary" data-testid="run-qa" disabled={!qaArtifact || busy} onClick={onDirectQA}>运行 QA</button>
        {!qaArtifact ? <div className="warn-line">请选择“上一翻译结果”、此前导入的已译语言表，或上传新的译文 workbook 后再运行 QA。</div> : null}
        <ActionStatus status={status} busy={busy} />
      </div>
      <div className="check-list">
        <CheckItem ok={Boolean(qaArtifact)} title="处理文件" detail={qaArtifact ? qaArtifact.label : '未选择'} />
        <CheckItem ok={Boolean(qaArtifact)} title="来源说明" detail={originText} />
        <CheckItem ok={glossaryCount > 0} title="项目术语库" detail={`${glossaryCount} 条，运行时生成快照`} />
        <CheckItem ok={!latestQaRun || latestQaRun.status === 'passed'} title="最近 QA" detail={qaStatus} />
        <CheckItem ok={qaIssues.length === 0} title="待处理问题" detail={qaIssues.length ? `${qaIssues.length} 条` : '无'} />
      </div>
      <TaskHistoryTable project={project} kind="qa" title="🕒 校对历史记录" />
      {latestQaRun ? <TaskRunSummary run={latestQaRun} issues={qaIssues} projectHardErrors={projectHardErrors} /> : null}
      {qaIssues.length ? <FailedRowEditor issues={qaIssues} busy={busy} onModelFix={onModelFixes} onApply={onManualFixes} /> : null}
    </>
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

export function StepDone({ project, latestRun }: { project: Project; latestRun: Run | null }) {
  const artifacts = pickerArtifacts(latestRun?.artifacts?.length ? latestRun.artifacts : runArtifacts(project, latestRun?.id))
    .filter((artifact) => artifact.kind === 'qa_final_workbook' || artifact.kind === 'qa_changes')
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 9</span>最终交付</div>
      {latestRun ? <TaskRunSummary run={latestRun} /> : <div className="muted-left">暂无可交付任务。先完成翻译或校对。</div>}
      <div className="artifact-grid">
        {artifacts.map((artifact) => <a key={artifact.id} className="artifact" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}<span>{artifactKindLabel(artifact)}</span></a>)}
      </div>
      <div className="muted-left">正式交付请回到“交付”页生成最终 workbook 和 QA 修改表。</div>
    </>
  )
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
                    {download ? <a href={`/api/artifacts/${download.id}/download`}>下载</a> : <span className="muted-inline" title="该任务暂无可下载交付产物">下载</span>}
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
  return artifacts.find((artifact) => accepted.includes(artifact.role || '') || accepted.includes(artifact.kind)) || null
}

export function RunDetail({ project, run, kind }: { project: Project; run: Run; kind: HistoryKind }) {
  const artifacts = runArtifacts(project, run.id)
  const visibleArtifacts = pickerArtifacts(artifacts.filter((artifact) => downloadableArtifact([artifact], kind)))
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
          <a key={artifact.id} className="btn btn-ghost btn-sm" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}</a>
        ))}
        {!visibleArtifacts.length ? <span className="muted-left">暂无可下载交付产物。</span> : null}
      </div>
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
  const sourceId = String(run.metadata?.manual_fix_source_run_id || run.metadata?.source_run_id || '')
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
      ? `输入已含译文 ${readiness.translated_rows}/${readiness.source_rows} 行，跳过模型翻译`
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
  const quality = (run.metadata?.quality_summary || {}) as Record<string, unknown>
  const globalQuality = quality.global_harness_quality as { rows_scanned?: number } | undefined
  const projectQuality = quality.project_harness_quality as { rows_scanned?: number } | undefined
  return Number(globalQuality?.rows_scanned || projectQuality?.rows_scanned || 0)
}

export function runDeliveryState(run: Run, visibleArtifacts: Artifact[]): string {
  if (visibleArtifacts.some((artifact) => artifact.kind === 'qa_final_workbook' || artifact.role === 'translation_workbook')) return '可生成最终交付'
  if (run.status === 'passed') return '已通过，等待生成交付文件'
  if (run.status === 'needs_input') return '需要补充输入'
  if (run.status === 'failed') return 'QA 未通过'
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
  const summary = run.metadata?.quality_summary as { hard_errors?: number } | undefined
  const metadataHardErrors = Number(summary?.hard_errors ?? 0)
  const issueCount = issues.length || metadataHardErrors
  const issueText = issueCount ? `待处理问题 ${issueCount} 条` : '无待处理问题'
  const projectGate = typeof projectHardErrors === 'number' ? `，项目规则必须修复 ${projectHardErrors}` : ''
  return (
    <div className="task-summary">
      <div>
        <strong>{title}</strong>
        <span>{new Date(run.created_at).toLocaleString()}</span>
      </div>
      <div>
        <span className={`tag ${run.status === 'passed' ? 'tag-done' : 'tag-doing'}`}>{run.status}</span>
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
      <div className="muted-left">这些问题缺少可直接编辑的 workbook 行定位；请查看 QA 报告，或重新生成带行号的问题列表后再批量修复。</div>
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
