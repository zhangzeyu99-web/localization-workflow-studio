import { languageQuery, languageSpec, type LanguageCode } from '../../../languages'
import { ArtifactNote, AssetSelect, FileBoxWithTemplate, GlossaryPreview } from '../../shared/WorkflowPrimitives'
import type { Artifact, GlossaryPreviewRow, Project } from '../../../types'

export function StepTerm({
  project,
  onUploadTerm,
  termArtifact,
  setTermArtifact,
  glossaryPreview,
  onGlossaryPreview,
  onGlossaryImport,
  busy,
  selectedLanguage,
  status
}: {
  project: Project
  onUploadTerm: (file: File) => void
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  busy: boolean
  selectedLanguage: LanguageCode
  status: string
}) {
  const lang = languageSpec(selectedLanguage)
  const templateError = /术语表格式有误|导入模板|重新上传/.test(status)
  return (
    <>
      <div className="panel-title"><span className="badge">步骤 3/9</span>术语表</div>
      <div className="panel-desc">导入已确认术语，可跳过。</div>
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} />
        <FileBoxWithTemplate
          label="上传术语表"
          onFile={onUploadTerm}
          templateKind="glossary"
          highlightTemplate={templateError}
          templateNote={templateError ? '格式有误，请按模板重传。' : '下载模板'}
        />
        {templateError ? <div className="warn-line">格式有误，请按模板重传。</div> : null}
        <div className="row-actions">
          <button className="btn btn-ghost" disabled={!termArtifact || busy} onClick={onGlossaryPreview}>预览术语</button>
          <button className="btn btn-primary" disabled={!termArtifact || busy} onClick={onGlossaryImport}>导入术语</button>
        </div>
        <details className="compact-tools">
          <summary>更多操作</summary>
          <a className="btn btn-ghost btn-sm" href={`/api/projects/${project.id}/glossary/export?format=xlsx&${languageQuery(selectedLanguage)}`}>导出 {lang.short} 术语</a>
        </details>
      </div>
      {termArtifact ? <ArtifactNote artifact={termArtifact} /> : null}
      {glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} selectedLanguage={selectedLanguage} /> : null}
    </>
  )
}
