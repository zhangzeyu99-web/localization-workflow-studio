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

export function TranslationProgressBar({ progress }: { progress: TranslationProgress }) {
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)))
  return (
    <div className="translation-progress">
      <div className="progress-head">
        <strong>翻译进度</strong>
        <span>{progress.completed_batches}/{progress.total_batches} 批 · {progress.completed_rows}/{progress.total_rows} 行 · ETA {formatDuration(progress.eta_seconds)}</span>
      </div>
      <div className="progress-track"><div className="progress-fill" style={{ width: `${percent}%` }} /></div>
      <div className="progress-foot">
        <span>{percent.toFixed(1)}%</span>
        <span>{progress.failed_batch ? `失败批次：${progress.failed_batch}` : `当前批次：${progress.current_batch || '-'}`}</span>
        {progress.rate_limit_wait_seconds ? <span>限流等待 {formatDuration(progress.rate_limit_wait_seconds)}</span> : null}
      </div>
    </div>
  )
}
