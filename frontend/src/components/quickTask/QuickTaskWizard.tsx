import { useEffect, useState } from 'react'
import { api } from '../../apiClient'
import { artifactPickerLabel, uniqueArtifactsByContent } from '../../domain/artifacts'
import { canSkipModelTranslation, effectiveBatchSize } from '../../domain/translationFlow'
import { allLanguageOptions, languageQuery, languageSpec, normalizeLanguageArray, normalizeLanguageCode, type LanguageCode } from '../../languages'
import { ActionStatus, ArtifactNote, FileBox } from '../shared/WorkflowPrimitives'
import type { AppSettings, Artifact, Project, QuickObjective, Run, TranslationReadiness, TranslationTargets } from '../../types'

export function quickTaskRuns(project: Project): Run[] {
  return (project.runs || []).filter((run) => run.metadata?.task_origin === 'quick_task')
}

export function quickTaskName(run: Run): string {
  return run.kind === 'qa' ? '快速校对' : '快速翻译'
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
          <em>{run.status}</em>
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

  useEffect(() => {
    if (!inputArtifact?.id) {
      setReadiness(null)
      return
    }
    const batchSize = effectiveBatchSize(settings)
    let canceled = false
    api<TranslationReadiness>(`/api/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
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
    setQuickStep(2)
  }

  async function uploadReference(file: File) {
    const artifact = await onUploadFile(file, 'quick_reference')
    if (!artifact) return
    setReferenceArtifacts((items) => uniqueArtifactsByContent([artifact, ...items]))
  }

  async function start() {
    if (!inputArtifact) return
    const run = await onStartQuickTask({ inputArtifact, referenceArtifacts, objective, language })
    if (run) setStartedRun(run)
  }

  const detected = normalizeLanguageArray(targets?.detected_languages)
  const quickRuns = quickTaskRuns(project).slice(0, 3)
  const lang = languageSpec(language)
  const readySummary = readiness
    ? `${readiness.source_rows} 行源文 / 已译 ${readiness.translated_rows} / 空译文 ${readiness.empty_target_rows} / 预计 ${readiness.estimated_batches || '-'} 批`
    : '上传后自动检查'
  const canStart = Boolean(inputArtifact && !busy)
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>⚡ 快速任务 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">三步启动翻译或校对；项目提示词、术语库和 QA 归档自动带入，上传参考只对本次任务生效。</div>
        </div>
        <button className="btn btn-ghost" onClick={onBack}>← 返回项目概览</button>
      </div>
      <div className="quick-steps">
        {['投入内容', '投入参考', '目标并启动'].map((title, index) => (
          <button key={title} className={`quick-step ${quickStep === index + 1 ? 'active' : quickStep > index + 1 ? 'done' : ''}`} onClick={() => setQuickStep(index + 1)}>
            <span>{index + 1}</span>{title}
          </button>
        ))}
      </div>
      <ActionStatus status={status} busy={busy} />
      <div className="quick-task-card">
        {quickStep === 1 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 1</span>投入要处理的内容</div>
            <div className="panel-desc">v1 先支持语言表 workbook。上传后系统只做本次任务输入，不写入长期语言表资产。</div>
            <div className="upload-row">
              <FileBox label="上传待翻译 / 待校对 workbook（XLSX）" onFile={uploadInput} testId="quick-input-upload" />
              {inputArtifact ? <ArtifactNote artifact={inputArtifact} /> : null}
            </div>
          </>
        ) : null}
        {quickStep === 2 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 2</span>投入可选参考</div>
            <div className="panel-desc">默认已经使用项目提示词、项目术语和 QA 归档；这里上传的术语表、风格说明或参考素材只作为本次 run 的临时约束。</div>
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
              <button className="btn btn-primary" data-testid="quick-reference-next" onClick={() => setQuickStep(3)}>下一步：选择目标</button>
            </div>
          </>
        ) : null}
        {quickStep === 3 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 3</span>选择目标并启动</div>
            <div className="panel-desc">语言从输入表头自动识别；识别不到时手动选择。质量门槛沿用正式翻译/QA 流程。</div>
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
                  {allLanguageOptions.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
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
            {settings?.provider === 'mock' && objective === 'translate' && !project.name.startsWith('E2E ') ? <div className="warn-line">当前是 mock provider，真实项目会阻断翻译；请先配置 GPT / Claude API key。</div> : null}
            <div className="row-actions">
              <button className="btn btn-ghost" onClick={() => setQuickStep(2)}>← 上一步</button>
              <button className="btn btn-primary" data-testid="quick-task-start" disabled={!canStart} onClick={start}>{objective === 'qa' ? `开始 ${lang.short} 校对` : `开始 ${lang.short} 翻译`}</button>
              <button className="btn btn-ghost" disabled={!startedRun && !latestRun} onClick={() => onViewResult(startedRun || latestRun)}>查看结果</button>
            </div>
            {startedRun ? <div className="scan-explain"><strong>{quickTaskName(startedRun)} 已创建</strong><span>{languageSpec(normalizeLanguageCode(startedRun.language) || language).short} · {startedRun.status} · {startedRun.id}</span></div> : null}
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
                <tr key={run.id}><td>{quickTaskName(run)}</td><td>{languageSpec(normalizeLanguageCode(run.language) || 'en').short}</td><td>{run.status}</td><td>{new Date(run.created_at).toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  )
}
