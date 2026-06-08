import React, { useEffect, useState } from 'react'
import { WIDE_TABLE_PAGE_SIZE, pagedRows } from '../../assetTableState'
import { artifactPickerLabel } from '../../domain/artifacts'
import { languageSpec, supportedLanguages, type LanguageCode } from '../../languages'
import { ActionStatus, AssetSelect, FileBox, GlossaryPreview, LanguageSelector, TemplateDownloadLink } from '../shared/WorkflowPrimitives'
import { altColumnVisible, displayLanguagesForWideRows, glossaryWideRowMatches, glossaryWideRows, languageFromValue, normalizeGlossaryNote, rowRecords, translationWideRowMatches, translationWideRows, visibleLanguagesFromRows } from '../../domain/projectAssets'
import type { Artifact, GlossaryPreviewRow, GlossaryTerm, Project, TranslationEntry, WideGlossaryRow, WideTranslationRow } from '../../types'

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
  onPageChange
}: {
  testIdPrefix: string
  page: number
  totalRows: number
  onPageChange: (page: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(totalRows / WIDE_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  if (totalRows <= WIDE_TABLE_PAGE_SIZE) {
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

export function GlossaryTab({
  project,
  sourceArtifact,
  termArtifact,
  setTermArtifact,
  glossaryPreview,
  busy,
  status,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onGlossaryExtract,
  onAddTerm,
  onUpdateTerm,
  onDeleteTerm,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  busy: boolean
  status: string
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onGlossaryExtract: () => void
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const [toolsOpen, setToolsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [displayLanguages, setDisplayLanguages] = useState<LanguageCode[]>([])
  const [page, setPage] = useState(1)
  const lang = languageSpec(selectedLanguage)
  const rows = glossaryWideRows(project)
  const availableDisplayLanguages = visibleLanguagesFromRows(rows).filter((code) => code !== 'en')
  const visibleLanguages = displayLanguagesForWideRows(rows, displayLanguages)
  const filteredRows = rows.filter((row) => glossaryWideRowMatches(row, searchQuery))
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / WIDE_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const currentRows = pagedRows(filteredRows, currentPage)
  const colSpan = 5 + visibleLanguages.reduce((total, code) => total + (altColumnVisible(code) ? 2 : 1), 0)

  useEffect(() => {
    setPage(1)
  }, [searchQuery, displayLanguages.join('|'), rows.length])

  function toggleDisplayLanguage(code: LanguageCode) {
    setDisplayLanguages((value) => value.includes(code) ? value.filter((item) => item !== code) : [...value, code])
  }

  return (
    <>
      <div className="card">
        <div className="card-title">
          <div className="left">项目术语表（{rows.length} 个 CN 概念）</div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToolsOpen((value) => !value)}>{toolsOpen ? '收起导入/导出' : '导入 / 生成 / 导出'}</button>
        </div>
        <WideTableSearchBar
          testId="glossary-search"
          value={searchQuery}
          onChange={setSearchQuery}
          totalRows={rows.length}
          filteredRows={filteredRows.length}
          placeholder="强匹配搜索 ID / CN / 译文 / 分类 / 备注"
        />
        {toolsOpen ? (
          <GlossaryToolsPanel
            project={project}
            sourceArtifact={sourceArtifact}
            termArtifact={termArtifact}
            setTermArtifact={setTermArtifact}
            busy={busy}
            onUploadTerm={onUploadTerm}
            onGlossaryPreview={onGlossaryPreview}
            onGlossaryImport={onGlossaryImport}
            onGlossaryExtract={onGlossaryExtract}
            selectedLanguage={selectedLanguage}
            setSelectedLanguage={setSelectedLanguage}
          />
        ) : null}
        <ActionStatus status={status} busy={busy} />
        {toolsOpen && glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} selectedLanguage={selectedLanguage} /> : null}
        <details className="manual-maintenance" data-testid="manual-glossary-tools">
          <summary>手动新增 / 多语言维护</summary>
          <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); onAddTerm(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
            <input name="term_key" placeholder="ID" />
            <input name="source" placeholder="CN" required />
            <input name="target" placeholder={lang.targetHeader} />
            {altColumnVisible(selectedLanguage) ? <input name="target_alt" placeholder={lang.altHeader} /> : <input name="target_alt" type="hidden" value="" />}
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
                      {altColumnVisible(code) ? <th>{spec.altHeader}</th> : null}
                    </React.Fragment>
                  )
                })}
                <th>分类</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {currentRows.map((row) => (
                <WideGlossaryTermRow key={row.source_key} row={row} visibleLanguages={visibleLanguages} onUpdateTerm={onUpdateTerm} onDeleteTerm={onDeleteTerm} />
              ))}
              {!rows.length ? <tr><td colSpan={colSpan} className="muted">暂无术语。可上传已有术语表、从语言表生成，或手工新增。</td></tr> : null}
              {rows.length && !filteredRows.length ? <tr><td colSpan={colSpan} className="muted">暂无匹配结果</td></tr> : null}
            </tbody>
          </table>
        </div>
        <WideTablePager testIdPrefix="glossary" page={currentPage} totalRows={filteredRows.length} onPageChange={setPage} />
      </div>
    </>
  )
}

export function GlossaryToolsPanel({
  project,
  sourceArtifact,
  termArtifact,
  setTermArtifact,
  busy,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onGlossaryExtract,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  busy: boolean
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onGlossaryExtract: () => void
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <div className="glossary-tools-panel">
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} allowEmpty />
        <FileBox label="上传术语表 xlsx/csv/json" onFile={onUploadTerm} />
        <div className="row-actions"><TemplateDownloadLink kind="glossary" /></div>
        <div className="language-inline-select">
          <span>从语言表生成 / 单语言兜底：</span>
          <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
        </div>
        <div className="row-actions">
          <button type="button" className="btn btn-ghost" disabled={!termArtifact || busy} onClick={onGlossaryPreview}>自动预览导入</button>
          <button type="button" className="btn btn-primary" disabled={!termArtifact || busy} onClick={onGlossaryImport}>自动导入多语言术语</button>
          <button type="button" className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>生成 {lang.short} 术语候选</button>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx`}>导出全部 XLSX</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=csv`}>导出全部 CSV</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=json`}>导出全部 JSON</a>
        </div>
        {!sourceArtifact ? <div className="warn-line">需要从语言表生成术语时，先在“翻译”页上传待翻译表。</div> : null}
        <div className="muted-left">自动导入会识别 EN/EN2、KR/KO、JP/JA；KR/JP 默认不使用第二译名列。</div>
      </div>
    </div>
  )
}

export function WideGlossaryTermRow({
  row,
  visibleLanguages,
  onUpdateTerm,
  onDeleteTerm
}: {
  row: WideGlossaryRow
  visibleLanguages: LanguageCode[]
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: row.term_key || '',
    source: row.source || '',
    category: row.category || '',
    note: normalizeGlossaryNote(row.note),
    targets: supportedLanguages.reduce((acc, lang) => {
      acc[lang.code] = row.translations[lang.code]?.target || ''
      return acc
    }, {} as Record<LanguageCode, string>),
    enAlt: row.translations.en?.target_alt || ''
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
      }, {} as Record<LanguageCode, string>),
      enAlt: row.translations.en?.target_alt || ''
    })
    setEditing(false)
  }, [row.source_key, row.term_key, row.source, row.category, row.note, JSON.stringify(row.translations)])

  async function save() {
    const records = rowRecords<GlossaryTerm>(row)
    for (const record of records) {
      const code = languageFromValue(record.language) || 'en'
      await onUpdateTerm(record, {
        term_key: draft.term_key,
        source: draft.source,
        target: draft.targets[code] || '',
        target_alt: code === 'en' ? draft.enAlt : '',
        category: draft.category,
        note: draft.note
      })
    }
    setEditing(false)
  }

  async function remove() {
    const records = rowRecords<GlossaryTerm>(row)
    for (const record of records) await onDeleteTerm(record)
  }

  function sharedCell(key: 'term_key' | 'source' | 'category' | 'note') {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  function targetCell(code: LanguageCode) {
    if (!editing) return <span className="readonly-cell">{draft.targets[code] || '-'}</span>
    return <input className="cell-input" value={draft.targets[code] || ''} onChange={(event) => setDraft((value) => ({ ...value, targets: { ...value.targets, [code]: event.target.value } }))} />
  }

  function enAltCell() {
    if (!editing) return <span className="readonly-cell">{draft.enAlt || '-'}</span>
    return <input className="cell-input" value={draft.enAlt} onChange={(event) => setDraft((value) => ({ ...value, enAlt: event.target.value }))} />
  }

  return (
    <tr className={row.conflicts.length ? 'has-conflict' : ''}>
      <td>{sharedCell('term_key')}{row.conflicts.length ? <span className="conflict-badge" title={row.conflicts.map((item) => `${item.field}: ${item.values.join(' / ')}`).join('\n')}>字段冲突</span> : null}</td>
      <td>{sharedCell('source')}</td>
      {visibleLanguages.map((code) => (
        <React.Fragment key={code}>
          <td>{targetCell(code)}</td>
          {altColumnVisible(code) ? <td>{enAltCell()}</td> : null}
        </React.Fragment>
      ))}
      <td>{sharedCell('category')}</td>
      <td>{sharedCell('note')}</td>
      <td>
        <div className="table-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={save}>保存</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={remove}>删除</button>
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>编辑</button>
          )}
        </div>
      </td>
    </tr>
  )
}

export function TranslationArchiveTab({
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
  onGoQA
}: {
  project: Project
  archiveArtifact: Artifact | null
  setArchiveArtifact: (artifact: Artifact | null) => void
  busy: boolean
  status: string
  onUploadArchive: (file: File) => Promise<Artifact | null>
  onImportArchive: (artifact?: Artifact | null) => Promise<boolean>
  onAddTranslation: (form: FormData) => void
  onUpdateTranslation: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDeleteTranslation: (entry: TranslationEntry) => Promise<void>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  onGoQA?: () => void
}) {
  const [importOpen, setImportOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportLanguage, setExportLanguage] = useState<LanguageCode | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [displayLanguages, setDisplayLanguages] = useState<LanguageCode[]>([])
  const [page, setPage] = useState(1)
  const rows = translationWideRows(project)
  const availableDisplayLanguages = visibleLanguagesFromRows(rows).filter((code) => code !== 'en')
  const visibleLanguages = displayLanguagesForWideRows(rows, displayLanguages)
  const filteredRows = rows.filter((row) => translationWideRowMatches(row, searchQuery))
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / WIDE_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const currentRows = pagedRows(filteredRows, currentPage)
  const lang = languageSpec(selectedLanguage)
  const colSpan = 4 + visibleLanguages.reduce((total, code) => total + (altColumnVisible(code) ? 2 : 1), 0)

  useEffect(() => {
    setPage(1)
  }, [searchQuery, displayLanguages.join('|'), rows.length])

  function toggleDisplayLanguage(code: LanguageCode) {
    setDisplayLanguages((value) => value.includes(code) ? value.filter((item) => item !== code) : [...value, code])
  }

  return (
    <div className="card">
      <div className="card-title">
        <div className="left">项目译文归档（{rows.length} 个 CN 源文）</div>
        <div className="card-actions">
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setImportOpen(true)}>导入译文</button>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExportOpen((value) => !value)}>{exportOpen ? '收起导出' : '导出'}</button>
        </div>
      </div>
      <WideTableSearchBar
        testId="archive-search"
        value={searchQuery}
        onChange={setSearchQuery}
        totalRows={rows.length}
        filteredRows={filteredRows.length}
        placeholder="强匹配搜索 ID / CN / 译文 / 备注"
      />
      {exportOpen ? <TranslationArchiveExportPanel project={project} exportLanguage={exportLanguage} setExportLanguage={setExportLanguage} /> : null}
      <ActionStatus status={status} busy={busy} />
      {importOpen ? (
        <TranslationArchiveImportModal
          archiveArtifact={archiveArtifact}
          busy={busy}
          onClose={() => setImportOpen(false)}
          onUploadArchive={onUploadArchive}
          onImportArchive={onImportArchive}
        />
      ) : null}
      {!rows.length ? (
        <div className="empty-action-card asset-empty-state" data-testid="archive-empty-state">
          <div>
            <strong>还没有译文归档</strong>
            <span>优先导入已翻译表，或先去校对已有译文；QA 通过后也会自动写入这里。</span>
          </div>
          <div className="row-actions compact-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={() => setImportOpen(true)}>导入译文</button>
            {onGoQA ? <button type="button" className="btn btn-ghost btn-sm" onClick={onGoQA}>去校对</button> : null}
          </div>
        </div>
      ) : null}
      <details className="manual-maintenance" data-testid="manual-archive-tools">
        <summary>手动维护归档</summary>
        <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); onAddTranslation(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
          <input name="entry_key" placeholder="ID" />
          <input name="source" placeholder="CN" required />
          <input name="target" placeholder={lang.targetHeader} />
          {altColumnVisible(selectedLanguage) ? <input name="target_alt" placeholder={lang.altHeader} /> : <input name="target_alt" type="hidden" value="" />}
          <input name="note" placeholder="备注" />
          <input name="language" type="hidden" value={selectedLanguage} />
          <button className="btn btn-primary btn-sm">+ 新增 {lang.short}</button>
        </form>
        <div className="language-inline-select">
          <span>新增语言：</span>
          <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
        </div>
      </details>
      {rows.length ? (
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
                        {altColumnVisible(code) ? <th>{spec.altHeader}</th> : null}
                      </React.Fragment>
                    )
                  })}
                  <th>备注</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {currentRows.map((row) => (
                  <WideTranslationEntryRow key={row.source_key} row={row} visibleLanguages={visibleLanguages} onUpdate={onUpdateTranslation} onDelete={onDeleteTranslation} />
                ))}
                {!filteredRows.length ? <tr><td colSpan={colSpan} className="muted">暂无匹配结果</td></tr> : null}
              </tbody>
            </table>
          </div>
          <WideTablePager testIdPrefix="archive" page={currentPage} totalRows={filteredRows.length} onPageChange={setPage} />
        </>
      ) : null}
    </div>
  )
}

export function TranslationArchiveImportModal({
  archiveArtifact,
  busy,
  onClose,
  onUploadArchive,
  onImportArchive
}: {
  archiveArtifact: Artifact | null
  busy: boolean
  onClose: () => void
  onUploadArchive: (file: File) => Promise<Artifact | null>
  onImportArchive: (artifact?: Artifact | null) => Promise<boolean>
}) {
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(archiveArtifact)
  const [message, setMessage] = useState('上传译文表后会立即自动导入多语言归档。')
  const [importing, setImporting] = useState(false)

  async function uploadAndImport(file: File) {
    setImporting(true)
    setMessage(`正在上传：${file.name}`)
    try {
      const artifact = await onUploadArchive(file)
      if (!artifact) {
        setMessage('上传失败，未执行导入。')
        return
      }
      setSelectedArtifact(artifact)
      setMessage('上传完成，正在自动导入多语言归档...')
      const imported = await onImportArchive(artifact)
      setMessage(imported ? '导入完成。' : '导入失败，具体原因见顶部状态。')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="modal-mask show">
      <div className="modal archive-import-modal">
        <div className="settings-head">
          <h3>导入译文归档</h3>
          <button type="button" className="btn btn-ghost btn-sm" disabled={busy || importing} onClick={onClose}>关闭</button>
        </div>
        <p>上传已翻译 workbook / csv，系统自动识别语言列并写入归档。</p>
        <FileBox label="上传译文 workbook/csv" onFile={uploadAndImport} />
        <div className="archive-import-summary">
          <span>当前文件</span>
          <strong>{selectedArtifact ? artifactPickerLabel(selectedArtifact) : '未上传'}</strong>
        </div>
        <div className={importing ? 'inline-status busy' : 'inline-status'}>{message}</div>
      </div>
    </div>
  )
}

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

export function WideTranslationEntryRow({
  row,
  visibleLanguages,
  onUpdate,
  onDelete
}: {
  row: WideTranslationRow
  visibleLanguages: LanguageCode[]
  onUpdate: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDelete: (entry: TranslationEntry) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    entry_key: row.entry_key || '',
    source: row.source || '',
    note: row.note || '',
    targets: supportedLanguages.reduce((acc, lang) => {
      acc[lang.code] = row.translations[lang.code]?.target || ''
      return acc
    }, {} as Record<LanguageCode, string>),
    enAlt: row.translations.en?.target_alt || ''
  })

  useEffect(() => {
    setDraft({
      entry_key: row.entry_key || '',
      source: row.source || '',
      note: row.note || '',
      targets: supportedLanguages.reduce((acc, lang) => {
        acc[lang.code] = row.translations[lang.code]?.target || ''
        return acc
      }, {} as Record<LanguageCode, string>),
      enAlt: row.translations.en?.target_alt || ''
    })
    setEditing(false)
  }, [row.source_key, row.entry_key, row.source, row.note, JSON.stringify(row.translations)])

  async function save() {
    const records = rowRecords<TranslationEntry>(row)
    for (const record of records) {
      const code = languageFromValue(record.language) || 'en'
      await onUpdate(record, {
        entry_key: draft.entry_key,
        source: draft.source,
        target: draft.targets[code] || '',
        target_alt: code === 'en' ? draft.enAlt : '',
        note: draft.note
      })
    }
    setEditing(false)
  }

  async function remove() {
    const records = rowRecords<TranslationEntry>(row)
    for (const record of records) await onDelete(record)
  }

  function sharedCell(key: 'entry_key' | 'source' | 'note') {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  function targetCell(code: LanguageCode) {
    if (!editing) return <span className="readonly-cell">{draft.targets[code] || '-'}</span>
    return <input className="cell-input" value={draft.targets[code] || ''} onChange={(event) => setDraft((value) => ({ ...value, targets: { ...value.targets, [code]: event.target.value } }))} />
  }

  function enAltCell() {
    if (!editing) return <span className="readonly-cell">{draft.enAlt || '-'}</span>
    return <input className="cell-input" value={draft.enAlt} onChange={(event) => setDraft((value) => ({ ...value, enAlt: event.target.value }))} />
  }

  return (
    <tr className={row.conflicts.length ? 'has-conflict' : ''}>
      <td>{sharedCell('entry_key')}{row.conflicts.length ? <span className="conflict-badge" title={row.conflicts.map((item) => `${item.field}: ${item.values.join(' / ')}`).join('\n')}>字段冲突</span> : null}</td>
      <td>{sharedCell('source')}</td>
      {visibleLanguages.map((code) => (
        <React.Fragment key={code}>
          <td>{targetCell(code)}</td>
          {altColumnVisible(code) ? <td>{enAltCell()}</td> : null}
        </React.Fragment>
      ))}
      <td>{sharedCell('note')}</td>
      <td>
        <div className="table-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={save}>保存</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={remove}>删除</button>
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>编辑</button>
          )}
        </div>
      </td>
    </tr>
  )
}
