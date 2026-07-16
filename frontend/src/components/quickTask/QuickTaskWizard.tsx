import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Check, Download, Square, Zap } from 'lucide-react'
import { api } from '../../apiClient'
import { artifactPickerLabel, uniqueArtifactsByContent } from '../../domain/artifacts'
import { groupQuickTasks, quickTaskIdOfRun, type QuickTaskGroup, type QuickTaskSessionScope } from '../../domain/quickTaskLifecycle'
import { aiProviderConfigurationReminder } from '../../domain/providerSettings'
import { canSkipModelTranslation, effectiveBatchSize, isTranslationRunResumable } from '../../domain/translationFlow'
import { languageQuery, languageSpec, normalizeLanguageArray, normalizeLanguageCode, supportedLanguages, type LanguageCode } from '../../languages'
import { ActionStatus, ArtifactNote, FileBox } from '../shared/WorkflowPrimitives'
import { runStatusLabel } from '../../uiText'
import type { AppSettings, Artifact, DeliverableTask, DeliveryFile, Project, QuickObjective, Run, TranslationReadiness, TranslationTargets } from '../../types'

type StartQuickPayload = {
  inputArtifact: Artifact
  referenceArtifacts: Artifact[]
  objective: QuickObjective
  language: LanguageCode
  taskId: string
  accept: () => boolean
}

export function quickTaskRuns(project: Project): Run[] {
  return (project.runs || []).filter((run) => run.metadata?.task_origin === 'quick_task')
}

export function quickTaskName(run: Run): string {
  return run.kind === 'qa' ? '快速校对' : '快速翻译'
}

export function quickTaskDisplayRun(startedRun: Run | null, _latestRun: Run | null): Run | null {
  return startedRun
}

export function QuickTaskRecent({ project }: { project: Project }) {
  const groups = groupQuickTasks(project.runs || []).slice(0, 3)
  if (!groups.length) return null
  return (
    <div className="quick-recent">
      <div className="quick-recent-title">最近快速任务</div>
      {groups.map((group) => (
        <div key={group.id} className="quick-recent-item">
          <span>{quickTaskName(group.latestRun)} · {languageSpec(normalizeLanguageCode(group.latestRun.language) || 'en').short}</span>
          <em>{quickTaskGroupStatus(group)}</em>
        </div>
      ))}
    </div>
  )
}

export function QuickTaskWizard({
  project,
  busy,
  status,
  settings,
  scope,
  initialRun,
  onBack,
  onStartNextTask,
  onUploadFile,
  onStartQuickTask,
  onRefreshProject,
  onContinueTask,
  onViewResult,
  isCurrentScope,
}: {
  project: Project
  busy: boolean
  status: string
  settings: AppSettings | null
  scope: QuickTaskSessionScope
  initialRun: Run | null
  onBack: () => void
  onStartNextTask: () => void
  onUploadFile: (file: File, kind: string, accept: () => boolean) => Promise<Artifact | null>
  onStartQuickTask: (payload: StartQuickPayload) => Promise<Run | null>
  onRefreshProject: (scope: QuickTaskSessionScope) => Promise<Project | null>
  onContinueTask: (group: QuickTaskGroup) => void
  onViewResult: (run: Run | null) => void
  isCurrentScope: (scope: QuickTaskSessionScope) => boolean
}) {
  const initialInputArtifactId = String(initialRun?.metadata?.input_artifact_id || '')
  const initialInputArtifact = (project.artifacts || []).find((artifact) => artifact.id === initialInputArtifactId) || null
  const initialReferenceIds = Array.isArray(initialRun?.metadata?.reference_artifact_ids)
    ? initialRun.metadata.reference_artifact_ids.map(String)
    : []
  const [quickStep, setQuickStep] = useState(initialRun ? 3 : 1)
  const [inputArtifact, setInputArtifact] = useState<Artifact | null>(initialInputArtifact)
  const [referenceArtifacts, setReferenceArtifacts] = useState<Artifact[]>(
    (project.artifacts || []).filter((artifact) => initialReferenceIds.includes(artifact.id)),
  )
  const [targets, setTargets] = useState<TranslationTargets | null>(null)
  const [objective, setObjective] = useState<QuickObjective>(initialRun?.kind === 'qa' ? 'qa' : 'translate')
  const [language, setLanguage] = useState<LanguageCode>(normalizeLanguageCode(initialRun?.language) || 'en')
  const [readiness, setReadiness] = useState<TranslationReadiness | null>(null)
  const [startedRun, setStartedRun] = useState<Run | null>(initialRun)
  const [inputMode, setInputMode] = useState<'paste' | 'upload'>('paste')
  const [pastedText, setPastedText] = useState('')
  const [maxQuickStep, setMaxQuickStep] = useState(initialRun ? 3 : 1)
  const [localStatus, setLocalStatus] = useState('')
  const [deliveryBusy, setDeliveryBusy] = useState(false)
  const [deliveryError, setDeliveryError] = useState('')
  const [serverDeliveryFiles, setServerDeliveryFiles] = useState<DeliveryFile[]>([])
  const [deliveryFiles, setDeliveryFiles] = useState<DeliveryFile[]>([])
  const [deliveryText, setDeliveryText] = useState('')
  const [previewFiles, setPreviewFiles] = useState<DeliveryFile[]>([])
  const [previewTitle, setPreviewTitle] = useState('')
  const [previewError, setPreviewError] = useState('')
  const accept = useCallback(() => isCurrentScope(scope), [isCurrentScope, scope.projectId, scope.taskId, scope.generation])

  useEffect(() => {
    if (!inputArtifact?.id) {
      setReadiness(null)
      return
    }
    const batchSize = effectiveBatchSize(settings)
    let canceled = false
    api<TranslationReadiness>(`/api/projects/${scope.projectId}/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      .then((result) => {
        if (canceled || !accept()) return
        setReadiness(result)
        if (canSkipModelTranslation(result)) setObjective('qa')
      })
      .catch(() => {
        if (!canceled && accept()) setReadiness(null)
      })
    return () => { canceled = true }
  }, [inputArtifact?.id, language, settings?.batch_size, scope.projectId, scope.taskId, scope.generation, accept])

  async function uploadInput(file: File) {
    const artifact = await onUploadFile(file, 'quick_input', accept)
    if (!artifact || !accept()) return
    setInputArtifact(artifact)
    try {
      const inspected = await api<TranslationTargets>(`/api/projects/${scope.projectId}/artifacts/${artifact.id}/translation-targets`)
      if (!accept()) return
      const normalized = {
        ...inspected,
        detected_languages: normalizeLanguageArray(inspected.detected_languages),
        suggested_language: normalizeLanguageCode(inspected.suggested_language),
      }
      setTargets(normalized)
      const suggested = normalized.suggested_language || normalized.detected_languages[0] || 'en'
      setLanguage(suggested)
      setMaxQuickStep((current) => Math.max(current, 2))
      setQuickStep(2)
    } catch {
      if (accept()) setLocalStatus('语言识别失败，请重新选择目标语言。')
    }
  }

  async function submitPastedText() {
    const text = pastedText.trim()
    if (!text) return
    const file = new File([pastedText], `inline-quick-${Date.now()}.txt`, { type: 'text/plain' })
    await uploadInput(file)
  }

  async function uploadReference(file: File) {
    const artifact = await onUploadFile(file, 'quick_reference', accept)
    if (!artifact || !accept()) return
    setReferenceArtifacts((items) => uniqueArtifactsByContent([artifact, ...items]))
  }

  const startingRef = useRef(false)
  async function start() {
    if (!inputArtifact || startingRef.current || !accept()) return
    startingRef.current = true
    setDeliveryError('')
    setDeliveryFiles([])
    setServerDeliveryFiles([])
    setLocalStatus('')
    try {
      const run = await onStartQuickTask({ inputArtifact, referenceArtifacts, objective, language, taskId: scope.taskId, accept })
      if (run && accept() && quickTaskIdOfRun(run) === scope.taskId) setStartedRun(run)
    } finally {
      startingRef.current = false
    }
  }

  useEffect(() => {
    if (!startedRun?.id || ['passed', 'failed', 'needs_input', 'canceled'].includes(startedRun.status)) return
    let canceled = false
    const timer = window.setInterval(async () => {
      try {
        const updated = await api<Run>(`/api/runs/${startedRun.id}`)
        if (canceled || !accept() || quickTaskIdOfRun(updated) !== scope.taskId) return
        setStartedRun(updated)
        if (!['queued', 'running'].includes(updated.status)) void onRefreshProject(scope)
      } catch {
        if (!canceled && accept()) setLocalStatus('任务状态刷新失败，稍后会继续重试。')
      }
    }, 1500)
    return () => {
      canceled = true
      window.clearInterval(timer)
    }
  }, [startedRun?.id, startedRun?.status, scope.projectId, scope.taskId, scope.generation, accept, onRefreshProject])

  const readBackDelivery = useCallback(async (files: DeliveryFile[]) => {
    let textResult = ''
    for (const file of files) {
      if (!file.download_url) throw new Error('交付文件缺少下载地址')
      const response = await fetch(file.download_url)
      if (!response.ok) throw new Error(`交付文件读回失败（${response.status}）`)
      const filename = String(file.filename || file.path || '').toLowerCase()
      if (/\.(txt|md|markdown)$/.test(filename)) {
        const text = await response.text()
        if (!text.trim()) throw new Error('交付文本读回为空')
        if (!textResult) textResult = text
      } else {
        const body = await response.arrayBuffer()
        if (!body.byteLength) throw new Error('交付文件读回为空')
      }
      if (!accept()) return false
    }
    if (!accept()) return false
    setDeliveryText(textResult)
    setDeliveryFiles(files)
    setDeliveryError('')
    setLocalStatus(`交付已生成并读回：${files.length} 个文件`)
    await onRefreshProject(scope)
    return true
  }, [accept, onRefreshProject, scope.projectId, scope.taskId, scope.generation])

  const deliveryPostingRef = useRef(false)
  const generateDelivery = useCallback(async () => {
    if (!startedRun?.id || startedRun.status !== 'passed' || deliveryPostingRef.current || !accept()) return
    deliveryPostingRef.current = true
    setDeliveryBusy(true)
    setDeliveryError('')
    let serverReady = serverDeliveryFiles.length > 0
    try {
      let files = serverDeliveryFiles
      if (!files.length) {
        const result = await api<{
          files: DeliveryFile[]
          deliverable?: Pick<DeliverableTask, 'run_id' | 'translation_task_id'>
        }>(`/api/projects/${scope.projectId}/delivery-package?run_id=${encodeURIComponent(startedRun.id)}`, { method: 'POST' })
        if (!accept()) return
        const responseRunId = String(result.deliverable?.run_id || '')
        const responseTaskId = String(result.deliverable?.translation_task_id || '')
        if (
          (responseRunId && responseRunId !== startedRun.id)
          || (responseTaskId && responseTaskId !== scope.taskId)
        ) {
          throw new Error('交付响应与当前快速任务不匹配，请重试。')
        }
        files = result.files || []
        if (!files.length || files.some((file) => !file.download_url)) throw new Error('交付未返回可下载文件')
        setServerDeliveryFiles(files)
        serverReady = true
      }
      await readBackDelivery(files)
    } catch (error) {
      if (accept()) {
        setDeliveryError(String(error).replace(/^Error:\s*/, ''))
        setLocalStatus(serverReady ? '服务端交付已生成，但浏览器读回失败；请重试读取。' : '交付未完成，请在当前任务中重试。')
      }
    } finally {
      deliveryPostingRef.current = false
      if (accept()) setDeliveryBusy(false)
    }
  }, [startedRun?.id, startedRun?.status, serverDeliveryFiles, scope.projectId, scope.taskId, scope.generation, accept, readBackDelivery])

  const attemptedDeliveryRunRef = useRef('')
  useEffect(() => {
    if (!startedRun?.id || startedRun.status !== 'passed' || deliveryFiles.length) return
    if (attemptedDeliveryRunRef.current === startedRun.id) return
    attemptedDeliveryRunRef.current = startedRun.id
    void generateDelivery()
  }, [startedRun?.id, startedRun?.status, deliveryFiles.length, generateDelivery])

  async function stopRun() {
    if (!startedRun || !['queued', 'running'].includes(startedRun.status) || !accept()) return
    setLocalStatus('正在停止快速任务...')
    const endpoint = startedRun.kind === 'qa' ? 'qa' : 'translate'
    try {
      const stopped = await api<Run>(`/api/runs/${startedRun.id}/${endpoint}/cancel`, { method: 'POST' })
      if (!accept()) return
      setStartedRun(stopped)
      setLocalStatus('快速任务已停止，可返回项目后开始新任务。')
      await onRefreshProject(scope)
    } catch (error) {
      if (accept()) setLocalStatus(`停止失败：${String(error).replace(/^Error:\s*/, '')}`)
    }
  }

  async function previewDelivery(group: QuickTaskGroup) {
    setPreviewFiles([])
    setPreviewError('')
    setPreviewTitle(`${quickTaskName(group.latestRun)} · ${languageSpec(normalizeLanguageCode(group.latestRun.language) || 'en').short}`)
    try {
      const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${scope.projectId}/deliverables`)
      if (!accept()) return
      const runIds = new Set(group.runs.map((run) => run.id))
      const matched = (result.deliverables || []).filter((item) => runIds.has(item.run_id))
      const files = matched.flatMap(deliverableFiles)
      setPreviewFiles(files)
      if (!files.length) setPreviewError('该历史任务暂无可下载交付文件。')
    } catch (error) {
      if (accept()) setPreviewError(`历史交付加载失败：${String(error).replace(/^Error:\s*/, '')}`)
    }
  }

  const detected = normalizeLanguageArray(targets?.detected_languages)
  const quickGroups = useMemo(() => groupQuickTasks(project.runs || []), [project.runs])
  const lang = languageSpec(language)
  const readySummary = readiness
    ? `${readiness.source_rows} 行源文 / 已译 ${readiness.translated_rows} / 空译文 ${readiness.empty_target_rows} / 预计 ${readiness.estimated_batches || '-'} 批`
    : '上传后自动检查'
  const apiConfigurationReminder = objective === 'translate' ? aiProviderConfigurationReminder(settings) : ''
  const startedRunActive = Boolean(startedRun && ['queued', 'running'].includes(startedRun.status))
  const runBlocksRestart = Boolean(startedRun && (
    ['passed', 'canceled'].includes(startedRun.status)
    || ['delivered', 'canceled', 'abandoned', 'closed'].includes(String(startedRun.metadata?.translation_task_state || ''))
  ))
  const canStart = Boolean(inputArtifact && !busy && !startedRunActive && !runBlocksRestart && !deliveryBusy)
  const resumableCurrentRun = Boolean(
    startedRun
    && quickTaskIdOfRun(startedRun) === scope.taskId
    && isTranslationRunResumable(startedRun),
  )
  const launchLabel = objective === 'qa'
    ? `开始 ${lang.short} 校对`
    : resumableCurrentRun
      ? `继续 ${lang.short} 翻译`
      : `开始 ${lang.short} 翻译`

  return (
    <>
      <span className="sr-only" data-testid="quick-task-id" data-task-id={scope.taskId}>{scope.taskId}</span>
      <div className="proj-head">
        <div className="page-title-lockup">
          <span className="page-title-icon"><Zap size={20} aria-hidden="true" /></span>
          <div>
            <h2>快速任务</h2>
            <div className="desc">三步启动翻译或校对；项目提示词、术语库和译文归档自动带入，上传参考只对本次任务生效。</div>
          </div>
        </div>
        <button className="btn btn-ghost" onClick={onBack}><ArrowLeft size={16} aria-hidden="true" />返回项目概览</button>
      </div>
      <div className="quick-steps">
        {['投入内容', '投入参考', '目标并启动'].map((title, index) => (
          <button
            key={title}
            className={`quick-step ${quickStep === index + 1 ? 'active' : quickStep > index + 1 ? 'done' : ''}`}
            disabled={index + 1 > maxQuickStep}
            onClick={() => setQuickStep(index + 1)}
          >
            <span>{index + 1}</span>{title}
          </button>
        ))}
      </div>
      <ActionStatus status={localStatus || status} busy={busy || deliveryBusy} />
      <div className="quick-task-card">
        {quickStep === 1 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 1</span>投入要处理的内容</div>
            <div className="panel-desc">可直接粘贴短文本，也可上传语言表格或 TXT。系统只做本次任务输入，不写入长期语言表资产。</div>
            <div className="segmented-control quick-input-mode">
              <button data-testid="quick-mode-paste" className={inputMode === 'paste' ? 'active' : ''} onClick={() => setInputMode('paste')}>粘贴文本</button>
              <button data-testid="quick-mode-upload" className={inputMode === 'upload' ? 'active' : ''} onClick={() => setInputMode('upload')}>上传文件</button>
            </div>
            {inputMode === 'paste' ? (
              <QuickTextInput value={pastedText} onChange={setPastedText} onSubmit={submitPastedText} disabled={busy} artifact={inputArtifact} />
            ) : (
              <div className="upload-row">
                <FileBox label="上传待翻译 / 待校对文件（XLSX/TXT）" onFile={uploadInput} testId="quick-input-upload" />
                {inputArtifact ? <ArtifactNote artifact={inputArtifact} /> : null}
              </div>
            )}
          </>
        ) : null}
        {quickStep === 2 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 2</span>投入可选参考</div>
            <div className="panel-desc">默认已经使用项目提示词、项目术语和译文归档；这里上传的术语表、风格说明或参考素材只作为本次任务的临时约束。</div>
            <div className="quick-reference-row">
              <FileBox label="上传本次参考（可选）" onFile={uploadReference} testId="quick-reference-upload" />
              <div className="quick-reference-summary">
                <strong>已上传 {referenceArtifacts.length} 个参考</strong>
                <span>不会写入项目资产库；启动时会生成 reference snapshot。</span>
                {referenceArtifacts.length ? <div className="row-actions wrap">{referenceArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}</div> : null}
              </div>
            </div>
            <div className="actions inline-actions">
              <button className="btn btn-ghost" onClick={() => setQuickStep(1)}>← 上一步</button>
              <button className="btn btn-primary" data-testid="quick-reference-next" onClick={() => { setMaxQuickStep(3); setQuickStep(3) }}>下一步：选择目标</button>
            </div>
          </>
        ) : null}
        {quickStep === 3 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 3</span>选择目标并启动</div>
            <div className="panel-desc">语言从输入表头自动识别；TXT 识别不到时手动选择。质量门槛沿用正式翻译/QA 流程。</div>
            <div className="quick-launch-grid">
              <div className="quick-block">
                <label>任务目标</label>
                <div className="segmented-control">
                  <button data-testid="quick-objective-translate" className={objective === 'translate' ? 'active' : ''} onClick={() => setObjective('translate')}>翻译</button>
                  <button data-testid="quick-objective-qa" className={objective === 'qa' ? 'active' : ''} onClick={() => setObjective('qa')}>校对</button>
                </div>
              </div>
              <label className="quick-block">
                <span>目标语言</span>
                <select value={language} onChange={(event) => setLanguage(normalizeLanguageCode(event.target.value) || 'en')}>
                  {supportedLanguages.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                </select>
                <em>{detected.length ? `已识别：${detected.map((item) => languageSpec(item).short).join(' / ')}` : '未识别语言，可手动选择'}</em>
              </label>
              <div className="quick-block">
                <strong>输入检查</strong>
                <span>{inputArtifact ? artifactPickerLabel(inputArtifact) : '未上传'}</span>
                <em>{readySummary}</em>
              </div>
            </div>
            {readiness && canSkipModelTranslation(readiness) ? <div className="warn-line">这份表已有可校对译文，系统已建议切换为校对。</div> : null}
            {apiConfigurationReminder ? <div className="warn-line">需要先配置 API：{apiConfigurationReminder}</div> : null}
            <div className="row-actions wrap">
              <button className="btn btn-ghost" onClick={() => setQuickStep(2)}>← 上一步</button>
              <button className="btn btn-primary" data-testid="quick-task-start" disabled={!canStart} onClick={start}>{launchLabel}</button>
              {startedRunActive ? <button className="btn btn-ghost" data-testid="quick-task-stop" onClick={stopRun}><Square size={14} aria-hidden="true" />停止任务</button> : null}
              <button className="btn btn-ghost" disabled={!startedRun} onClick={() => onViewResult(startedRun)}>查看详情</button>
            </div>
            {startedRun ? <div className="scan-explain"><strong>{quickTaskName(startedRun)} 已创建</strong><span>{languageSpec(normalizeLanguageCode(startedRun.language) || language).short} · {quickRunStatusLabel(startedRun)} · {startedRun.id}</span></div> : null}
            {deliveryError ? (
              <div className="warn-line quick-delivery-error" data-testid="quick-delivery-error">
                <span>{deliveryError}</span>
                <button className="btn btn-ghost" data-testid="quick-delivery-retry" disabled={deliveryBusy} onClick={() => { void generateDelivery() }}>{serverDeliveryFiles.length ? '重试读取交付' : '重试生成交付'}</button>
              </div>
            ) : null}
            {deliveryFiles.length ? (
              <QuickDeliveryResult files={deliveryFiles} text={deliveryText} onBack={onBack} onStartNext={onStartNextTask} />
            ) : null}
          </>
        ) : null}
      </div>
      {quickGroups.length ? (
        <div className="card tight quick-history-card">
          <div className="card-title"><div className="left">快速任务历史</div></div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>类型</th><th>语言</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
              <tbody>
                {quickGroups.map((group) => (
                  <tr key={group.id}>
                    <td>{quickTaskName(group.latestRun)}{group.legacy ? <small className="muted-inline"> · 历史任务</small> : null}</td>
                    <td>{languageSpec(normalizeLanguageCode(group.latestRun.language) || 'en').short}</td>
                    <td>{quickTaskGroupStatus(group)}</td>
                    <td>{new Date(group.latestRun.created_at).toLocaleString()}</td>
                    <td>
                      <div className="row-actions wrap">
                        {!group.legacy && !group.terminal ? <button className="btn btn-ghost" onClick={() => onContinueTask(group)}>继续</button> : null}
                        {group.state === 'delivered' ? <button className="btn btn-ghost" onClick={() => { void previewDelivery(group) }}>查看交付</button> : null}
                        {group.legacy || (group.terminal && group.state !== 'delivered') ? <button className="btn btn-ghost" onClick={() => onViewResult(group.latestRun)}>查看详情</button> : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {previewTitle ? (
            <div className="quick-history-preview">
              <strong>{previewTitle}</strong>
              {previewError ? <span className="warn-line">{previewError}</span> : null}
              {previewFiles.length ? <DeliveryLinks files={previewFiles} /> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  )
}

function QuickTextInput({
  value,
  onChange,
  onSubmit,
  disabled,
  artifact,
}: {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled: boolean
  artifact: Artifact | null
}) {
  const lineCount = value.split(/\r?\n/).filter((line) => line.trim()).length
  return (
    <div className="quick-text-input-block">
      <textarea data-testid="quick-text-input" className="quick-text-input" value={value} onChange={(event) => onChange(event.target.value)} placeholder="粘贴要翻译的正文。每个非空行会作为一条翻译输入。" />
      <div className="quick-text-meta">
        <span>{lineCount} 个非空行</span>
        {artifact ? <ArtifactNote artifact={artifact} compact /> : null}
      </div>
      <div className="actions inline-actions">
        <button className="btn btn-primary" data-testid="quick-text-next" disabled={disabled || !value.trim()} onClick={onSubmit}>下一步：投入参考</button>
      </div>
    </div>
  )
}

function QuickDeliveryResult({ files, text, onBack, onStartNext }: { files: DeliveryFile[]; text: string; onBack: () => void; onStartNext: () => void }) {
  const [copyStatus, setCopyStatus] = useState('')
  async function copyText() {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopyStatus('已复制')
    } catch {
      setCopyStatus('复制失败，请手动选中文本')
    }
  }
  return (
    <div className="quick-result-panel quick-delivery-result" data-testid="quick-delivery-result">
      <div className="card-title"><div className="left"><Check size={16} aria-hidden="true" />交付已完成</div><span>已生成 {files.length} 个文件</span></div>
      {text ? <pre data-testid="quick-text-result">{text}</pre> : null}
      <DeliveryLinks files={files} />
      <div className="row-actions wrap quick-delivery-footer">
        {text ? <button className="btn btn-ghost" data-testid="quick-result-copy" onClick={copyText}>复制正文</button> : null}
        <button className="btn btn-ghost" onClick={onBack}>返回项目</button>
        <button className="btn btn-primary" data-testid="quick-start-next-task" onClick={onStartNext}>开始下一快速任务</button>
        {copyStatus ? <span className="muted-inline">{copyStatus}</span> : null}
      </div>
    </div>
  )
}

function DeliveryLinks({ files }: { files: DeliveryFile[] }) {
  return (
    <div className="row-actions wrap quick-delivery-files">
      {files.map((file, index) => (
        <a key={`${file.kind}:${file.filename}:${index}`} className="btn btn-ghost" data-testid={index === 0 ? 'quick-result-download' : undefined} href={file.download_url || '#'}>
          <Download size={14} aria-hidden="true" />{file.filename || `交付文件 ${index + 1}`}
        </a>
      ))}
    </div>
  )
}

function deliverableFiles(deliverable: DeliverableTask): DeliveryFile[] {
  const files = deliverable.files || {}
  return [files.final, files.changes, files.package, files.qa_summary, ...(files.outputs || [])]
    .filter((file): file is DeliveryFile => Boolean(file?.download_url))
}

function quickTaskGroupStatus(group: QuickTaskGroup): string {
  if (group.state === 'delivered') return '已交付'
  if (group.state === 'canceled') return '已取消'
  if (group.state === 'abandoned') return '已放弃'
  if (group.state === 'closed') return '已关闭'
  return quickRunStatusLabel(group.activeRun || group.latestRun)
}

function quickRunStatusLabel(run: Run): string {
  const quality = run.metadata?.quality as { passed?: boolean } | undefined
  if (run.kind === 'translation' && run.status === 'failed' && quality?.passed === false) return '需校对'
  if (run.status === 'queued') return '排队中'
  if (run.status === 'running') return '处理中'
  if (run.status === 'needs_input') return '可继续'
  if (run.status === 'passed') return '已完成'
  if (run.status === 'failed') return '失败'
  if (run.status === 'canceled') return '已取消'
  return runStatusLabel(run.status)
}
