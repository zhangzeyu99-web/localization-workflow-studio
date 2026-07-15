import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Zap } from 'lucide-react'
import { api } from '../../apiClient'
import { artifactDownloadHref, artifactPickerLabel, newestArtifact, uniqueArtifactsByContent } from '../../domain/artifacts'
import { queueJobForTarget, queueJobStatusText } from '../../domain/jobQueues'
import { aiProviderConfigurationReminder } from '../../domain/providerSettings'
import { canSkipModelTranslation, effectiveBatchSize, isTranslationRunResumable, matchesTranslationRun } from '../../domain/translationFlow'
import { languageQuery, languageSpec, normalizeLanguageArray, normalizeLanguageCode, supportedLanguages, type LanguageCode } from '../../languages'
import { ActionStatus, ArtifactNote, FileBox } from '../shared/WorkflowPrimitives'
import { runStatusLabel } from '../../uiText'
import type { AppSettings, Artifact, JobQueues, Project, QuickObjective, Run, TranslationReadiness, TranslationTargets } from '../../types'

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
  const runs = quickTaskRuns(project).slice(0, 3)
  if (!runs.length) return null
  return (
    <div className="quick-recent">
      <div className="quick-recent-title">最近快速任务</div>
      {runs.map((run) => (
        <div key={run.id} className="quick-recent-item">
          <span>{quickTaskName(run)} · {languageSpec(normalizeLanguageCode(run.language) || 'en').short}</span>
          <em>{runStatusLabel(run.status)}</em>
        </div>
      ))}
    </div>
  )
}

export function QuickTaskWizard({
  project,
  busy,
  status,
  jobQueues,
  settings,
  latestRun,
  onBack,
  onUploadFile,
  onInspectTargets,
  onStartQuickTask,
  onViewResult
}: {
  project: Project
  busy: boolean
  status: string
  jobQueues: JobQueues
  settings: AppSettings | null
  latestRun: Run | null
  onBack: () => void
  onUploadFile: (file: File, kind: string) => Promise<Artifact | null>
  onInspectTargets: (artifactId: string) => Promise<TranslationTargets | null>
  onStartQuickTask: (payload: { inputArtifact: Artifact; referenceArtifacts: Artifact[]; objective: QuickObjective; language: LanguageCode }) => Promise<Run | null>
  onViewResult: (run: Run | null) => void
}) {
  const [quickStep, setQuickStep] = useState(1)
  const [inputArtifact, setInputArtifact] = useState<Artifact | null>(null)
  const [referenceArtifacts, setReferenceArtifacts] = useState<Artifact[]>([])
  const [targets, setTargets] = useState<TranslationTargets | null>(null)
  const [objective, setObjective] = useState<QuickObjective>('translate')
  const [language, setLanguage] = useState<LanguageCode>('en')
  const [readiness, setReadiness] = useState<TranslationReadiness | null>(null)
  const [startedRun, setStartedRun] = useState<Run | null>(null)
  const [inputMode, setInputMode] = useState<'paste' | 'upload'>('paste')
  const [pastedText, setPastedText] = useState('')
  const [maxQuickStep, setMaxQuickStep] = useState(1)

  useEffect(() => {
    if (!inputArtifact?.id) {
      setReadiness(null)
      return
    }
    const batchSize = effectiveBatchSize(settings)
    let canceled = false
    api<TranslationReadiness>(`/api/projects/${project.id}/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      .then((result) => {
        if (canceled) return
        setReadiness(result)
        if (canSkipModelTranslation(result)) setObjective('qa')
      })
      .catch(() => {
        if (!canceled) setReadiness(null)
      })
    return () => { canceled = true }
  }, [inputArtifact?.id, language, settings?.batch_size])

  async function uploadInput(file: File) {
    const artifact = await onUploadFile(file, 'quick_input')
    if (!artifact) return
    setInputArtifact(artifact)
    const inspected = await onInspectTargets(artifact.id)
    setTargets(inspected)
    const suggested = normalizeLanguageCode(inspected?.suggested_language) || inspected?.detected_languages?.[0] || 'en'
    setLanguage(suggested)
    setMaxQuickStep((current) => Math.max(current, 2))
    setQuickStep(2)
  }

  async function submitPastedText() {
    const text = pastedText.trim()
    if (!text) return
    const file = new File([pastedText], `inline-quick-${Date.now()}.txt`, { type: 'text/plain' })
    await uploadInput(file)
  }

  async function uploadReference(file: File) {
    const artifact = await onUploadFile(file, 'quick_reference')
    if (!artifact) return
    setReferenceArtifacts((items) => uniqueArtifactsByContent([artifact, ...items]))
  }

  const startingRef = useRef(false)
  async function start() {
    // Local re-entry lock: the global busy flag is set asynchronously inside
    // onStartQuickTask, leaving a window where a double-click would submit twice.
    if (!inputArtifact || startingRef.current) return
    startingRef.current = true
    try {
      const run = await onStartQuickTask({ inputArtifact, referenceArtifacts, objective, language })
      if (run) setStartedRun(run)
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
        if (!canceled) setStartedRun(updated)
      } catch {
        // Keep the last known run state; the global status already surfaces API errors.
      }
    }, 1500)
    return () => {
      canceled = true
      window.clearInterval(timer)
    }
  }, [startedRun?.id, startedRun?.status])

  const detected = normalizeLanguageArray(targets?.detected_languages)
  const quickRuns = quickTaskRuns(project).slice(0, 3)
  const lang = languageSpec(language)
  const readySummary = readiness
    ? `${readiness.source_rows} 行源文 / 已译 ${readiness.translated_rows} / 空译文 ${readiness.empty_target_rows} / 预计 ${readiness.estimated_batches || '-'} 批`
    : '上传后自动检查'
  const apiConfigurationReminder = objective === 'translate' ? aiProviderConfigurationReminder(settings) : ''
  const projectStartedRun = startedRun?.project_id === project.id ? startedRun : null
  const projectLatestQuickRun = latestRun?.project_id === project.id && latestRun.metadata?.task_origin === 'quick_task' ? latestRun : null
  const quickQueueTargetRun = projectStartedRun || projectLatestQuickRun
  const quickQueueJob = queueJobForTarget(jobQueues, quickQueueTargetRun?.id, project.id)
  // Background tasks no longer hold the global busy flag, so also guard on
  // the run this panel just started still being active.
  const startedRunActive = Boolean(quickQueueJob || (projectStartedRun && ['queued', 'running'].includes(projectStartedRun.status)))
  const canStart = Boolean(inputArtifact && !busy && !startedRunActive)
  const resumableQuickRun = inputArtifact ? quickTaskRuns(project).find((run) =>
    matchesTranslationRun(run, language, inputArtifact.id, 'quick_task')
    && isTranslationRunResumable(run)
  ) : null
  const launchLabel = objective === 'qa'
    ? `\u5f00\u59cb ${lang.short} \u6821\u5bf9`
    : resumableQuickRun
      ? `\u7ee7\u7eed ${lang.short} \u7ffb\u8bd1`
      : `\u5f00\u59cb ${lang.short} \u7ffb\u8bd1`
  const quickStatusLabel = (value: string) => {
    if (value === 'queued') return '\u6392\u961f\u4e2d'
    if (value === 'running') return '\u5904\u7406\u4e2d'
    if (value === 'needs_input') return '\u53ef\u7ee7\u7eed'
    if (value === 'passed') return '\u5df2\u5b8c\u6210'
    if (value === 'failed') return '\u5931\u8d25'
    if (value === 'canceled') return '\u5df2\u53d6\u6d88'
    return value
  }
  const quickRunStatusLabel = (run: Run) => {
    const quality = run.metadata?.quality as { passed?: boolean } | undefined
    if (run.kind === 'translation' && run.status === 'failed' && quality?.passed === false) return '\u9700\u6821\u5bf9'
    return quickStatusLabel(run.status)
  }
  const displayRun = quickTaskDisplayRun(projectStartedRun, projectLatestQuickRun)
  const effectiveStatus = queueJobStatusText(quickQueueJob) || status
  return (
    <>
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
      <ActionStatus status={effectiveStatus} busy={busy} />
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
              <QuickTextInput
                value={pastedText}
                onChange={setPastedText}
                onSubmit={submitPastedText}
                disabled={busy}
                artifact={inputArtifact}
              />
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
                {referenceArtifacts.length ? (
                  <div className="row-actions wrap">
                    {referenceArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
                  </div>
                ) : null}
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
            <div className="row-actions">
              <button className="btn btn-ghost" onClick={() => setQuickStep(2)}>← 上一步</button>
              <button className="btn btn-primary" data-testid="quick-task-start" disabled={!canStart} onClick={start}>{launchLabel}</button>
              <button className="btn btn-ghost" disabled={!displayRun} onClick={() => onViewResult(displayRun)}>查看结果</button>
            </div>
            {startedRun ? <div className="scan-explain"><strong>{quickTaskName(startedRun)} 已创建</strong><span>{languageSpec(normalizeLanguageCode(startedRun.language) || language).short} · {quickRunStatusLabel(startedRun)} · {startedRun.id}</span></div> : null}
            {displayRun ? <QuickTextResultPanel projectId={project.id} run={displayRun} onOpenDetail={() => onViewResult(displayRun)} /> : null}
          </>
        ) : null}
      </div>
      {quickRuns.length ? (
        <div className="card tight">
          <div className="card-title"><div className="left">最近快速任务</div></div>
          <table>
            <thead><tr><th>类型</th><th>语言</th><th>状态</th><th>创建时间</th></tr></thead>
            <tbody>
              {quickRuns.map((run) => (
                <tr key={run.id}><td>{quickTaskName(run)}</td><td>{languageSpec(normalizeLanguageCode(run.language) || 'en').short}</td><td>{quickRunStatusLabel(run)}</td><td>{new Date(run.created_at).toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
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
  artifact
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
      <textarea
        data-testid="quick-text-input"
        className="quick-text-input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="粘贴要翻译的正文。每个非空行会作为一条翻译输入。"
      />
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

function QuickTextResultPanel({ projectId, run, onOpenDetail }: { projectId: string; run: Run; onOpenDetail: () => void }) {
  const finalTextArtifact = newestArtifact(run.artifacts || [], ['final_text'])
  const [text, setText] = useState('')
  const [readFailed, setReadFailed] = useState(false)
  const [copyStatus, setCopyStatus] = useState('')
  const href = finalTextArtifact ? artifactDownloadHref(finalTextArtifact, projectId) : ''

  useEffect(() => {
    let canceled = false
    setText('')
    setReadFailed(false)
    if (!href) return
    fetch(href)
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status))
        return response.text()
      })
      .then((body) => {
        if (!canceled) setText(body)
      })
      .catch(() => {
        // Without this flag the panel shows "正在读取结果..." forever.
        if (!canceled) setReadFailed(true)
      })
    return () => { canceled = true }
  }, [href])

  async function copyText() {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopyStatus('已复制')
    } catch {
      setCopyStatus('复制失败，请手动选中文本')
    }
  }

  if (!finalTextArtifact && !['passed', 'failed'].includes(run.status)) {
    return <div className="scan-explain" data-testid="quick-text-result"><strong>结果生成中</strong><span>{runStatusLabel(run.status)}</span></div>
  }
  if (!finalTextArtifact) return null
  return (
    <div className="quick-result-panel" data-testid="quick-text-result">
      <div className="card-title">
        <div className="left">快速翻译结果</div>
        <span>{runStatusLabel(run.status)}</span>
      </div>
      <pre>{text || (readFailed ? '读取结果失败，请点击“下载 TXT”获取文件，或刷新页面重试。' : '正在读取结果...')}</pre>
      <div className="row-actions">
        <button className="btn btn-primary" data-testid="quick-result-copy" disabled={!text} onClick={copyText}>复制正文</button>
        <a className="btn btn-ghost" data-testid="quick-result-download" href={href}>下载 TXT</a>
        <button className="btn btn-ghost" onClick={onOpenDetail}>查看详情</button>
        {copyStatus ? <span className="muted-inline">{copyStatus}</span> : null}
      </div>
    </div>
  )
}
