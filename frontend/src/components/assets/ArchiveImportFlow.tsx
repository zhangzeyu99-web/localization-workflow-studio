import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { artifactPickerLabel } from '../../domain/artifacts'
import {
  archiveImportSummaryValue,
  artifactCanBeImported,
  type ArchiveImportCommitResult,
  type ArchiveImportKind,
  type ArchiveImportMode,
  type ArchiveImportStage,
  type ArchiveImportSummary,
} from '../../domain/archiveImport'
import { useArchiveImportFlow } from '../../hooks/useArchiveImportFlow'
import { languageSpec, supportedLanguages, type LanguageCode } from '../../languages'
import type { Artifact, Project } from '../../types'
import '../../styles/archive-import.css'

type ArchiveImportFlowProps = {
  project: Project
  kind: ArchiveImportKind
  defaultLanguage: LanguageCode
  initialArtifact?: Artifact | null
  onReadback?: (project: Project) => void | Promise<void>
  onClose: () => void
}

const stageLabels: Array<{ key: ArchiveImportStage; index: string; label: string }> = [
  { key: 'source', index: '1', label: '来源' },
  { key: 'settings', index: '2', label: '设置' },
  { key: 'preview', index: '3', label: '差异预览' },
  { key: 'success', index: '4', label: '提交结果' },
]

const summaryFields: Array<{ key: keyof ArchiveImportSummary; label: string }> = [
  { key: 'insert', label: '新增' },
  { key: 'update', label: '更新' },
  { key: 'unchanged', label: '不变' },
  { key: 'skip', label: '跳过' },
  { key: 'clear', label: '清空' },
  { key: 'deactivate', label: '停用' },
  { key: 'protected', label: '受保护' },
  { key: 'conflict', label: '冲突' },
]

function actionLabel(action?: string): string {
  return ({
    insert: '新增',
    update: '更新',
    unchanged: '不变',
    skip: '跳过',
    clear: '清空',
    deactivate: '停用',
    protected: '受保护',
    conflict: '冲突',
  } as Record<string, string>)[String(action || '')] || String(action || '-')
}

function committedLanguageStats(result: ArchiveImportCommitResult): Array<{ language: string; count: number | null }> {
  const counts = new Map<string, number | null>((result.languages || []).map((language) => [language, null]))
  if (result.language_summary && Object.keys(result.language_summary).length) {
    for (const [language, summary] of Object.entries(result.language_summary)) {
      counts.set(language, archiveImportSummaryValue(summary, 'insert')
        + archiveImportSummaryValue(summary, 'update')
        + archiveImportSummaryValue(summary, 'unchanged'))
    }
    return [...counts].map(([language, count]) => ({ language, count }))
  }
  const entities = [...(result.entries || []), ...(result.terms || [])]
  if (entities.length) {
    for (const language of result.languages || []) counts.set(language, 0)
    for (const entity of entities) {
      const language = String(entity.language || '').trim()
      if (language) counts.set(language, (counts.get(language) ?? 0) + 1)
    }
    return [...counts].map(([language, count]) => ({ language, count }))
  }
  if ((result.languages || []).length === 1 && result.imported_count !== undefined) {
    counts.set(result.languages![0], Number(result.imported_count || 0))
  }
  return [...counts].map(([language, count]) => ({ language, count }))
}

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(
    'button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute('hidden') && element.getClientRects().length > 0)
}

export function ArchiveImportFlow({
  project,
  kind,
  defaultLanguage,
  initialArtifact = null,
  onReadback,
  onClose,
}: ArchiveImportFlowProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const snapshotConfirmRef = useRef<HTMLDivElement | null>(null)
  const sourceSelectRef = useRef<HTMLSelectElement | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const commitButtonRef = useRef<HTMLButtonElement | null>(null)
  const [snapshotConfirmOpen, setSnapshotConfirmOpen] = useState(false)
  const flow = useArchiveImportFlow({
    projectId: project.id,
    kind,
    defaultLanguage,
    initialArtifact,
    onReadback,
  })
  const { state } = flow
  const title = kind === 'translations' ? '安全导入译文归档' : '导入已确认术语'
  const description = kind === 'translations'
    ? '先分析真实差异，再明确提交。选择或上传文件不会自动写入归档。'
    : '仅导入已经人工确认过的术语表；完整语言表请使用候选扫描流程。'
  const assets = useMemo(() => {
    const allowed = (project.artifacts || []).filter((artifact) => artifactCanBeImported(kind, artifact))
    if (state.artifact && !allowed.some((artifact) => artifact.id === state.artifact?.id)) return [state.artifact, ...allowed]
    return allowed
  }, [kind, project.artifacts, state.artifact])
  const datasets = flow.lineages

  useEffect(() => {
    const frame = requestAnimationFrame(() => (sourceSelectRef.current || closeButtonRef.current)?.focus())
    return () => cancelAnimationFrame(frame)
  }, [])

  useEffect(() => {
    if (state.stage !== 'preview' || state.settings.mode !== 'snapshot') setSnapshotConfirmOpen(false)
  }, [state.settings.mode, state.stage])

  function closeDialog() {
    flow.close()
    onClose()
  }

  function handleDialogKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault()
      if (snapshotConfirmOpen) {
        setSnapshotConfirmOpen(false)
        requestAnimationFrame(() => commitButtonRef.current?.focus())
        return
      }
      closeDialog()
      return
    }
    const focusRoot = snapshotConfirmOpen ? snapshotConfirmRef.current : dialogRef.current
    if (event.key !== 'Tab' || !focusRoot) return
    const focusable = focusableElements(focusRoot)
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  async function handleUpload(file: File, input: HTMLInputElement) {
    try {
      await flow.uploadFile(file)
    } finally {
      input.value = ''
    }
  }

  function setMode(mode: ArchiveImportMode) {
    flow.updateSettings({ mode, datasetKey: mode === 'snapshot' ? '' : state.settings.datasetKey })
  }

  function closeSnapshotConfirm() {
    setSnapshotConfirmOpen(false)
    requestAnimationFrame(() => commitButtonRef.current?.focus())
  }

  async function requestCommit() {
    if (state.settings.mode === 'snapshot') {
      setSnapshotConfirmOpen(true)
      return
    }
    await flow.commit()
  }

  return (
    <div className="modal-mask show archive-import-flow-mask">
      <div
        ref={dialogRef}
        className="modal archive-import-flow-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="archive-import-title"
        aria-describedby="archive-import-description"
        onKeyDown={handleDialogKeyDown}
      >
        <header className="archive-import-head">
          <div>
            <span className="archive-import-eyebrow">受控写入 · {kind === 'translations' ? '译文归档' : '确认术语'}</span>
            <h3 id="archive-import-title">{title}</h3>
            <p id="archive-import-description">{description}</p>
          </div>
          <button ref={closeButtonRef} type="button" className="btn btn-ghost btn-sm" data-testid="archive-import-close" onClick={closeDialog}>关闭</button>
        </header>

        <ol className="archive-import-stages" aria-label="导入进度">
          {stageLabels.map((stage) => (
            <li
              key={stage.key}
              data-testid={`archive-import-stage-${stage.key}`}
              aria-current={state.stage === stage.key ? 'step' : undefined}
              className={state.stage === stage.key ? 'active' : ''}
            >
              <span>{stage.index}</span>
              <strong>{stage.label}</strong>
            </li>
          ))}
        </ol>

        <div className="archive-import-body">
          {state.stage === 'source' ? (
            <section className="archive-import-section" aria-labelledby="archive-source-heading">
              <div className="archive-import-section-head">
                <div><span>第 1 步</span><h4 id="archive-source-heading">选择可信来源</h4></div>
                <p>文件只会进入设置阶段，不会自动分析或提交。</p>
              </div>
              <label className="archive-import-field">
                <span>选择已有文件</span>
                <select
                  ref={sourceSelectRef}
                  aria-label="选择已有文件"
                  value={state.artifact?.id || ''}
                  onChange={(event) => flow.selectArtifact(assets.find((artifact) => artifact.id === event.target.value) || null)}
                >
                  <option value="">请选择项目内文件</option>
                  {assets.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifactPickerLabel(artifact)}</option>)}
                </select>
              </label>
              <div className="archive-import-or" aria-hidden="true"><span>或</span></div>
              <label className="archive-import-upload">
                <span className="archive-import-upload-title">上传新文件</span>
                <span>{kind === 'translations' ? 'XLSX / CSV / JSON 译文表' : 'XLSX / CSV / JSON 已确认术语表'}</span>
                <input
                  type="file"
                  aria-label="上传新文件"
                  accept=".xlsx,.csv,.json"
                  disabled={Boolean(state.busy)}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0]
                    if (file) void handleUpload(file, event.currentTarget)
                  }}
                />
              </label>
              {kind === 'glossary' ? <div className="archive-import-guidance">这是人工确认入口。完整语言表不会直接写入术语库，应改用“扫描候选”。</div> : null}
            </section>
          ) : null}

          {state.stage === 'settings' ? (
            <section className="archive-import-section" aria-labelledby="archive-settings-heading">
              <div className="archive-import-section-head">
                <div><span>第 2 步</span><h4 id="archive-settings-heading">确认作用范围</h4></div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={flow.showSource}>更换来源</button>
              </div>
              <div className="archive-import-source-line">
                <span>当前文件</span>
                <strong>{state.artifact?.label || state.artifact?.path || '未选择'}</strong>
              </div>

              {kind === 'translations' ? (
                <fieldset className="archive-import-fieldset">
                  <legend>导入模式</legend>
                  <div className="archive-import-mode-grid">
                    <button
                      type="button"
                      className={state.settings.mode === 'merge' ? 'selected' : ''}
                      aria-pressed={state.settings.mode === 'merge'}
                      data-testid="archive-import-mode-merge"
                      onClick={() => setMode('merge')}
                    >
                      <strong>合并更新</strong>
                      <span>非空匹配值覆盖；空单元格和缺行保留。</span>
                    </button>
                    <button
                      type="button"
                      className={state.settings.mode === 'snapshot' ? 'selected danger' : 'danger'}
                      aria-pressed={state.settings.mode === 'snapshot'}
                      data-testid="archive-import-mode-snapshot"
                      onClick={() => setMode('snapshot')}
                    >
                      <strong>快照覆盖</strong>
                      <span>危险范围操作；仅按后端预览停用缺失项。</span>
                    </button>
                  </div>
                </fieldset>
              ) : (
                <div className="archive-import-fixed-mode"><strong>固定为合并更新</strong><span>confirmed_glossary=true；不会执行快照停用。</span></div>
              )}

              {kind === 'translations' ? (
                <label className="archive-import-field">
                  <span>{state.settings.mode === 'snapshot' ? '覆盖数据集' : '数据集归属'}</span>
                  <select
                    aria-label={state.settings.mode === 'snapshot' ? '覆盖数据集' : '数据集归属'}
                    value={state.settings.datasetKey ? JSON.stringify([state.settings.datasetKey, state.settings.sheet]) : ''}
                    onChange={(event) => {
                      const dataset = datasets.find((item) => item.value === event.target.value)
                      flow.updateSettings(dataset
                        ? { datasetKey: dataset.key, sheet: dataset.sheet }
                        : { datasetKey: '' })
                    }}
                  >
                    <option value="">{state.settings.mode === 'snapshot' ? '请选择后端识别的既有数据集' : '自动判断（匹配既有则更新，否则新建数据集）'}</option>
                    {datasets.map((dataset) => <option key={dataset.value} value={dataset.value}>{dataset.key}{dataset.sheet ? ` · ${dataset.sheet}` : ''}</option>)}
                  </select>
                  {flow.lineagesLoading ? <small>正在读取既有数据集…</small> : null}
                  {flow.lineagesError ? <small role="alert">{flow.lineagesError}</small> : null}
                </label>
              ) : null}

              <fieldset className="archive-import-fieldset">
                <legend>语言范围</legend>
                <div className="archive-import-language-grid">
                  {supportedLanguages.map((language) => {
                    const selected = state.settings.languages.includes(language.code)
                    return (
                      <button
                        key={language.code}
                        type="button"
                        className={selected ? 'selected' : ''}
                        aria-pressed={selected}
                        data-testid={`archive-import-language-${language.code}`}
                        onClick={() => flow.toggleLanguage(language.code)}
                      >
                        {language.short}
                      </button>
                    )
                  })}
                </div>
              </fieldset>

              {state.availableSheets.length ? (
                <label className="archive-import-field">
                  <span>工作表</span>
                  <select aria-label="工作表" value={state.settings.sheet} onChange={(event) => flow.updateSettings({ sheet: event.target.value })}>
                    <option value="">请选择工作表</option>
                    {state.availableSheets.map((sheet) => <option key={sheet} value={sheet}>{sheet}</option>)}
                  </select>
                </label>
              ) : null}

              <details className="archive-import-advanced">
                <summary>高级列映射（留空自动识别）</summary>
                <div className="archive-import-column-grid">
                  <label><span>{kind === 'glossary' ? '术语 ID 列' : 'ID 列'}</span><input value={state.settings.idColumn} onChange={(event) => flow.updateSettings({ idColumn: event.target.value })} /></label>
                  <label><span>CN 源文列</span><input value={state.settings.sourceColumn} onChange={(event) => flow.updateSettings({ sourceColumn: event.target.value })} /></label>
                  <label><span>目标译文列</span><input value={state.settings.targetColumn} onChange={(event) => flow.updateSettings({ targetColumn: event.target.value })} /></label>
                  {kind === 'glossary' ? <label><span>分类列</span><input value={state.settings.categoryColumn} onChange={(event) => flow.updateSettings({ categoryColumn: event.target.value })} /></label> : null}
                  <label><span>备注列</span><input value={state.settings.noteColumn} onChange={(event) => flow.updateSettings({ noteColumn: event.target.value })} /></label>
                </div>
              </details>
            </section>
          ) : null}

          {state.stage === 'preview' && state.preview ? (
            <section className="archive-import-section" aria-labelledby="archive-preview-heading">
              <div className="archive-import-section-head">
                <div><span>第 3 步</span><h4 id="archive-preview-heading">核对真实差异</h4></div>
                <div className="archive-import-preview-scope">
                  {state.preview.dataset_key || '新数据集'} · {state.preview.sheet || '自动工作表'} · {state.preview.languages.map((language) => languageSpec(language).short).join('/')}
                </div>
              </div>
              <div className="archive-import-summary-grid">
                {summaryFields.map((field) => (
                  <div key={field.key} data-testid={`archive-import-summary-${field.key}`} className={['protected', 'conflict'].includes(field.key) ? 'warn' : ''}>
                    <span>{field.label}</span>
                    <strong>{archiveImportSummaryValue(state.preview?.summary, field.key)}</strong>
                  </div>
                ))}
              </div>
              {state.settings.mode === 'snapshot' ? (
                <div className="archive-import-snapshot-warning">
                  <strong>快照范围：{state.preview.dataset_key} · {state.preview.sheet}</strong>
                  <span>将停用 {archiveImportSummaryValue(state.preview.summary, 'deactivate')} 条当前数据集内、但本次文件缺失的译文。</span>
                </div>
              ) : null}
              {state.preview.conflicts.length || !state.preview.can_commit ? (
                <div className="archive-import-conflicts" role="alert">
                  <strong>当前预览不能提交</strong>
                  {(state.preview.conflicts.length ? state.preview.conflicts : [{ message: '后端判定 can_commit=false，请修正设置后重新分析。' }]).map((conflict, index) => (
                    <span key={`${conflict.code || 'blocked'}-${index}`}>{conflict.message || conflict.code || '未知冲突'}{conflict.source ? ` · ${conflict.source}` : ''}</span>
                  ))}
                </div>
              ) : null}
              {archiveImportSummaryValue(state.preview.summary, 'protected') > 0 ? (
                <label className="archive-import-override">
                  <input
                    type="checkbox"
                    checked={state.settings.overrideProtected}
                    onChange={(event) => flow.updateSettings({ overrideProtected: event.target.checked })}
                  />
                  <span>覆盖人工维护项并标记待复核；勾选后必须重新分析</span>
                </label>
              ) : null}
              {state.preview.changes.length ? (
                <div className="archive-import-change-table">
                  <table>
                    <thead><tr><th>动作</th><th>语言</th><th>ID</th><th>CN</th><th>目标文本</th></tr></thead>
                    <tbody>
                      {state.preview.changes.slice(0, 20).map((change, index) => (
                        <tr key={`${change.ordinal || index}-${change.language || ''}`}>
                          <td>{actionLabel(change.action)}</td>
                          <td>{languageSpec(change.language || defaultLanguage).short}</td>
                          <td>{change.entry_key || change.term_key || '-'}</td>
                          <td>{change.source || '-'}</td>
                          <td>{change.explicit_empty ? '（明确清空）' : change.target || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <div className="archive-import-no-samples">后端未返回差异样例；上方汇总仍是本次提交依据。</div>}
            </section>
          ) : null}

          {state.stage === 'success' && state.result ? (
            <section className="archive-import-section archive-import-success" aria-labelledby="archive-success-heading">
              <div className="archive-import-success-mark" aria-hidden="true">✓</div>
              <div><span>第 4 步</span><h4 id="archive-success-heading">{state.readbackWarning ? '提交成功，读回待确认' : '导入已提交并读回'}</h4></div>
              <dl>
                <div><dt>批次 ID</dt><dd>{state.result.batch_id}</dd></div>
                <div><dt>数据集</dt><dd>{state.result.dataset_key || state.preview?.dataset_key || '-'}</dd></div>
                <div><dt>语言</dt><dd>{(state.result.languages || state.preview?.languages || []).map((language) => languageSpec(language).short).join(' / ') || '-'}</dd></div>
                <div><dt>写入变化</dt><dd>{state.result.changed_count ?? (archiveImportSummaryValue(state.result.summary, 'insert') + archiveImportSummaryValue(state.result.summary, 'update'))}</dd></div>
              </dl>
              <div className="archive-import-summary-grid compact">
                {summaryFields.map((field) => (
                  <div key={field.key}><span>{field.label}</span><strong>{archiveImportSummaryValue(state.result?.summary, field.key)}</strong></div>
                ))}
              </div>
              <div className="archive-import-language-results" aria-label="每语言提交统计">
                <strong>每语言提交结果</strong>
                {committedLanguageStats(state.result).map((item) => (
                  <span key={item.language}>{languageSpec(item.language).short}：{item.count === null ? '已提交' : `${item.count} 条`}</span>
                ))}
              </div>
              {state.readbackWarning ? <div className="archive-import-conflicts" role="alert">{state.readbackWarning}</div> : null}
            </section>
          ) : null}
        </div>

        {state.error ? <div className="archive-import-error" role="alert">{state.error}</div> : null}
        <div className="archive-import-live" role="status" aria-live="polite">{state.message}</div>

        <footer className="archive-import-footer">
          <div>
            {state.stage === 'preview' ? <button type="button" className="btn btn-ghost" disabled={Boolean(state.busy)} onClick={flow.showSettings}>返回设置</button> : null}
            {state.stage === 'settings' ? <button type="button" className="btn btn-ghost" disabled={Boolean(state.busy)} onClick={flow.showSource}>返回来源</button> : null}
          </div>
          <div className="archive-import-primary-actions">
            {state.stage === 'success' ? (
              <>
                {state.readbackWarning ? <button type="button" className="btn btn-ghost" disabled={Boolean(state.busy)} onClick={() => void flow.retryReadback()}>重试读回</button> : null}
                <button type="button" className="btn btn-primary" onClick={closeDialog}>关闭并查看归档</button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-primary"
                  data-testid="archive-import-analyze"
                  disabled={state.stage !== 'settings' || !flow.canAnalyze}
                  onClick={() => void flow.analyze()}
                >
                  {state.busy === 'analyze' ? '正在分析…' : '分析差异'}
                </button>
                <button
                  ref={commitButtonRef}
                  type="button"
                  className={state.settings.mode === 'snapshot' ? 'btn btn-danger' : 'btn btn-primary'}
                  data-testid="archive-import-commit"
                  disabled={!flow.canCommit}
                  onClick={() => void requestCommit()}
                >
                  {state.busy === 'commit' ? '正在提交…' : state.settings.mode === 'snapshot' ? '提交快照' : '确认提交'}
                </button>
              </>
            )}
          </div>
        </footer>

        {snapshotConfirmOpen ? (
          <div className="archive-import-confirm-mask">
            <div ref={snapshotConfirmRef} className="archive-import-confirm" role="alertdialog" aria-modal="true" aria-labelledby="archive-snapshot-confirm-title">
              <span>危险范围操作</span>
              <h4 id="archive-snapshot-confirm-title">确认覆盖数据集 {state.preview?.dataset_key}</h4>
              <p>
                作用范围：{state.preview?.sheet || '自动工作表'} · {(state.preview?.languages || []).map((language) => languageSpec(language).short).join('/') || '-'}。后端预览将停用 {archiveImportSummaryValue(state.preview?.summary, 'deactivate')} 条缺失记录；此确认只对当前 token 有效。
              </p>
              <div className="row-actions">
                <button type="button" className="btn btn-ghost" onClick={closeSnapshotConfirm}>取消</button>
                <button type="button" className="btn btn-danger" autoFocus onClick={() => { setSnapshotConfirmOpen(false); void flow.commit() }}>确认覆盖并提交</button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
