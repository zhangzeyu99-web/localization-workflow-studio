import { useEffect, useState } from 'react'
import { normalizeGlossaryNote } from '../../../domain/projectAssets'
import { translationInputMode, translationReadinessUserMessage } from '../../../domain/translationFlow'
import { languageSpec, type LanguageCode } from '../../../languages'
import type { Artifact, GlossaryBatch, GlossaryCandidate, Project, Run, TranslationReadiness } from '../../../types'

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
      <div className="panel-desc">输入是「判定输入」步骤判定为“待翻译”的语言表；项目资料只辅助生成 brief 和提示词。扫描结果先进入候选，人工确认后才加入项目术语库。</div>
      {inputMode === 'ready_for_qa' ? (
        <div className="translation-readiness-box ready">
          <div className="readiness-head">
            <strong>这份表已有完整译文</strong>
            <span>不需要扫描术语候选；请直接进入校对。通过后生成标准交付，未通过时可修复或带问题摘要交付。</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button>
        </div>
      ) : inputMode === 'invalid' || !sourceArtifact ? (
        <div className="translation-readiness-box todo">
          <div className="readiness-head">
            <strong>请先回「判定输入」步骤上传正确语言表</strong>
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
