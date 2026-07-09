import { matchesTranslationRun, translationInputMode, translationNextStep } from '../../domain/translationFlow'
import { type LanguageCode } from '../../languages'
import { ActionStatus } from '../shared/WorkflowPrimitives'
import type { ConfirmDialogOptions } from '../modals/ConfirmModal'
import type { AppSettings, Artifact, DeliverableTask, DeliveryFile, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, Project, ProjectHarness, QualityIssue, Run, TranslationReadiness } from '../../types'
import { StepIntro } from './steps/StepIntro'
import { StepAnalyze } from './steps/StepAnalyze'
import { StepTerm } from './steps/StepTerm'
import { StepSource } from './steps/StepSource'
import { StepFreqV2 } from './steps/StepFreqV2'
import { StepLang } from './steps/StepLang'
import { StepTranslate } from './steps/StepTranslate'
import { StepQA } from './steps/StepQA'
import { StepDone, wizardDeliveryFiles } from './steps/StepDone'

export const steps = ['项目资料', 'AI 分析', '术语表', '判定输入', '术语候选', '目标语言', 'AI 翻译', 'QA 校对', '交付']

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
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
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
