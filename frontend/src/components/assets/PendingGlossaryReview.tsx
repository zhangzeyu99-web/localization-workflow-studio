import { useEffect, useRef, useState } from 'react'
import { ApiRequestError, api } from '../../apiClient'
import { errorText } from '../../appText'
import { languageSpec } from '../../languages'
import type { GlossaryTerm } from '../../types'

type PendingTerm = GlossaryTerm & { revision: string }
type PendingPage = { project_id: string; items: PendingTerm[]; total_rows: number; total_pages: number }
const PAGE_SIZE = 20

export function PendingGlossaryReview({ projectId, canCurate, refreshVersion, onEditingChange, onConfirmed }: {
  projectId: string
  canCurate: boolean
  refreshVersion: number
  onEditingChange: (editing: boolean) => void
  onConfirmed: () => void
}) {
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [reload, setReload] = useState(0)
  const [result, setResult] = useState<PendingPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)

  useEffect(() => { onEditingChange(Boolean(editingId)) }, [editingId, onEditingChange])
  useEffect(() => () => onEditingChange(false), [onEditingChange])

  useEffect(() => {
    // 先前操作的迟到读回不得卸载正在编辑的行；结束编辑后再读取最新列表。
    if (editingId) return
    const controller = new AbortController()
    setLoading(true)
    setError('')
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE), q: query.trim() })
      void api<PendingPage>(`/api/projects/${projectId}/glossary/pending?${params}`, { signal: controller.signal }, '读取待复核术语')
        .then((data) => {
          if (controller.signal.aborted || data.project_id !== projectId) return
          if (page > Math.max(1, data.total_pages)) { setPage(Math.max(1, data.total_pages)); return }
          setResult(data)
        })
        .catch((caught) => { if (!controller.signal.aborted) setError(errorText(caught)) })
        .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }, 200)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [projectId, query, page, reload, refreshVersion, editingId])

  function confirmed() {
    setEditingId(null)
    setMessage('术语已确认，已加入正常术语表。')
    setReload((value) => value + 1)
    onConfirmed()
  }

  return <section aria-label="待复核术语" data-testid="pending-glossary-review">
    <div className="muted-left">强制覆盖的导入术语需逐条复核；确认前不参与术语匹配或导出。稍后处理不会丢失记录。</div>
    {!canCurate ? <div className="info-line">当前账号只读，请由项目运营或管理员复核。</div> : null}
    <div className="wide-table-search">
      <input aria-label="搜索待复核术语" placeholder="搜索 ID / CN / 译文 / 分类 / 备注" value={query} disabled={Boolean(editingId)} onChange={(event) => { setQuery(event.target.value); setPage(1); setMessage('') }} />
      <span>{result ? `共 ${result.total_rows} 条语言记录` : '正在读取'}</span>
    </div>
    {message ? <div role="status" className="info-line">{message}</div> : null}
    {error ? <div role="alert" className="info-line warn">{error} <button type="button" className="btn btn-sm" onClick={() => setReload((value) => value + 1)}>重试读取</button></div> : null}
    {loading ? <div role="status" className="muted-left">正在读取待复核术语…</div> : null}
    {!loading && !error && result ? <>
      <div className="table-scroll asset-table-scroll">
        <table className="glossary-table" aria-label="待复核术语列表">
          <thead><tr><th>ID / 语言</th><th>CN</th><th>译文</th><th>分类 / 备注</th><th>操作</th></tr></thead>
          <tbody>
            {result.items.map((term) => <PendingTermRow key={`${term.id}:${term.revision}`} projectId={projectId} term={term} canCurate={canCurate} editBlocked={Boolean(editingId && editingId !== term.id)} onEditing={(editing) => setEditingId(editing ? term.id : null)} onConfirmed={confirmed} onReload={() => { setEditingId(null); setReload((value) => value + 1) }} />)}
            {!result.items.length ? <tr><td colSpan={5} className="muted">{query.trim() ? '没有匹配的待复核术语' : '暂无待复核术语'}</td></tr> : null}
          </tbody>
        </table>
      </div>
      <div className="wide-table-pager">
        <span>第 {page} / {Math.max(1, result.total_pages)} 页</span>
        {result.total_pages > 1 ? <div className="row-actions compact-actions">
          <button type="button" className="btn btn-ghost btn-sm" disabled={Boolean(editingId) || page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</button>
          <button type="button" className="btn btn-ghost btn-sm" disabled={Boolean(editingId) || page >= result.total_pages} onClick={() => setPage((value) => value + 1)}>下一页</button>
        </div> : null}
      </div>
    </> : null}
  </section>
}

function PendingTermRow({ projectId, term, canCurate, editBlocked, onEditing, onConfirmed, onReload }: {
  projectId: string; term: PendingTerm; canCurate: boolean; editBlocked: boolean; onEditing: (editing: boolean) => void; onConfirmed: () => void; onReload: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ term_key: term.term_key || '', source: term.source, target: term.target, category: term.category || '', note: term.note || '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState(false)
  const pending = useRef(false)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  async function save() {
    if (pending.current || conflict || !draft.source.trim() || !draft.target.trim()) return
    pending.current = true
    setSaving(true)
    setError('')
    try {
      await api(`/api/projects/${projectId}/glossary/${term.id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...draft, expected_revision: term.revision }),
      }, '确认术语')
      if (mounted.current) onConfirmed()
    } catch (caught) {
      if (!mounted.current) return
      const changed = caught instanceof ApiRequestError && caught.status === 409
        && (caught.detail as { code?: string } | null)?.code === 'glossary_revision_conflict'
      setConflict(changed)
      setError(changed ? '此术语已被其他操作修改，未覆盖新内容。你的编辑仍保留，请载入最新结果后重新复核。' : errorText(caught))
    } finally {
      pending.current = false
      if (mounted.current) setSaving(false)
    }
  }

  function field(key: keyof typeof draft, label: string) {
    return editing ? <input className="cell-input" aria-label={label} value={draft[key]} disabled={saving || conflict} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} /> : <span className="readonly-cell">{draft[key] || '-'}</span>
  }

  return <tr data-testid={`pending-term-${term.id}`}>
    <td>{field('term_key', '待复核 ID')}<span className="muted-left">{languageSpec(term.language || 'en').short} · 待复核</span></td>
    <td>{field('source', '待复核 CN')}</td>
    <td>{field('target', '待复核译文')}</td>
    <td>{field('category', '待复核分类')}{field('note', '待复核备注')}</td>
    <td>
      {canCurate ? <div className="table-actions">
        {editing ? <>
          <button type="button" className="btn btn-primary btn-sm" disabled={saving || conflict || !draft.source.trim() || !draft.target.trim()} onClick={() => void save()}>{saving ? '正在确认…' : '保存并确认'}</button>
          {!conflict ? <button type="button" className="btn btn-ghost btn-sm" disabled={saving} onClick={() => { setEditing(false); onEditing(false); setError(''); setDraft({ term_key: term.term_key || '', source: term.source, target: term.target, category: term.category || '', note: term.note || '' }) }}>稍后处理</button> : null}
        </> : <button type="button" className="btn btn-sm" disabled={editBlocked} onClick={() => { setEditing(true); onEditing(true) }}>编辑并确认</button>}
      </div> : <span className="muted">只读</span>}
      {error ? <div className="info-line warn" role="alert">{error}</div> : null}
      {conflict ? <button type="button" className="btn btn-ghost btn-sm" onClick={onReload}>放弃编辑并载入最新结果</button> : null}
    </td>
  </tr>
}
