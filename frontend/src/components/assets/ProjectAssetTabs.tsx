import React, { useEffect, useRef, useState } from 'react'
import { WIDE_TABLE_PAGE_SIZE } from '../../assetTableState'
import { ApiRequestError, api } from '../../apiClient'
import { errorText } from '../../appText'
import { ASSETS_CURATE, useAuth } from '../../auth'
import { artifactExists, artifactFileName, artifactPickerLabel, artifactRole } from '../../domain/artifacts'
import { languageSpec, supportedLanguages, type LanguageCode } from '../../languages'
import { useProjectAssetRows } from '../../hooks/useProjectAssetRows'
import { useProjectGlossaryCandidates } from '../../hooks/useProjectGlossaryCandidates'
import { GlossaryCandidateReview } from '../glossary/GlossaryCandidateReview'
import type { ConfirmDialogOptions } from '../modals/ConfirmModal'
import { ActionStatus, GlossaryPreview, LanguageSelector } from '../shared/WorkflowPrimitives'
import { ArchiveProvenanceBadge } from '../shared/StatusPrimitives'
import { ArchiveImportFlow } from './ArchiveImportFlow'
import type { ArchiveImportReadbackOptions } from '../../domain/archiveImport'
import { languageFromValue, normalizeGlossaryNote, rowRecords } from '../../domain/projectAssets'
import type { Artifact, GlossaryPreviewRow, GlossaryTerm, Project, TranslationEntry, WideGlossaryRow, WideTranslationRow } from '../../types'

type GlossaryWideDraft = {
  term_key: string
  source: string
  category: string
  note: string
  targets: Record<LanguageCode, string>
}

type TranslationWideDraft = {
  entry_key: string
  source: string
  note: string
  targets: Record<LanguageCode, string>
}

function isArchiveRevisionConflict(error: unknown): boolean {
  return error instanceof ApiRequestError
    && error.status === 409
    && Boolean(error.detail && typeof error.detail === 'object' && (error.detail as { code?: unknown }).code === 'archive_revision_conflict')
}

export function WideTableSearchBar({
  testId,
  value,
  onChange,
  totalRows,
  filteredRows,
  placeholder
}: {
  testId: string
  value: string
  onChange: (value: string) => void
  totalRows: number
  filteredRows: number
  placeholder: string
}) {
  return (
    <div className="wide-table-search">
      <input
        data-testid={testId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      <span>{value.trim() ? `匹配 ${filteredRows} / ${totalRows}` : `共 ${totalRows} 行`}</span>
    </div>
  )
}

export function WideTableLanguageControls({
  testIdPrefix,
  availableLanguages,
  selectedLanguages,
  onToggle
}: {
  testIdPrefix: string
  availableLanguages: LanguageCode[]
  selectedLanguages: LanguageCode[]
  onToggle: (language: LanguageCode) => void
}) {
  if (!availableLanguages.length) return null
  const selected = new Set(selectedLanguages)
  return (
    <div className="wide-table-language-controls">
      <span>展示语言：</span>
      {availableLanguages.map((code) => {
        const lang = languageSpec(code)
        return (
          <button
            key={code}
            type="button"
            data-testid={`${testIdPrefix}-display-lang-${code}`}
            className={`lang-chip ${selected.has(code) ? 'selected' : ''}`}
            aria-pressed={selected.has(code)}
            onClick={() => onToggle(code)}
          >
            {lang.short} {lang.label.replace(`${lang.short} `, '')}
          </button>
        )
      })}
    </div>
  )
}

export function WideTablePager({
  testIdPrefix,
  page,
  totalRows,
  onPageChange,
  pageSize = WIDE_TABLE_PAGE_SIZE
}: {
  testIdPrefix: string
  page: number
  totalRows: number
  onPageChange: (page: number) => void
  pageSize?: number
}) {
  const totalPages = Math.max(1, Math.ceil(totalRows / pageSize))
  const currentPage = Math.min(page, totalPages)
  if (totalRows <= pageSize) {
    return <div className="wide-table-pager muted-left">第 1 页 / 共 1 页</div>
  }
  return (
    <div className="wide-table-pager">
      <span>{totalRows} 行 · 第 {currentPage} / {totalPages} 页</span>
      <div className="row-actions compact-actions">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid={`${testIdPrefix}-page-prev`}
          disabled={currentPage <= 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        >
          上一页
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid={`${testIdPrefix}-page-next`}
          disabled={currentPage >= totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        >
          下一页
        </button>
      </div>
    </div>
  )
}

function GlossaryTabImpl({
  project,
  termArtifact,
  setTermArtifact,
  glossaryPreview,
  busy,
  status,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onAddTerm,
  onUpdateTerm,
  onDeleteTerm,
  selectedLanguage,
  setSelectedLanguage,
  confirm
}: {
  project: Project
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  busy: boolean
  status: string
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: (options?: ArchiveImportReadbackOptions) => void | Promise<boolean>
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<boolean>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
}) {
  const { can } = useAuth()
  const canCurate = can(ASSETS_CURATE)
  const [toolsOpen, setToolsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [displayLanguages, setDisplayLanguages] = useState<LanguageCode[]>([])
  const [page, setPage] = useState(1)
  const [unfilteredTotal, setUnfilteredTotal] = useState(0)
  const [mutationStatus, setMutationStatus] = useState('')
  const [mutationError, setMutationError] = useState('')
  const lang = languageSpec(selectedLanguage)
  const requestedLanguages = supportedLanguages
    .map((language) => language.code)
    .filter((code) => code === 'en' || code === selectedLanguage || displayLanguages.includes(code))
  const assetRows = useProjectAssetRows(
    project.id,
    'glossary',
    true,
    page,
    WIDE_TABLE_PAGE_SIZE,
    searchQuery,
    requestedLanguages,
  )
  const rows = assetRows.rows as WideGlossaryRow[]
  const availableDisplayLanguages = assetRows.recordLanguages.filter((code) => code !== 'en')
  const visibleLanguages = supportedLanguages
    .map((language) => language.code)
    .filter((code) => code === 'en' || (availableDisplayLanguages.includes(code) && displayLanguages.includes(code)))
  const colSpan = 5 + visibleLanguages.length

  useEffect(() => {
    if (!searchQuery.trim() && !assetRows.loading) setUnfilteredTotal(assetRows.totalRows)
  }, [assetRows.loading, assetRows.totalRows, searchQuery])

  useEffect(() => {
    setSearchQuery('')
    setDisplayLanguages([])
    setPage(1)
    setUnfilteredTotal(0)
    setMutationStatus('')
    setMutationError('')
  }, [project.id])

  function refreshAssets() {
    setMutationStatus('')
    setPage(1)
    assetRows.refresh()
  }

  function toggleDisplayLanguage(code: LanguageCode) {
    setPage(1)
    setDisplayLanguages((value) => value.includes(code) ? value.filter((item) => item !== code) : [...value, code])
  }

  async function deleteAllLanguages(row: WideGlossaryRow): Promise<boolean> {
    setMutationError('')
    const query = new URLSearchParams({ source_key: row.source_key })
    try {
      const summary = await api<{ count: number; languages: LanguageCode[]; revision: string }>(
        `/api/projects/${project.id}/glossary/by-source-key?${query.toString()}`,
        undefined,
        '读取术语语言范围',
      )
      if (!summary.count) {
        refreshAssets()
        return false
      }
      const labels = summary.languages.map((language) => languageSpec(language).short)
      const approved = await confirm(
        `将删除当前术语的 ${labels.join('、')}，共 ${summary.count} 条语言记录。此操作不可撤销。`,
        { title: '删除全部语言', confirmLabel: '删除全部', cancelLabel: '取消', tone: 'warn' },
      )
      if (!approved) return false
      query.set('expected_revision', summary.revision)
      const result = await api<{ deleted_count: number }>(
        `/api/projects/${project.id}/glossary/by-source-key?${query.toString()}`,
        { method: 'DELETE' },
        '删除术语全部语言',
      )
      refreshAssets()
      return result.deleted_count > 0
    } catch (error) {
      if (isArchiveRevisionConflict(error)) {
        refreshAssets()
        setMutationError('归档内容已变化，已刷新列表；请重新确认删除范围。')
      } else {
        setMutationError(`删除全部语言失败：${errorText(error)}`)
      }
      return false
    }
  }

  async function saveWideRow(row: WideGlossaryRow, draft: GlossaryWideDraft, targetLanguages: LanguageCode[]): Promise<boolean> {
    setMutationStatus('')
    setMutationError('')
    const targets = targetLanguages.reduce<Record<string, string>>((result, language) => {
      if (row.translations[language]?.record) result[language] = draft.targets[language] || ''
      return result
    }, {})
    try {
      await api(
        `/api/projects/${project.id}/glossary/by-source-key?${new URLSearchParams({ source_key: row.source_key }).toString()}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            expected_revision: assetRows.revision,
            shared: { term_key: draft.term_key, source: draft.source, category: draft.category, note: draft.note },
            targets,
          }),
        },
        '保存术语多语言行',
      )
      refreshAssets()
      setMutationStatus('词条已保存')
      return true
    } catch (error) {
      if (isArchiveRevisionConflict(error)) {
        refreshAssets()
        setMutationError('归档内容已变化，已刷新列表；请重新编辑后保存。')
      } else {
        setMutationError(`保存术语失败：${errorText(error)}`)
      }
      return false
    }
  }

  return (
    <>
      <div className="card">
        <div className="card-title">
          <div className="left">项目术语表（{searchQuery.trim() ? assetRows.totalRows : unfilteredTotal} 个 CN 概念）</div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToolsOpen((value) => !value)}>{toolsOpen ? '收起导入/导出' : '导入 / 生成 / 导出'}</button>
        </div>
        <WideTableSearchBar
          testId="glossary-search"
          value={searchQuery}
          onChange={(value) => { setSearchQuery(value); setPage(1) }}
          totalRows={unfilteredTotal}
          filteredRows={assetRows.totalRows}
          placeholder="强匹配搜索 ID / CN / 译文 / 分类 / 备注"
        />
        {toolsOpen ? (
          <GlossaryToolsPanel
            project={project}
            termArtifact={termArtifact}
            setTermArtifact={setTermArtifact}
            busy={busy}
            canCurate={canCurate}
            onUploadTerm={onUploadTerm}
            onGlossaryPreview={onGlossaryPreview}
            onGlossaryImport={onGlossaryImport}
            selectedLanguage={selectedLanguage}
            setSelectedLanguage={setSelectedLanguage}
            onAssetChanged={refreshAssets}
          />
        ) : null}
        <ActionStatus status={mutationStatus || status} busy={busy} />
        {assetRows.loading ? <div className="muted-left" role="status">正在读取项目术语…</div> : null}
        {assetRows.error ? <div className="info-line warn" role="alert">术语读取失败：{assetRows.error}</div> : null}
        {mutationError ? <div className="info-line warn" role="alert">{mutationError}</div> : null}
        {toolsOpen && glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} selectedLanguage={selectedLanguage} /> : null}
        {canCurate ? (
          <details className="manual-maintenance" data-testid="manual-glossary-tools">
            <summary>手动新增 / 多语言维护</summary>
            <form className="glossary-form" onSubmit={(event) => {
              event.preventDefault()
              const form = event.currentTarget
              void Promise.resolve(onAddTerm(new FormData(form))).then(() => { form.reset(); refreshAssets() })
            }}>
              <input name="term_key" placeholder="ID" />
              <input name="source" placeholder="CN" required />
              <input name="target" placeholder={lang.targetHeader} />
              <input name="category" placeholder="分类" />
              <input name="note" placeholder="备注" />
              <input name="language" type="hidden" value={selectedLanguage} />
              <button className="btn btn-primary btn-sm">+ 新增 {lang.short}</button>
            </form>
            <div className="language-inline-select">
              <span>新增 / 生成语言：</span>
              <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
            </div>
          </details>
        ) : null}
        <WideTableLanguageControls
          testIdPrefix="glossary"
          availableLanguages={availableDisplayLanguages}
          selectedLanguages={displayLanguages}
          onToggle={toggleDisplayLanguage}
        />
        <div className="table-scroll asset-table-scroll">
          <table className="glossary-table glossary-wide-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>CN</th>
                {visibleLanguages.map((code) => {
                  const spec = languageSpec(code)
                  return (
                    <React.Fragment key={code}>
                      <th>{spec.targetHeader}</th>
                    </React.Fragment>
                  )
                })}
                <th>分类</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <WideGlossaryTermRow
                  key={row.source_key}
                  row={row}
                  visibleLanguages={visibleLanguages}
                  canCurate={canCurate}
                  selectedLanguage={selectedLanguage}
                  onSave={saveWideRow}
                  onDeleteTerm={onDeleteTerm}
                  onDeleteAll={deleteAllLanguages}
                  onChanged={refreshAssets}
                />
              ))}
              {!assetRows.loading && !assetRows.totalRows && !searchQuery.trim() ? <tr><td colSpan={colSpan} className="muted">暂无术语。可上传已有术语表、从语言表生成，或手工新增。</td></tr> : null}
              {!assetRows.loading && !rows.length && searchQuery.trim() ? <tr><td colSpan={colSpan} className="muted">暂无匹配结果</td></tr> : null}
            </tbody>
          </table>
        </div>
        <WideTablePager testIdPrefix="glossary" page={page} totalRows={assetRows.totalRows} onPageChange={setPage} />
      </div>
    </>
  )
}

export const GlossaryTab = React.memo(GlossaryTabImpl)

export function GlossaryToolsPanel({
  project,
  termArtifact,
  busy,
  canCurate = true,
  onGlossaryImport,
  selectedLanguage,
  onAssetChanged,
}: {
  project: Project
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  busy: boolean
  canCurate?: boolean
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: (options?: ArchiveImportReadbackOptions) => void | Promise<boolean>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  onAssetChanged: () => void
}) {
  const [confirmedImportOpen, setConfirmedImportOpen] = useState(false)
  const [candidateLanguage, setCandidateLanguage] = useState<LanguageCode>(selectedLanguage)
  const confirmedImportTriggerRef = useRef<HTMLButtonElement | null>(null)
  const candidateFlow = useProjectGlossaryCandidates({
    project,
    language: candidateLanguage,
    onReadback: async () => { await onGlossaryImport({ readbackOnly: true }); onAssetChanged() },
  })
  const storedCandidateSources = (project.artifacts || [])
    .filter(artifactExists)
    .filter((artifact) => artifactRole(artifact) === 'language_source')
    .filter((artifact) => /\.xlsx$/i.test(artifactFileName(artifact)))
  const candidateSources = candidateFlow.artifact && !storedCandidateSources.some((artifact) => artifact.id === candidateFlow.artifact?.id)
    ? [candidateFlow.artifact, ...storedCandidateSources]
    : storedCandidateSources

  function openConfirmedImport(event: React.MouseEvent<HTMLButtonElement>) {
    confirmedImportTriggerRef.current = event.currentTarget
    setConfirmedImportOpen(true)
  }

  function closeConfirmedImport() {
    setConfirmedImportOpen(false)
    requestAnimationFrame(() => confirmedImportTriggerRef.current?.focus())
  }

  return (
    <div className="glossary-tools-panel">
      {canCurate ? <div className="action-card archive-tool-block">
        <div className="archive-tool-block-head">
          <div>
            <strong>导入已确认术语</strong>
            <span>用于已经人工确认、可直接合并到项目术语库的 XLSX / CSV / JSON。</span>
          </div>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={openConfirmedImport}>导入已确认术语</button>
        </div>
      </div> : null}
      {canCurate ? <div className="action-card archive-tool-block">
        <div className="archive-tool-block-head">
          <div>
            <strong>扫描术语候选</strong>
            <span>完整语言表先生成候选，再逐条人工确认；不会直接写入项目术语库。</span>
          </div>
        </div>
        <div className="inline-form">
          <label>
            <span>选择完整语言表</span>
            <select
              aria-label="选择完整语言表"
              value={candidateFlow.artifact?.id || ''}
              disabled={candidateFlow.busy}
              onChange={(event) => candidateFlow.selectArtifact(candidateSources.find((artifact) => artifact.id === event.target.value) || null)}
            >
              <option value="">请选择项目内 XLSX</option>
              {candidateSources.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifactPickerLabel(artifact)}</option>)}
            </select>
          </label>
          <label className={`btn btn-ghost ${candidateFlow.busy ? 'disabled' : ''}`}>
            <span>上传完整语言表</span>
            <input
              aria-label="上传完整语言表"
              type="file"
              accept=".xlsx"
              disabled={candidateFlow.busy}
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void candidateFlow.uploadFile(file)
                event.currentTarget.value = ''
              }}
            />
          </label>
        </div>
        {candidateFlow.artifact ? <div className="asset-meta">已选择：<span>{artifactFileName(candidateFlow.artifact)}</span></div> : null}
        <div className="language-inline-select">
          <span>候选目标语言：</span>
          <LanguageSelector selectedLanguage={candidateLanguage} setSelectedLanguage={setCandidateLanguage} />
        </div>
        <div className="row-actions">
          <button type="button" className="btn btn-primary" disabled={!candidateFlow.artifact || candidateFlow.busy} onClick={() => void candidateFlow.scan()}>扫描候选</button>
        </div>
        {!candidateFlow.batch ? (
          <div role="status" aria-label="候选扫描状态" aria-live="polite" className="archive-import-live">{candidateFlow.status}</div>
        ) : null}
        {candidateFlow.batch ? (
          <GlossaryCandidateReview
            batch={candidateFlow.batch}
            candidates={candidateFlow.candidates}
            language={candidateLanguage}
            busy={candidateFlow.busy}
            status={candidateFlow.status}
            canCurate={canCurate}
            onUpdateCandidate={candidateFlow.updateCandidate}
            onResolveCandidates={candidateFlow.resolveCandidates}
            onTranslateMissingCandidates={candidateFlow.translateMissing}
          />
        ) : null}
          <div className="muted-left">完整语言表不会直接写入项目术语库；只能先生成候选，再人工确认加入。</div>
      </div> : null}
      <div className="action-card archive-tool-block">
        <div className="archive-tool-block-head">
          <div><strong>导出术语</strong><span>按当前项目全部已确认术语导出。</span></div>
        </div>
        <div className="row-actions">
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx`}>导出全部 XLSX</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=csv`}>导出全部 CSV</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=json`}>导出全部 JSON</a>
        </div>
      </div>
      {confirmedImportOpen && canCurate ? (
        <ArchiveImportFlow
          project={project}
          kind="glossary"
          defaultLanguage={selectedLanguage}
          initialArtifact={termArtifact}
          onReadback={async () => { await onGlossaryImport({ readbackOnly: true }); onAssetChanged() }}
          onClose={closeConfirmedImport}
        />
      ) : null}
    </div>
  )
}

function WideGlossaryTermRowImpl({
  row,
  visibleLanguages,
  canCurate = true,
  selectedLanguage,
  onSave,
  onDeleteTerm,
  onDeleteAll,
  onChanged,
}: {
  row: WideGlossaryRow
  visibleLanguages: LanguageCode[]
  canCurate?: boolean
  selectedLanguage: LanguageCode
  onSave: (row: WideGlossaryRow, draft: GlossaryWideDraft, targetLanguages: LanguageCode[]) => Promise<boolean>
  onDeleteTerm: (term: GlossaryTerm) => Promise<boolean>
  onDeleteAll: (row: WideGlossaryRow) => Promise<boolean>
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [draft, setDraft] = useState({
    term_key: row.term_key || '',
    source: row.source || '',
    category: row.category || '',
    note: normalizeGlossaryNote(row.note),
    targets: supportedLanguages.reduce((acc, lang) => {
      acc[lang.code] = row.translations[lang.code]?.target || ''
      return acc
    }, {} as Record<LanguageCode, string>)
  })

  useEffect(() => {
    setDraft({
      term_key: row.term_key || '',
      source: row.source || '',
      category: row.category || '',
      note: normalizeGlossaryNote(row.note),
      targets: supportedLanguages.reduce((acc, lang) => {
        acc[lang.code] = row.translations[lang.code]?.target || ''
        return acc
      }, {} as Record<LanguageCode, string>)
    })
    setEditing(false)
  }, [row.source_key, row.term_key, row.source, row.category, row.note, JSON.stringify(row.translations)])

  async function save() {
    setActionBusy(true)
    try {
      if (await onSave(row, draft, visibleLanguages)) setEditing(false)
    } finally {
      setActionBusy(false)
    }
  }

  async function removeCurrentLanguage() {
    const currentRecord = row.translations[selectedLanguage]?.record
    if (!currentRecord) return
    setActionBusy(true)
    try {
      if (await onDeleteTerm(currentRecord)) onChanged()
    } finally {
      setActionBusy(false)
    }
  }

  async function removeAllLanguages() {
    setActionBusy(true)
    try {
      await onDeleteAll(row)
    } finally {
      setActionBusy(false)
    }
  }

  function sharedCell(key: 'term_key' | 'source' | 'category' | 'note') {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  function targetCell(code: LanguageCode) {
    if (!editing) return <span className="readonly-cell">{draft.targets[code] || '-'}</span>
    if (!row.translations[code]?.record) {
      return <input className="cell-input" value="" disabled aria-label={`${languageSpec(code).short} 无归档记录`} title="无该语言记录，请先手动新增" placeholder="无该语言记录" />
    }
    return <input className="cell-input" value={draft.targets[code] || ''} onChange={(event) => setDraft((value) => ({ ...value, targets: { ...value.targets, [code]: event.target.value } }))} />
  }

  return (
    <tr className={row.conflicts.length ? 'has-conflict' : ''}>
      <td>{sharedCell('term_key')}{row.conflicts.length ? <span className="conflict-badge" title={row.conflicts.map((item) => `${item.field}: ${item.values.join(' / ')}`).join('\n')}>字段冲突</span> : null}</td>
      <td>{sharedCell('source')}</td>
      {visibleLanguages.map((code) => (
        <React.Fragment key={code}>
          <td>{targetCell(code)}</td>
        </React.Fragment>
      ))}
      <td>{sharedCell('category')}</td>
        <td>{sharedCell('note')}</td>
        <td>
          <div className="table-actions">
            {canCurate ? (
              <>
                {editing ? (
                  <>
                    <button type="button" className="btn btn-primary btn-sm" disabled={actionBusy} onClick={save}>保存</button>
                    <button type="button" className="btn btn-sm" disabled={actionBusy} onClick={() => setEditing(false)}>取消</button>
                  </>
                ) : (
                  <button type="button" className="btn btn-sm" disabled={actionBusy} onClick={() => setEditing(true)}>编辑</button>
                )}
                <button
                  type="button"
                  className="btn btn-sm"
                  aria-label={`删除当前语言（${languageSpec(selectedLanguage).short}）`}
                  disabled={actionBusy || !row.translations[selectedLanguage]?.record}
                  onClick={() => void removeCurrentLanguage()}
                >
                  删 {languageSpec(selectedLanguage).short}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-danger"
                  aria-label="删除全部语言"
                  disabled={actionBusy}
                  onClick={() => void removeAllLanguages()}
                >
                  删全部
                </button>
              </>
            ) : null}
          </div>
        </td>
    </tr>
  )
}

export const WideGlossaryTermRow = React.memo(WideGlossaryTermRowImpl)

function TranslationArchiveTabImpl({
  project,
  archiveArtifact,
  busy,
  status,
  onUploadArchive,
  onImportArchive,
  onAddTranslation,
  onUpdateTranslation,
  onDeleteTranslation,
  selectedLanguage,
  setSelectedLanguage,
  onGoQA,
  confirm
}: {
  project: Project
  archiveArtifact: Artifact | null
  setArchiveArtifact: (artifact: Artifact | null) => void
  busy: boolean
  status: string
  onUploadArchive: (file: File) => Promise<Artifact | null>
  onImportArchive: (artifact?: Artifact | null, options?: ArchiveImportReadbackOptions) => Promise<boolean>
  onAddTranslation: (form: FormData) => void
  onUpdateTranslation: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDeleteTranslation: (entry: TranslationEntry) => Promise<boolean>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  onGoQA?: () => void
  confirm: (message: string, options?: ConfirmDialogOptions) => Promise<boolean>
}) {
  const { can } = useAuth()
  const canCurate = can(ASSETS_CURATE)
  const [importOpen, setImportOpen] = useState(false)
  const importTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportLanguage, setExportLanguage] = useState<LanguageCode | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [displayLanguages, setDisplayLanguages] = useState<LanguageCode[]>([])
  const [page, setPage] = useState(1)
  const [unfilteredTotal, setUnfilteredTotal] = useState(0)
  const [mutationError, setMutationError] = useState('')
  const requestedLanguages = supportedLanguages
    .map((language) => language.code)
    .filter((code) => code === 'en' || code === selectedLanguage || displayLanguages.includes(code))
  const assetRows = useProjectAssetRows(
    project.id,
    'translations',
    true,
    page,
    WIDE_TABLE_PAGE_SIZE,
    searchQuery,
    requestedLanguages,
  )
  const rows = assetRows.rows as WideTranslationRow[]
  const availableDisplayLanguages = assetRows.recordLanguages.filter((code) => code !== 'en')
  const visibleLanguages = supportedLanguages
    .map((language) => language.code)
    .filter((code) => code === 'en' || (availableDisplayLanguages.includes(code) && displayLanguages.includes(code)))
  const lang = languageSpec(selectedLanguage)
  const colSpan = 5 + visibleLanguages.length

  useEffect(() => {
    if (!searchQuery.trim() && !assetRows.loading) setUnfilteredTotal(assetRows.totalRows)
  }, [assetRows.loading, assetRows.totalRows, searchQuery])

  useEffect(() => {
    setSearchQuery('')
    setDisplayLanguages([])
    setPage(1)
    setUnfilteredTotal(0)
    setMutationError('')
  }, [project.id])

  function refreshAssets() {
    setPage(1)
    assetRows.refresh()
  }

  function toggleDisplayLanguage(code: LanguageCode) {
    setPage(1)
    setDisplayLanguages((value) => value.includes(code) ? value.filter((item) => item !== code) : [...value, code])
  }

  async function deleteAllLanguages(row: WideTranslationRow): Promise<boolean> {
    setMutationError('')
    const query = new URLSearchParams({ source_key: row.source_key })
    try {
      const summary = await api<{ count: number; languages: LanguageCode[]; revision: string }>(
        `/api/projects/${project.id}/translations/by-source-key?${query.toString()}`,
        undefined,
        '读取译文语言范围',
      )
      if (!summary.count) {
        refreshAssets()
        return false
      }
      const labels = summary.languages.map((language) => languageSpec(language).short)
      const approved = await confirm(
        `将删除当前译文的 ${labels.join('、')}，共 ${summary.count} 条语言记录。此操作不可撤销。`,
        { title: '删除全部语言', confirmLabel: '删除全部', cancelLabel: '取消', tone: 'warn' },
      )
      if (!approved) return false
      query.set('expected_revision', summary.revision)
      const result = await api<{ deleted_count: number }>(
        `/api/projects/${project.id}/translations/by-source-key?${query.toString()}`,
        { method: 'DELETE' },
        '删除译文全部语言',
      )
      refreshAssets()
      return result.deleted_count > 0
    } catch (error) {
      if (isArchiveRevisionConflict(error)) {
        refreshAssets()
        setMutationError('归档内容已变化，已刷新列表；请重新确认删除范围。')
      } else {
        setMutationError(`删除全部语言失败：${errorText(error)}`)
      }
      return false
    }
  }

  async function saveWideRow(row: WideTranslationRow, draft: TranslationWideDraft, targetLanguages: LanguageCode[]): Promise<boolean> {
    setMutationError('')
    const targets = targetLanguages.reduce<Record<string, string>>((result, language) => {
      if (row.translations[language]?.record) result[language] = draft.targets[language] || ''
      return result
    }, {})
    try {
      await api(
        `/api/projects/${project.id}/translations/by-source-key?${new URLSearchParams({ source_key: row.source_key }).toString()}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            expected_revision: assetRows.revision,
            shared: { entry_key: draft.entry_key, source: draft.source, note: draft.note },
            targets,
          }),
        },
        '保存译文多语言行',
      )
      refreshAssets()
      return true
    } catch (error) {
      if (isArchiveRevisionConflict(error)) {
        refreshAssets()
        setMutationError('归档内容已变化，已刷新列表；请重新编辑后保存。')
      } else {
        setMutationError(`保存译文失败：${errorText(error)}`)
      }
      return false
    }
  }

  function openImport(event: React.MouseEvent<HTMLButtonElement>) {
    importTriggerRef.current = event.currentTarget
    setImportOpen(true)
  }

  function closeImport() {
    setImportOpen(false)
    requestAnimationFrame(() => importTriggerRef.current?.focus())
  }

  return (
    <div className="card">
      <div className="card-title">
        <div className="left">项目译文归档（{searchQuery.trim() ? assetRows.totalRows : unfilteredTotal} 个 CN 源文）</div>
        <div className="card-actions">
          {canCurate ? <button type="button" className="btn btn-primary btn-sm" onClick={openImport}>导入译文</button> : null}
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExportOpen((value) => !value)}>{exportOpen ? '收起导出' : '导出'}</button>
        </div>
      </div>
      <WideTableSearchBar
        testId="archive-search"
        value={searchQuery}
        onChange={(value) => { setSearchQuery(value); setPage(1) }}
        totalRows={unfilteredTotal}
        filteredRows={assetRows.totalRows}
        placeholder="强匹配搜索 ID / CN / 译文 / 备注"
      />
      {exportOpen ? <TranslationArchiveExportPanel project={project} exportLanguage={exportLanguage} setExportLanguage={setExportLanguage} /> : null}
      <ActionStatus status={status} busy={busy} />
      {assetRows.loading ? <div className="muted-left" role="status">正在读取译文归档…</div> : null}
      {assetRows.error ? <div className="info-line warn" role="alert">译文归档读取失败：{assetRows.error}</div> : null}
      {mutationError ? <div className="info-line warn" role="alert">{mutationError}</div> : null}
      {importOpen && canCurate ? (
        <ArchiveImportFlow
          project={project}
          kind="translations"
          defaultLanguage={selectedLanguage}
          initialArtifact={archiveArtifact}
          onReadback={async () => { await onImportArchive(null, { readbackOnly: true }); refreshAssets() }}
          onClose={closeImport}
        />
      ) : null}
      {!assetRows.loading && !assetRows.totalRows && !searchQuery.trim() ? (
        <div className="empty-action-card asset-empty-state" data-testid="archive-empty-state">
          <div>
            <strong>还没有译文归档</strong>
            <span>可导入已有译文表，或先运行 QA。标准交付会写入可信归档；带问题交付也会归档，并明确标记为“待复核”。</span>
          </div>
          <div className="row-actions compact-actions">
            {canCurate ? <button type="button" className="btn btn-primary btn-sm" onClick={openImport}>导入译文</button> : null}
            {onGoQA ? <button type="button" className="btn btn-ghost btn-sm" onClick={onGoQA}>去校对</button> : null}
          </div>
        </div>
      ) : null}
      {canCurate ? (
        <details className="manual-maintenance" data-testid="manual-archive-tools">
          <summary>手动维护归档</summary>
          <form className="glossary-form" onSubmit={(event) => {
            event.preventDefault()
            const form = event.currentTarget
            void Promise.resolve(onAddTranslation(new FormData(form))).then(() => { form.reset(); refreshAssets() })
          }}>
            <input name="entry_key" placeholder="ID" />
            <input name="source" placeholder="CN" required />
            <input name="target" placeholder={lang.targetHeader} />
            <input name="note" placeholder="备注" />
            <input name="language" type="hidden" value={selectedLanguage} />
            <button className="btn btn-primary btn-sm">+ 新增 {lang.short}</button>
          </form>
          <div className="language-inline-select">
            <span>新增语言：</span>
            <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
          </div>
        </details>
      ) : null}
      {assetRows.totalRows || searchQuery.trim() ? (
        <>
          <WideTableLanguageControls
            testIdPrefix="archive"
            availableLanguages={availableDisplayLanguages}
            selectedLanguages={displayLanguages}
            onToggle={toggleDisplayLanguage}
          />
          <div className="table-scroll asset-table-scroll">
            <table className="glossary-table translation-archive-table translation-wide-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>CN</th>
                  {visibleLanguages.map((code) => {
                    const spec = languageSpec(code)
                    return (
                      <React.Fragment key={code}>
                        <th>{spec.targetHeader}</th>
                      </React.Fragment>
                    )
                  })}
                  <th>来源</th>
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <WideTranslationEntryRow
                    key={row.source_key}
                    row={row}
                    visibleLanguages={visibleLanguages}
                    canCurate={canCurate}
                    selectedLanguage={selectedLanguage}
                    onSave={saveWideRow}
                    onDelete={onDeleteTranslation}
                    onDeleteAll={deleteAllLanguages}
                    onChanged={refreshAssets}
                  />
                ))}
                {!assetRows.loading && !rows.length ? <tr><td colSpan={colSpan} className="muted">暂无匹配结果</td></tr> : null}
              </tbody>
            </table>
          </div>
          <WideTablePager testIdPrefix="archive" page={page} totalRows={assetRows.totalRows} onPageChange={setPage} />
        </>
      ) : null}
    </div>
  )
}

export const TranslationArchiveTab = React.memo(TranslationArchiveTabImpl)

export function TranslationArchiveExportPanel({
  project,
  exportLanguage,
  setExportLanguage
}: {
  project: Project
  exportLanguage: LanguageCode | 'all'
  setExportLanguage: (language: LanguageCode | 'all') => void
}) {
  const suffix = exportLanguage === 'all' ? '' : `&language=${exportLanguage}`
  const label = exportLanguage === 'all' ? '全部语言' : languageSpec(exportLanguage).short
  return (
    <div className="glossary-tools-panel">
      <div className="action-card">
        <div className="inline-form">
          <label>
            <span>导出范围</span>
            <select value={exportLanguage} onChange={(event) => setExportLanguage(event.target.value as LanguageCode | 'all')}>
              <option value="all">全部语言</option>
              {supportedLanguages.map((language) => <option key={language.code} value={language.code}>{language.short}</option>)}
            </select>
          </label>
        </div>
        <div className="row-actions">
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=xlsx${suffix}`}>导出 {label} XLSX</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=csv${suffix}`}>导出 {label} CSV</a>
        </div>
      </div>
    </div>
  )
}

function WideTranslationEntryRowImpl({
  row,
  visibleLanguages,
  canCurate = true,
  selectedLanguage,
  onSave,
  onDelete,
  onDeleteAll,
  onChanged,
}: {
  row: WideTranslationRow
  visibleLanguages: LanguageCode[]
  canCurate?: boolean
  selectedLanguage: LanguageCode
  onSave: (row: WideTranslationRow, draft: TranslationWideDraft, targetLanguages: LanguageCode[]) => Promise<boolean>
  onDelete: (entry: TranslationEntry) => Promise<boolean>
  onDeleteAll: (row: WideTranslationRow) => Promise<boolean>
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [draft, setDraft] = useState({
    entry_key: row.entry_key || '',
    source: row.source || '',
    note: row.note || '',
    targets: supportedLanguages.reduce((acc, lang) => {
      acc[lang.code] = row.translations[lang.code]?.target || ''
      return acc
    }, {} as Record<LanguageCode, string>)
  })

  useEffect(() => {
    setDraft({
      entry_key: row.entry_key || '',
      source: row.source || '',
      note: row.note || '',
      targets: supportedLanguages.reduce((acc, lang) => {
        acc[lang.code] = row.translations[lang.code]?.target || ''
        return acc
      }, {} as Record<LanguageCode, string>)
    })
    setEditing(false)
  }, [row.source_key, row.entry_key, row.source, row.note, JSON.stringify(row.translations)])

  async function save() {
    setActionBusy(true)
    try {
      if (await onSave(row, draft, visibleLanguages)) setEditing(false)
    } finally {
      setActionBusy(false)
    }
  }

  async function removeCurrentLanguage() {
    const currentRecord = row.translations[selectedLanguage]?.record
    if (!currentRecord) return
    setActionBusy(true)
    try {
      if (await onDelete(currentRecord)) onChanged()
    } finally {
      setActionBusy(false)
    }
  }

  async function removeAllLanguages() {
    setActionBusy(true)
    try {
      await onDeleteAll(row)
    } finally {
      setActionBusy(false)
    }
  }

  function sharedCell(key: 'entry_key' | 'source' | 'note') {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  function targetCell(code: LanguageCode) {
    if (!editing) return <span className="readonly-cell">{draft.targets[code] || '-'}</span>
    if (!row.translations[code]?.record) {
      return <input className="cell-input" value="" disabled aria-label={`${languageSpec(code).short} 无归档记录`} title="无该语言记录，请先手动新增" placeholder="无该语言记录" />
    }
    return <input className="cell-input" value={draft.targets[code] || ''} onChange={(event) => setDraft((value) => ({ ...value, targets: { ...value.targets, [code]: event.target.value } }))} />
  }

  return (
    <tr className={row.conflicts.length ? 'has-conflict' : ''}>
      <td>{sharedCell('entry_key')}{row.conflicts.length ? <span className="conflict-badge" title={row.conflicts.map((item) => `${item.field}: ${item.values.join(' / ')}`).join('\n')}>字段冲突</span> : null}</td>
      <td>{sharedCell('source')}</td>
      {visibleLanguages.map((code) => (
        <React.Fragment key={code}>
          <td>{targetCell(code)}</td>
        </React.Fragment>
      ))}
      <td>
        <div className="provenance-list">
          {[...new Set(rowRecords<TranslationEntry>(row).map((record) => record.source_type || ''))].map((sourceType) => (
            <ArchiveProvenanceBadge key={sourceType || 'unknown'} sourceType={sourceType} />
          ))}
        </div>
      </td>
      <td>{sharedCell('note')}</td>
      <td>
        <div className="table-actions">
          {canCurate ? (
            <>
              {editing ? (
                <>
                  <button type="button" className="btn btn-primary btn-sm" disabled={actionBusy} onClick={save}>保存</button>
                  <button type="button" className="btn btn-sm" disabled={actionBusy} onClick={() => setEditing(false)}>取消</button>
                </>
              ) : (
                <button type="button" className="btn btn-sm" disabled={actionBusy} onClick={() => setEditing(true)}>编辑</button>
              )}
              <button
                type="button"
                className="btn btn-sm"
                aria-label={`删除当前语言（${languageSpec(selectedLanguage).short}）`}
                disabled={actionBusy || !row.translations[selectedLanguage]?.record}
                onClick={() => void removeCurrentLanguage()}
              >
                删 {languageSpec(selectedLanguage).short}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                aria-label="删除全部语言"
                disabled={actionBusy}
                onClick={() => void removeAllLanguages()}
              >
                删全部
              </button>
            </>
          ) : null}
        </div>
      </td>
    </tr>
  )
}

export const WideTranslationEntryRow = React.memo(WideTranslationEntryRowImpl)
