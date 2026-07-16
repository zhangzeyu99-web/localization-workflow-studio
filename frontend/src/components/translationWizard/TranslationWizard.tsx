import { ArrowLeft, Check, ChevronLeft, ChevronRight, Languages } from 'lucide-react'
import { findVisibleTranslationRun, matchesTranslationRun, translationInputMode, translationNextStep } from '../../domain/translationFlow'
import { formalWorkflowQueueJob, queueJobStatusText } from '../../domain/jobQueues'
import { projectPromptForLanguage } from '../../domain/projectAssets'
import { type LanguageCode } from '../../languages'
import { ActionStatus } from '../shared/WorkflowPrimitives'
import type { ConfirmDialogOptions } from '../modals/ConfirmModal'
import type { AppSettings, Artifact, DeliverableTask, DeliveryFile, DeliveryLanguageResult, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, JobQueues, Project, ProjectHarness, QualityIssue, Run, TranslationReadiness } from '../../types'
import { StepIntro } from './steps/StepIntro'
import { StepAnalyze } from './steps/StepAnalyze'
import { StepTerm } from './steps/StepTerm'
import { StepSource } from './steps/StepSource'
import { glossaryReviewState, StepFreqV2 } from './steps/StepFreqV2'
import { StepLang } from './steps/StepLang'
import { StepTranslate } from './steps/StepTranslate'
import { StepQA } from './steps/StepQA'
import { findWizardDeliveryRun, StepDone, wizardDeliveryFiles } from './steps/StepDone'
import { PhaseStepper } from './PhaseStepper'

export const steps = ['项目资料', 'AI 分析', '术语表', '判定输入', '术语候选', '目标语言', 'AI 翻译', 'QA 校对', '交付']

export function Wizard(props: {
  project: Project
  translationTaskId: string
  step: number
  setStep: (step: number) => void
  intro: string
  setIntro: (value: string) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  qaArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  jobQueues: JobQueues
  translationReadiness: TranslationReadiness | null
  sourceInputNotice?: TranslationReadiness | null
  invalidSourceArtifactIds?: string[]
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  qualityIssues: QualityIssue[]
  deliverables: DeliverableTask[]
  generatedDeliveryRunId?: string
  generatedDeliveryFiles?: DeliveryFile[]
  generatedDeliveryMergedLanguages?: string[]
  generatedDeliverySkippedLanguages?: string[]
  generatedDeliveryLanguageResults?: DeliveryLanguageResult[]
  settings: AppSettings | null
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
  lineProofread: boolean
  setLineProofread: (value: boolean) => void
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
  onCancelTranslate: (run?: Run | null) => void
  onDirectQA: (artifact?: Artifact | null) => void
  onDirectQAQueue?: () => void
  onCancelQa?: (run?: Run | null) => void
  onSkipQAArchive: (artifact?: Artifact | null) => void
  allowSkipQAArchive?: boolean
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  onCreateDelivery: (runId: string) => Promise<DeliveryFile[] | null>
  onCreateMergedDelivery?: () => Promise<DeliveryFile[] | null> | void
  onFinishDelivery: () => void
  onStartNextTask: () => void
  onFreq: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<boolean | void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  busy: boolean
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
}) {
  const { project, step, setStep } = props
  const sourceReadiness = props.sourceArtifact && props.translationReadiness?.artifact_id === props.sourceArtifact.id ? props.translationReadiness : null
  const taskScope = { translationTaskId: props.translationTaskId, inputArtifactId: props.sourceArtifact?.id }
  const stepTranslationRun = props.latestRun && matchesTranslationRun(props.latestRun, props.selectedLanguage, props.sourceArtifact?.id, 'translation_run', props.translationTaskId)
    ? props.latestRun
    : findVisibleTranslationRun(project, props.selectedLanguage, props.sourceArtifact?.id, 'translation_run', props.translationTaskId)
  const selectedTranslationRuns = props.selectedLanguages.map((language) => findVisibleTranslationRun(project, language, props.sourceArtifact?.id, 'translation_run', props.translationTaskId))
  const multilingualMode = props.selectedLanguages.length > 1
  const stepTranslationActive = step === 7 && (multilingualMode
    ? selectedTranslationRuns.some((run) => run && ['queued', 'running'].includes(run.status))
    : Boolean(stepTranslationRun && ['queued', 'running'].includes(stepTranslationRun.status)))
  const stepDeliveryFiles = step === 9
    ? wizardDeliveryFiles(project, props.latestRun, props.deliverables, props.generatedDeliveryRunId, props.generatedDeliveryFiles, multilingualMode, props.sourceArtifact?.id, props.translationTaskId)
    : []
  const wizardDeliveryRun = findWizardDeliveryRun(project, props.latestRun, { ...taskScope, language: props.selectedLanguage })
  const currentTranslationDeliveryRun = stepTranslationRun ? findWizardDeliveryRun(project, stepTranslationRun, { ...taskScope, language: stepTranslationRun.language }) : null
  const multilingualCanEnterQa = multilingualMode && selectedTranslationRuns.every((run) => Boolean(
    run && ['passed', 'failed'].includes(run.status) && findWizardDeliveryRun(project, run, { ...taskScope, language: run.language })?.id === run.id
  ))
  const stepCanEnterQa = translationInputMode(sourceReadiness) === 'ready_for_qa'
    || (multilingualMode ? multilingualCanEnterQa : Boolean(stepTranslationRun && currentTranslationDeliveryRun?.id === stepTranslationRun.id))
  const stepCanGoDelivery = Boolean(wizardDeliveryRun)
  const maxNavigableStep = stepCanGoDelivery ? 9 : props.sourceArtifact || stepCanEnterQa ? 8 : 6
  const stepDeliveryReady = step !== 9 || stepDeliveryFiles.length > 0
  const stepSourceMissing = step === 4 && !props.sourceArtifact
  const glossaryReview = glossaryReviewState(props.latestRun, props.glossaryBatches, props.glossaryCandidates)
  const workflowStatus = queueJobStatusText(formalWorkflowQueueJob(props.jobQueues, project, props.translationTaskId, props.sourceArtifact?.id, props.latestRun)) || props.status
  const workflowProps = { ...props, status: workflowStatus }
  const skippedSteps = translationInputMode(sourceReadiness) === 'ready_for_qa' ? [5, 6, 7] : []
  const nextButtonLabels = ['去 AI 分析', '确认分析', '继续', '确认输入', '继续', '确认语言', '去 QA 校对', '去交付']
  const goNext = async () => {
    if (stepTranslationActive) return
    // H2 guard: these two steps used to be silently skippable, leaving later
    // steps in dead-end states. Ask before advancing without prerequisites.
    if (step === 2 && !projectPromptForLanguage(project, props.selectedLanguage)) {
      const proceed = await props.confirm('还没有运行 AI 分析，翻译提示词尚未生成，会影响翻译质量。确定跳过分析继续吗？', { title: '尚未完成 AI 分析', confirmLabel: '仍要继续', cancelLabel: '留在本步' })
      if (!proceed) return
    }
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
        <div className="page-title-lockup">
          <span className="page-title-icon"><Languages size={20} aria-hidden="true" /></span>
          <div>
            <h2>新翻译任务</h2>
            <div className="desc">{project.name}</div>
          </div>
        </div>
        <button className="btn btn-ghost" onClick={props.onBack}><ArrowLeft size={16} aria-hidden="true" />项目概览</button>
      </div>
      <PhaseStepper step={step} steps={steps} skippedSteps={skippedSteps} maxStep={maxNavigableStep} onStepChange={setStep} />
      {step !== 7 && (props.busy || workflowStatus !== '准备就绪') ? <ActionStatus status={workflowStatus} busy={props.busy} /> : null}
      <div className="step-panel active">
        {step === 1 ? <StepIntro {...workflowProps} /> : null}
        {step === 2 ? <StepAnalyze {...workflowProps} /> : null}
        {step === 3 ? <StepTerm {...workflowProps} /> : null}
        {step === 4 ? <StepSource {...workflowProps} /> : null}
        {step === 5 ? <StepFreqV2 {...workflowProps} /> : null}
        {step === 6 ? <StepLang {...workflowProps} /> : null}
        {step === 7 ? <StepTranslate {...workflowProps} /> : null}
        {step === 8 ? <StepQA {...workflowProps} showHistory={false} onRetryTranslations={props.onTranslateQueue || props.onTranslate} onRerunTranslation={() => props.setStep(7)} onGoDelivery={(run) => {
          props.setStep(9)
          if (multilingualMode && props.onCreateMergedDelivery) void props.onCreateMergedDelivery()
          else void props.onCreateDelivery(run.id)
        }} /> : null}
        {step === 9 ? <StepDone {...workflowProps} onRetryTranslations={props.onTranslateQueue || props.onTranslate} /> : null}
      </div>
      <div className="actions">
        <button className="btn btn-ghost btn-icon" aria-label="上一步" title="上一步" disabled={step === 1} onClick={() => setStep(step - 1)}><ChevronLeft size={16} aria-hidden="true" /></button>
        {step === 9 ? (
          <>
            <button className="btn btn-ghost" disabled={props.busy || !stepDeliveryReady} onClick={props.onFinishDelivery}><ArrowLeft size={16} aria-hidden="true" />返回项目</button>
            <button className="btn btn-primary" data-testid="start-next-translation-task" disabled={props.busy || !stepDeliveryReady} onClick={props.onStartNextTask} title={!stepDeliveryReady ? '请先生成交付文件，下载入口出现后再开始下一项。' : undefined}><Check size={16} aria-hidden="true" />开始下一翻译任务</button>
          </>
        ) : (
          <button
            className="btn btn-primary"
            disabled={props.busy || stepTranslationActive || stepSourceMissing || (step === 5 && glossaryReview.blockAdvance) || (step === 7 && !stepCanEnterQa) || (step === 8 && !stepCanGoDelivery)}
            onClick={goNext}
            title={stepSourceMissing ? '请先上传或选择待翻译语言表。' : undefined}
          >
            {stepTranslationActive ? '翻译中' : <>{nextButtonLabels[step - 1]}<ChevronRight size={16} aria-hidden="true" /></>}
          </button>
        )}
      </div>
    </>
  )
}
