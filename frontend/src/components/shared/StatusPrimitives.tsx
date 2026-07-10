import { Archive, CheckCircle2, CircleDashed, FileCheck2, SearchCheck, ShieldAlert } from 'lucide-react'
import { archiveSourcePresentation, lineProofreadStage, referenceAuditSummary } from '../../domain/workflowPresentation'
import type { LineProofreadState, ReferenceAuditState } from '../../types'
import { LINE_PROOFREAD_LABEL } from '../../uiText'

export function ArchiveProvenanceBadge({ sourceType }: { sourceType?: string }) {
  const source = archiveSourcePresentation(sourceType)
  return (
    <span className={`provenance-badge ${source.tone}`} title={source.detail} data-testid={`archive-source-${sourceType || 'unknown'}`}>
      {source.tone === 'trusted' ? <CheckCircle2 size={13} aria-hidden="true" /> : source.tone === 'review' ? <ShieldAlert size={13} aria-hidden="true" /> : <Archive size={13} aria-hidden="true" />}
      {source.label}
    </span>
  )
}

export function ReferenceAuditPanel({ state }: { state?: ReferenceAuditState | null }) {
  const hitRows = Number(state?.reference_hit_rows || 0)
  const hits = Number(state?.reference_hits || 0)
  return (
    <section className="evidence-panel" data-testid="translation-reference-audit">
      <div className="evidence-panel-head">
        <SearchCheck size={17} aria-hidden="true" />
        <div>
          <strong>项目译文参考</strong>
          <span>{referenceAuditSummary(state)}</span>
        </div>
      </div>
      {state ? (
        <dl className="evidence-metrics">
          <div><dt>归档候选</dt><dd>{Number(state.archive_entries || 0)}</dd></div>
          <div><dt>命中原文</dt><dd>{hitRows}</dd></div>
          <div><dt>参考条目</dt><dd>{hits}</dd></div>
        </dl>
      ) : null}
    </section>
  )
}

export function LineProofreadTimeline({ state, enabled }: { state?: LineProofreadState | null; enabled?: boolean }) {
  const stage = lineProofreadStage(state)
  const steps = [
    { key: 'review', label: '逐句审校', done: stage !== 'idle' },
    { key: 'audit', label: '确定性审计', done: stage !== 'idle' },
    { key: 'apply', label: '安全写回', done: stage === 'applied' || (stage === 'reviewed' && Number(state?.suggested || 0) === 0) },
    { key: 'qa', label: '重跑 QA', done: stage === 'applied' }
  ]
  return (
    <section className={`proofread-timeline ${enabled || state ? 'enabled' : ''}`} data-testid="line-proofread-process">
      <div className="evidence-panel-head">
        <FileCheck2 size={17} aria-hidden="true" />
        <div>
          <strong>{LINE_PROOFREAD_LABEL}</strong>
          <span>{state ? `审校 ${state.reviewed_rows || 0} 行，采纳 ${state.applied || 0} 条，审计回退 ${state.rejected_by_audit || 0} 条。` : enabled ? '翻译完成后自动执行，并在安全写回后重跑机器 QA。' : '未启用'}</span>
        </div>
      </div>
      <ol>
        {steps.map((item) => (
          <li key={item.key} className={item.done ? 'done' : ''}>
            {item.done ? <CheckCircle2 size={15} aria-hidden="true" /> : <CircleDashed size={15} aria-hidden="true" />}
            <span>{item.label}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
