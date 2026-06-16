import { artifactDownloadHref, artifactFileName, artifactPickerLabel, artifactsByRoles, pickerArtifacts } from '../../domain/artifacts'
import { altColumnVisible } from '../../domain/projectAssets'
import { formatDuration } from '../../domain/translationFlow'
import { languageSpec, supportedLanguages, type LanguageCode } from '../../languages'
import type { Artifact, GlossaryPreviewRow, Project, TranslationProgress } from '../../types'

export function SelectedInput({ label, artifact }: { label: string; artifact: Artifact | null }) {
  return (
    <div className="selected-input">
      <strong>{label}</strong>
      <span>{artifact ? artifactPickerLabel(artifact) : '未选择'}</span>
    </div>
  )
}

export function CheckItem({ ok, title, detail }: { ok: boolean; title: string; detail: string }) {
  return (
    <div className="check-item">
      <div className={`check-icon ${ok ? 'check-pass' : 'check-warn'}`}>{ok ? '✓' : '!'}</div>
      <div className="check-info"><div className="name">{title}</div><div className="detail">{detail}</div></div>
    </div>
  )
}

export function ActionStatus({ status, busy }: { status: string; busy: boolean }) {
  if (!status) return null
  return (
    <div className={`inline-status ${busy ? 'running' : ''}`} role="status" aria-live="polite">
      {busy ? <span className="loading" /> : null}
      <span>{busy ? '正在执行：' : '当前状态：'}{status}</span>
    </div>
  )
}

export function AssetSelect({
  label,
  project,
  role,
  value,
  onChange,
  allowEmpty = false
}: {
  label: string
  project: Project
  role: string | string[]
  value: Artifact | null
  onChange: (artifact: Artifact | null) => void
  allowEmpty?: boolean
}) {
  const pickedAssets = pickerArtifacts(artifactsByRoles(project, role))
  const seenLabels = new Set<string>()
  const assets = pickedAssets.filter((artifact) => {
    const labelKey = artifactPickerLabel(artifact)
    if (value?.id === artifact.id) return true
    if (seenLabels.has(labelKey)) return false
    seenLabels.add(labelKey)
    return true
  })
  return (
    <label className="asset-select">
      <span>{label}</span>
      <select value={value?.id || ''} onChange={(event) => onChange(assets.find((artifact) => artifact.id === event.target.value) || null)}>
        {allowEmpty ? <option value="">不使用</option> : null}
        {!allowEmpty && !assets.length ? <option value="">暂无可用资产</option> : null}
        {assets.map((artifact) => (
          <option key={artifact.id} value={artifact.id}>{artifactPickerLabel(artifact)}</option>
        ))}
      </select>
    </label>
  )
}

export function GlossaryPreview({ rows, selectedLanguage = 'en' }: { rows: GlossaryPreviewRow[]; selectedLanguage?: LanguageCode }) {
  const lang = languageSpec(selectedLanguage)
  const showLanguage = rows.some((row) => row.language && row.language !== selectedLanguage)
  const showAlt = altColumnVisible(selectedLanguage)
  return (
    <div className="card tight">
      <div className="card-title"><div className="left">术语预览（{rows.length} 条）</div></div>
      <table>
        <thead><tr><th>ID</th><th>CN</th>{showLanguage ? <th>语言</th> : null}<th>{lang.targetHeader}</th>{showAlt ? <th>{lang.altHeader}</th> : null}<th>分类</th><th>备注</th></tr></thead>
        <tbody>
          {rows.slice(0, 20).map((row, index) => (
            <tr key={`${row.source}-${index}`}>
              <td>{row.term_key}</td>
              <td>{row.source}</td>
              {showLanguage ? <td>{String(row.language || selectedLanguage).toUpperCase()}</td> : null}
              <td>{row.target}</td>
              {showAlt ? <td>{row.target_alt}</td> : null}
              <td>{row.category}</td>
              <td>{row.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function FileBox({ label, onFile, testId }: { label: string; onFile: (file: File) => void; testId?: string }) {
  return (
    <label className="upload-box" data-testid={testId}>
      <div className="icon">📄</div>
      <div className="label">{label}</div>
      <input type="file" hidden onChange={(event) => event.target.files?.[0] ? onFile(event.target.files[0]) : null} />
    </label>
  )
}

export function TemplateDownloadLink({ kind, label = '下载导入模板' }: { kind: string; label?: string }) {
  return <a className="btn btn-ghost btn-sm" href={`/api/import-templates/${kind}`}>{label}</a>
}

export function FileBoxWithTemplate({
  label,
  onFile,
  templateKind,
  templateTitle = '导入模板',
  templateNote = '先下载模板，按列填写后再上传。',
  templateLabel = '下载模板',
  testId
}: {
  label: string
  onFile: (file: File) => void
  templateKind: string
  templateTitle?: string
  templateNote?: string
  templateLabel?: string
  testId?: string
}) {
  return (
    <div className="upload-template-row">
      <FileBox label={label} onFile={onFile} testId={testId} />
      <div className="template-card">
        <strong>{templateTitle}</strong>
        <span>{templateNote}</span>
        <TemplateDownloadLink kind={templateKind} label={templateLabel} />
      </div>
    </div>
  )
}

export function ArtifactNote({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  return (
    <div className={`ai-card ${compact ? 'compact-note' : ''}`}>
      <div className="ai-header">
        <span>{artifactPickerLabel(artifact)}</span>
        <a className="btn btn-ghost btn-sm" href={artifactDownloadHref(artifact)}>下载</a>
      </div>
      {!compact ? <div className="muted-left">{artifactFileName(artifact)}</div> : null}
    </div>
  )
}

export function LanguageSelector({ selectedLanguage, setSelectedLanguage }: { selectedLanguage: LanguageCode; setSelectedLanguage: (language: LanguageCode) => void }) {
  return (
    <div className="lang-grid compact-lang-grid">
      {supportedLanguages.map((lang) => (
        <button
          key={lang.code}
          type="button"
          className={`lang-chip ${selectedLanguage === lang.code ? 'selected' : ''}`}
          onClick={() => setSelectedLanguage(lang.code)}
        >
          {lang.label}
        </button>
      ))}
    </div>
  )
}

export function TranslationProgressBar({ progress, languageLabel = '' }: { progress: TranslationProgress; languageLabel?: string }) {
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)))
  const completed = progress.completed_rows >= progress.total_rows && progress.total_rows > 0
  const currentAttemptText = progress.current_attempt && progress.max_attempts
    ? `第 ${progress.current_attempt}/${progress.max_attempts} 次`
    : ''
  const currentBatchText = progress.current_batch
    ? `第 ${progress.current_batch}/${progress.total_batches} 批`
    : ''
  const currentRowsText = progress.current_batch_rows
    ? `本批 ${progress.current_batch_rows} 行`
    : ''
  const stateText = progress.failed_batch
    ? `卡在第 ${progress.failed_batch} 批：修复配置或下载错误报告后，点“继续 AI 翻译”会从已保存批次续跑。`
    : completed
      ? '翻译已完成：下一步进入 QA 校对，交付文件会从已保存结果生成。'
      : progress.rate_limit_wait_seconds
        ? `正在等限流窗口：约 ${formatDuration(progress.rate_limit_wait_seconds)} 后继续。`
        : (progress.message || '后台处理中：已完成批次会实时保存，刷新页面后仍可继续。')
  const termAudit = progress.term_audit
  const termCoverageText = termAudit && typeof termAudit.total_rows === 'number'
    ? `术语命中 ${termAudit.term_hit_rows || 0}/${termAudit.total_rows || 0} 行 · 可用术语 ${termAudit.term_count || 0} 条`
    : ''
  return (
    <div className="translation-progress">
      <div className="progress-head">
        <strong>{languageLabel ? `${languageLabel} 翻译进度` : '翻译进度'}</strong>
        <span>{progress.completed_batches}/{progress.total_batches} 批 · {progress.completed_rows}/{progress.total_rows} 行 · ETA {formatDuration(progress.eta_seconds)}</span>
      </div>
      <div className="progress-track"><div className="progress-fill" style={{ width: `${percent}%` }} /></div>
      <div className="progress-foot">
        <span>{percent.toFixed(1)}%</span>
        <span>{progress.failed_batch ? `失败批次：${progress.failed_batch}` : completed ? '批次已完成' : `当前批次：${progress.current_batch || '-'}`}</span>
        {progress.rate_limit_wait_seconds ? <span>限流等待 {formatDuration(progress.rate_limit_wait_seconds)}</span> : null}
      </div>
      {currentBatchText || currentRowsText || currentAttemptText ? (
        <div className="progress-foot">
          {currentBatchText ? <span>{currentBatchText}</span> : null}
          {currentRowsText ? <span>{currentRowsText}</span> : null}
          {currentAttemptText ? <span>{currentAttemptText}</span> : null}
          {progress.provider_timeout_seconds ? <span>单批超时 {Math.round(progress.provider_timeout_seconds)} 秒</span> : null}
        </div>
      ) : null}
      {termCoverageText ? (
        <div className={`progress-guidance ${termAudit?.warning ? 'blocked' : ''}`}>
          {termCoverageText}
          {termAudit?.warning === 'no_term_hits' ? '；当前文本没有命中术语，如不符合预期请返回术语筛选/导入。' : ''}
          {termAudit?.warning === 'glossary_candidates_not_confirmed' ? '；候选术语尚未确认，默认不会参与翻译。' : ''}
          {termAudit?.warning === 'selected_term_artifact_empty' ? '；已选择术语表但未读取到可用术语，请检查文件格式或目标语言列。' : ''}
        </div>
      ) : null}
      <div className={`progress-guidance ${progress.failed_batch ? 'blocked' : completed ? 'done' : ''}`}>{stateText}</div>
    </div>
  )
}
