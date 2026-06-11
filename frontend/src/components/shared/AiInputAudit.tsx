import React, { useEffect, useState } from 'react'
import { api } from '../../apiClient'

type AuditRecord = Record<string, unknown>

function asRecord(value: unknown): AuditRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as AuditRecord : {}
}

function asArray(value: unknown): AuditRecord[] {
  return Array.isArray(value) ? value.filter((item): item is AuditRecord => Boolean(item && typeof item === 'object' && !Array.isArray(item))) : []
}

function text(value: unknown): string {
  return String(value ?? '').trim()
}

function boolText(value: unknown): string {
  return value ? '?' : '?'
}

function renderProjectAudit(data: AuditRecord) {
  const analysis = asRecord(data.analysis)
  const summary = asRecord(analysis.summary)
  const materials = asArray(analysis.materials)
  return (
    <>
      <div className="audit-kpis">
        <span>?? {text(summary.parsed) || 0}/{text(summary.total) || materials.length}</span>
        <span>??? {text(summary.unsupported) || 0}</span>
        <span>?? {text(summary.warnings) || 0}</span>
      </div>
      <div className="audit-list">
        {materials.length ? materials.map((item, index) => (
          <div className="audit-item" key={`${text(item.artifact_id)}-${index}`}>
            <div className="audit-item-head">
              <strong>{text(item.filename) || text(item.label) || `?? ${index + 1}`}</strong>
              <span>{text(item.material_type) || 'unknown'} ? {text(item.status) || '???'}</span>
            </div>
            <div className="audit-meta-line">?? AI?{boolText(item.included_in_ai)} ? ?????{boolText(item.readable)}</div>
            {text(item.warning) || text(item.readable_reason) ? <div className="warn-line slim">{text(item.warning) || text(item.readable_reason)}</div> : null}
            {text(item.excerpt) ? <p>{text(item.excerpt)}</p> : <p className="muted">????? AI ??????</p>}
          </div>
        )) : <div className="muted">???????????????? AI ???</div>}
      </div>
    </>
  )
}

function renderTranslationAudit(data: AuditRecord) {
  const workpack = asRecord(data.workpack)
  const prompt = asRecord(data.prompt)
  const samples = asArray(workpack.samples)
  return (
    <>
      <div className="audit-kpis">
        <span>Workpack {text(workpack.rows) || 0} ?</span>
        <span>????? {text(workpack.term_hit_rows) || 0}</span>
        <span>?? {text(workpack.estimated_batches) || 0} ?</span>
      </div>
      <div className="audit-item">
        <div className="audit-item-head"><strong>?? Prompt ??</strong><span>{prompt.available ? '??? AI' : '???'}</span></div>
        <p>{text(prompt.preview) || '?? prompt ???'}</p>
      </div>
      <div className="audit-list compact">
        {samples.map((item, index) => (
          <div className="audit-item" key={`${text(item.id)}-${index}`}>
            <div className="audit-item-head"><strong>{text(item.id) || `? ${index + 1}`}</strong><span>term_hits {text(item.term_hits_count) || 0}</span></div>
            <p>{text(item.source)}</p>
          </div>
        ))}
      </div>
    </>
  )
}

function renderAnnouncementAudit(data: AuditRecord) {
  const languages = asArray(data.languages)
  const lookup = asRecord(data.lookup)
  return (
    <>
      <div className="audit-kpis">
        <span>?? {text(data.segments) || 0}</span>
        <span>?? {text(lookup.terms) || 0}</span>
        <span>???? {text(lookup.translations) || 0}</span>
      </div>
      {!Number(lookup.terms || 0) && !Number(lookup.translations || 0) ? <div className="warn-line slim">??????????????AI ?????? prompt ????????</div> : null}
      <div className="audit-list">
        {languages.length ? languages.map((item, index) => (
          <div className="audit-item" key={`${text(item.language)}-${index}`}>
            <div className="audit-item-head"><strong>{text(item.language).toUpperCase() || `?? ${index + 1}`}</strong><span>{text(item.workpack_rows) || 0} ? ? ???? {text(item.term_hits) || 0}</span></div>
            <p>{text(item.prompt_preview) || '?? prompt ???'}</p>
            {asArray(item.samples).slice(0, 2).map((sample, sampleIndex) => <p className="audit-sample" key={sampleIndex}>{text(sample.source)}</p>)}
          </div>
        )) : <div className="muted">??????????? AI ???</div>}
      </div>
    </>
  )
}

function renderAudit(data: AuditRecord) {
  if (data.analysis) return renderProjectAudit(data)
  if (data.workpack) return renderTranslationAudit(data)
  if (data.languages) return renderAnnouncementAudit(data)
  return <pre className="audit-json">{JSON.stringify(data, null, 2)}</pre>
}

export function AiInputAuditPanel({ endpoint, title, buttonLabel, disabled = false }: { endpoint: string; title: string; buttonLabel?: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [data, setData] = useState<AuditRecord | null>(null)

  useEffect(() => {
    setOpen(false)
    setData(null)
    setError('')
  }, [endpoint])

  async function toggle() {
    const nextOpen = !open
    setOpen(nextOpen)
    if (!nextOpen || data || disabled) return
    setLoading(true)
    setError('')
    try {
      setData(await api<AuditRecord>(endpoint))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ai-audit-panel">
      <button className="btn btn-ghost btn-sm" disabled={disabled || loading} onClick={toggle}>{loading ? '???...' : (buttonLabel || '?? AI ????')}</button>
      {open ? (
        <div className="ai-audit-body">
          <div className="audit-title">{title}</div>
          {error ? <div className="warn-line slim">{error}</div> : data ? renderAudit(data) : <div className="muted">??????????...</div>}
        </div>
      ) : null}
    </div>
  )
}
