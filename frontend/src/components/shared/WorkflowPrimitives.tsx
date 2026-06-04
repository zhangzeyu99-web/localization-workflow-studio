import { artifactFileName, artifactPickerLabel, artifactsByRoles, pickerArtifacts } from '../../domain/artifacts'
import { altColumnVisible } from '../../domain/projectAssets'
import { languageSpec, supportedLanguages, type LanguageCode } from '../../languages'
import type { Artifact, GlossaryPreviewRow, Project } from '../../types'

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
  const assets = pickerArtifacts(artifactsByRoles(project, role))
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

export function ArtifactNote({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  return (
    <div className={`ai-card ${compact ? 'compact-note' : ''}`}>
      <div className="ai-header">{artifactPickerLabel(artifact)}</div>
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
