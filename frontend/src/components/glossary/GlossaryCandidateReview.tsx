import { useEffect, useState } from 'react'
import { normalizeGlossaryNote } from '../../domain/projectAssets'
import { languageSpec, type LanguageCode } from '../../languages'
import type { GlossaryBatch, GlossaryCandidate } from '../../types'

type ResolveAction = 'accept' | 'reject'

export type GlossaryCandidateReviewProps = {
  batch: GlossaryBatch | null
  candidates: GlossaryCandidate[]
  language: LanguageCode
  busy: boolean
  status?: string
  canCurate?: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => boolean | void | Promise<boolean | void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: ResolveAction) => void | Promise<void>
  onTranslateMissingCandidates: (batchId: string) => void | Promise<void>
}

export function GlossaryCandidateReview({
  batch,
  candidates,
  language,
  busy,
  status = '',
  canCurate = true,
  onUpdateCandidate,
  onResolveCandidates,
  onTranslateMissingCandidates,
}: GlossaryCandidateReviewProps) {
  const [expanded, setExpanded] = useState(false)
  const pendingCandidates = candidates.filter((candidate) => candidate.status === 'pending')
  const needsTranslation = pendingCandidates.filter((candidate) => !candidate.target?.trim())
  const readyCandidates = pendingCandidates.filter((candidate) => candidate.target?.trim())
  const reviewPreview = expanded ? pendingCandidates : pendingCandidates.slice(0, 12)
  const accepted = batch?.counts?.accepted ?? candidates.filter((candidate) => candidate.status === 'accepted').length
  const rejected = batch?.counts?.rejected ?? candidates.filter((candidate) => candidate.status === 'rejected').length
  const lang = languageSpec(language)

  return (
    <section className="glossary-candidate-review" data-testid="glossary-candidate-review" aria-labelledby="glossary-candidate-review-title">
      <div className="scan-explain">
        <strong>本次扫描结果</strong>
        <span>待确认 {pendingCandidates.length} · 已加入 {accepted} · 已跳过 {rejected}</span>
      </div>
      <div className="confirm-panel">
        <div className="confirm-head">
          <h4 id="glossary-candidate-review-title">确认候选</h4>
          {canCurate ? <div className="confirm-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label="补译本批空候选"
              disabled={!batch || !needsTranslation.length || busy}
              onClick={() => batch && void onTranslateMissingCandidates(batch.id)}
            >
              补译空候选
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              aria-label="跳过本批全部待确认术语候选"
              disabled={!batch || !pendingCandidates.length || busy}
              onClick={() => batch && void onResolveCandidates(batch.id, pendingCandidates, 'reject')}
            >
              全部跳过
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              aria-label="加入本批全部可用术语候选"
              disabled={!batch || !readyCandidates.length || busy}
              onClick={() => batch && void onResolveCandidates(batch.id, readyCandidates, 'accept')}
            >
              确认可用候选
            </button>
          </div> : null}
        </div>
        <div role="status" aria-label="候选操作状态" aria-live="polite" className="archive-import-live">
          {status || `待确认 ${pendingCandidates.length} 条候选。`}
        </div>
        {reviewPreview.length ? (
          <div className="table-scroll">
            <table className="pending-term-table">
              <thead><tr><th>状态</th><th>ID</th><th>CN</th><th>{lang.targetHeader}</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
              <tbody>
                {reviewPreview.map((candidate) => (
                  <GlossaryCandidateReviewRow
                    key={candidate.id}
                    candidate={candidate}
                    batchId={batch?.id || ''}
                    busy={busy}
                    canCurate={canCurate}
                    onUpdateCandidate={onUpdateCandidate}
                    onResolveCandidates={onResolveCandidates}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-inline">暂无待确认候选。</div>
        )}
        {pendingCandidates.length > 12 ? (
          <div className="review-table-foot">
            <span>{expanded ? `共 ${pendingCandidates.length} 条` : `显示前 ${reviewPreview.length} 条`}</span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpanded((value) => !value)}>
              {expanded ? '收起' : `展开全部 ${pendingCandidates.length} 条`}
            </button>
          </div>
        ) : null}
      </div>
    </section>
  )
}

function GlossaryCandidateReviewRow({
  candidate,
  batchId,
  busy,
  canCurate,
  onUpdateCandidate,
  onResolveCandidates,
}: {
  candidate: GlossaryCandidate
  batchId: string
  busy: boolean
  canCurate: boolean
  onUpdateCandidate: GlossaryCandidateReviewProps['onUpdateCandidate']
  onResolveCandidates: GlossaryCandidateReviewProps['onResolveCandidates']
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: candidate.term_key || '',
    source: candidate.source || '',
    target: candidate.target || '',
    category: candidate.category || '',
    note: normalizeGlossaryNote(candidate.note),
  })

  useEffect(() => {
    setDraft({
      term_key: candidate.term_key || '',
      source: candidate.source || '',
      target: candidate.target || '',
      category: candidate.category || '',
      note: normalizeGlossaryNote(candidate.note),
    })
    setEditing(false)
  }, [candidate.id, candidate.term_key, candidate.source, candidate.target, candidate.category, candidate.note])

  async function save(confirmAfter: boolean) {
    const updated = await onUpdateCandidate(candidate, draft)
    if (updated === false) return
    setEditing(false)
    if (confirmAfter && draft.target.trim()) await onResolveCandidates(batchId, [candidate], 'accept')
  }

  function cell(key: keyof typeof draft) {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  const canAccept = Boolean(candidate.target?.trim())
  return (
    <tr data-testid={`glossary-candidate-${candidate.id}`}>
      <td><span className={`term-kind ${canAccept ? 'filled' : 'new'}`}>{canAccept ? '待审核' : '待补译'}</span></td>
      <td>{cell('term_key')}</td>
      <td>{cell('source')}</td>
      <td>{cell('target')}</td>
      <td>{cell('category')}</td>
      <td>{cell('note')}</td>
      <td>
        <div className="term-review-actions">
          {!canCurate ? null : editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save(false)}>保存</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId || !draft.target.trim()} onClick={() => void save(true)}>保存并加入</button>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(false)}>取消</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(true)}>编辑</button>
              <button
                type="button"
                className="btn btn-sm"
                aria-label={`加入候选“${candidate.source}”`}
                disabled={busy || !batchId || !canAccept}
                onClick={() => void onResolveCandidates(batchId, [candidate], 'accept')}
              >
                加入
              </button>
              <button
                type="button"
                className="btn btn-sm"
                aria-label={`跳过候选“${candidate.source}”`}
                disabled={busy || !batchId}
                onClick={() => void onResolveCandidates(batchId, [candidate], 'reject')}
              >
                跳过
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}
