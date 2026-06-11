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
  return value ? '是' : '否'
}

function renderProjectAudit(data: AuditRecord) {
  const analysis = asRecord(data.analysis)
  const summary = asRecord(analysis.summary)
  const materials = asArray(analysis.materials)
  return (
    <>
      <div className="audit-kpis">
        <span>已解析 {text(summary.parsed) || 0}/{text(summary.total) || materials.length}</span>
        <span>未支持 {text(summary.unsupported) || 0}</span>
        <span>警告 {text(summary.warnings) || 0}</span>
      </div>
      <div className="audit-list">
        {materials.length ? materials.map((item, index) => (
          <div className="audit-item" key={`${text(item.artifact_id)}-${index}`}>
            <div className="audit-item-head">
              <strong>{text(item.filename) || text(item.label) || `文件 ${index + 1}`}</strong>
              <span>{text(item.material_type) || 'unknown'} · {text(item.status) || '未知'}</span>
            </div>
            <div className="audit-meta-line">进入 AI：{boolText(item.included_in_ai)} · 文件可读：{boolText(item.readable)}</div>
            {text(item.warning) || text(item.readable_reason) ? <div className="warn-line slim">{text(item.warning) || text(item.readable_reason)}</div> : null}
            {text(item.excerpt) ? <p>{text(item.excerpt)}</p> : <p className="muted">暂无可展示的 AI 输入摘要</p>}
          </div>
        )) : <div className="muted">暂无资料读取明细或本次未生成 AI 输入</div>}
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
        <span>Workpack {text(workpack.rows) || 0} 行</span>
        <span>术语命中行 {text(workpack.term_hit_rows) || 0}</span>
        <span>预计 {text(workpack.estimated_batches) || 0} 批</span>
      </div>
      <div className="audit-item">
        <div className="audit-item-head"><strong>项目 Prompt 摘要</strong><span>{prompt.available ? '已进入 AI' : '未生成'}</span></div>
        <p>{text(prompt.preview) || '暂无 prompt 摘要'}</p>
      </div>
      <div className="audit-list compact">
        {samples.map((item, index) => (
          <div className="audit-item" key={`${text(item.id)}-${index}`}>
            <div className="audit-item-head"><strong>{text(item.id) || `行 ${index + 1}`}</strong><span>term_hits {text(item.term_hits_count) || 0}</span></div>
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
  const warnings = Array.isArray(data.warnings) ? data.warnings.map((item) => text(item)).filter(Boolean) : []
  if (text(data.status) === 'not_prepared') {
    return <div className="muted-empty-card">{text(data.message) || '尚未生成翻译准备包；请先完成上一步。'}</div>
  }
  return (
    <>
      {warnings.length ? <div className="warn-line slim">{warnings.join('?')}</div> : null}
      <div className="audit-kpis">
        <span>段落 {text(data.segments) || 0}</span>
        <span>术语 {text(lookup.terms) || 0}</span>
        <span>译文参考 {text(lookup.translations) || 0}</span>
      </div>
      {!Number(lookup.terms || 0) && !Number(lookup.translations || 0) ? <div className="warn-line slim">当前没有命中术语或译文参考；AI 将只基于项目 prompt 和公告正文翻译。</div> : null}
      <div className="audit-list">
        {languages.length ? languages.map((item, index) => (
          <div className="audit-item" key={`${text(item.language)}-${index}`}>
            <div className="audit-item-head"><strong>{text(item.language).toUpperCase() || `文件 ${index + 1}`}</strong><span>{text(item.workpack_rows) || 0} 行 · 术语命中 {text(item.term_hits) || 0}</span></div>
            <p>{text(item.prompt_preview) || '暂无 prompt 摘要'}</p>
            {asArray(item.samples).slice(0, 2).map((sample, sampleIndex) => <p className="audit-sample" key={sampleIndex}>{text(sample.source)}</p>)}
          </div>
        )) : <div className="muted">暂无公告翻译 AI 输入</div>}
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
      const message = err instanceof Error ? err.message : String(err)
      setError(message === 'Not Found' ? '当前还没有可查看的 AI 输入。请先完成上一步。' : message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="ai-audit-panel">
      <button className="btn btn-ghost btn-sm" disabled={disabled || loading} onClick={toggle}>{loading ? '读取中...' : (buttonLabel || '查看 AI 输入')}</button>
      {open ? (
        <div className="ai-audit-body">
          <div className="audit-title">{title}</div>
          {error ? <div className="warn-line slim">{error}</div> : data ? renderAudit(data) : <div className="muted">点击后读取本次 AI 输入摘要...</div>}
        </div>
      ) : null}
    </div>
  )
}
