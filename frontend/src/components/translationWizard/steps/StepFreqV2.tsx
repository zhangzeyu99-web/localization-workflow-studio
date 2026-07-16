import { translationInputMode } from '../../../domain/translationFlow'
import { type LanguageCode } from '../../../languages'
import { GlossaryCandidateReview } from '../../glossary/GlossaryCandidateReview'
import type { Artifact, GlossaryBatch, GlossaryCandidate, Project, Run, TranslationReadiness } from '../../../types'

export function glossaryReviewState(
  latestRun: Run | null,
  glossaryBatches: GlossaryBatch[],
  glossaryCandidates: GlossaryCandidate[]
) {
  const activeBatch = glossaryBatches[0] || null
  const pendingCount = glossaryCandidates.filter((candidate) => candidate.status === 'pending').length
  const acceptedCount = activeBatch?.counts?.accepted ?? glossaryCandidates.filter((candidate) => candidate.status === 'accepted').length
  const rejectedCount = activeBatch?.counts?.rejected ?? glossaryCandidates.filter((candidate) => candidate.status === 'rejected').length
  const extractionActive = latestRun?.kind === 'glossary' && ['queued', 'running'].includes(latestRun.status)
  const hasBackfill = latestRun?.kind === 'glossary' && Boolean(latestRun.metadata?.glossary_backfill)
  return {
    extractionActive,
    showCandidateReview: Boolean(hasBackfill || (activeBatch && (pendingCount || acceptedCount || rejectedCount))),
    blockAdvance: extractionActive || pendingCount > 0
  }
}

export function StepFreqV2({
  onGlossaryExtract,
  onFreq,
  sourceArtifact,
  translationReadiness,
  latestRun,
  glossaryBatches,
  glossaryCandidates,
  busy,
  status,
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
  latestRun: Run | null
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  busy: boolean
  status: string
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<boolean | void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  selectedLanguage: LanguageCode
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
}) {
  const activeBatch = glossaryBatches[0] || null
  const reviewState = glossaryReviewState(latestRun, glossaryBatches, glossaryCandidates)
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id ? translationReadiness : null
  const inputMode = translationInputMode(readiness)
  const blocked = !sourceArtifact || inputMode === 'ready_for_qa' || inputMode === 'invalid'
  return (
    <>
      <div className="panel-title"><span className="badge">步骤 5/9</span>术语候选</div>
      <div className="panel-desc">扫描并确认术语候选。</div>
      {inputMode === 'ready_for_qa' ? (
        <div className="translation-readiness-box ready">
          <div className="readiness-head">
            <strong>无需扫描</strong>
            <span>这份表可直接校对</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button>
        </div>
      ) : inputMode === 'invalid' || !sourceArtifact ? (
        <div className="translation-readiness-box todo">
          <div className="readiness-head">
            <strong>缺少待翻译语言表</strong>
            <span>{inputMode === 'invalid' ? '文件结构需要修正' : '请先上传语言表'}</span>
          </div>
          <button className="btn btn-primary btn-sm" data-testid="term-goto-source" onClick={() => setStep(4)}>返回判定输入</button>
        </div>
      ) : null}
      <div className="row-actions action-card">
        <span className="asset-meta">语言表：{sourceArtifact?.label || '未选择'}</span>
        <button className="btn btn-primary" disabled={blocked || busy || reviewState.extractionActive} onClick={() => onGlossaryExtract(sourceArtifact)}>扫描候选</button>
      </div>
      {reviewState.extractionActive ? <div className="info-line compact">正在整理术语候选，请完成后再继续。</div> : null}
      <details className="manual-maintenance compact-maintenance">
        <summary>更多设置</summary>
        <div className="language-inline-select">
          <span>候选补译与扫描规则。</span>
          <button className="btn btn-ghost" onClick={onFreq}>查看扫描规则</button>
        </div>
      </details>
      {reviewState.showCandidateReview ? (
        <GlossaryCandidateReview
          batch={activeBatch}
          candidates={glossaryCandidates}
          language={selectedLanguage}
          busy={busy}
          status={status}
          onUpdateCandidate={onUpdateCandidate}
          onResolveCandidates={onResolveCandidates}
          onTranslateMissingCandidates={onTranslateMissingCandidates}
        />
      ) : null}
    </>
  )
}
