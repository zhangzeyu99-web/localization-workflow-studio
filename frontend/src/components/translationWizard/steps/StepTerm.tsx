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
      <div className="panel-title"><span className="badge">STEP 3</span>导入已确认术语表</div>
      <div className="panel-desc">这里只导入人工维护过的术语模板。完整语言表不要放这里，请到「判定输入」步骤上传并判定，待翻译表会在「术语候选」步骤扫描候选。</div>
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} />
        <FileBoxWithTemplate
          label="上传已确认术语表 xlsx/csv/json"
          onFile={onUploadTerm}
          templateKind="glossary"
          highlightTemplate={templateError}
          templateNote={templateError ? '格式有误，请重新上传。先下载模板，按列填写后再上传。' : '先下载模板，按列填写后再上传。'}
        />
        {templateError ? <div className="warn-line">术语表格式有误，请重新上传；建议先下载右侧模板后按列填写。</div> : null}
        <div className="row-actions">
          <button className="btn btn-ghost" disabled={!termArtifact || busy} onClick={onGlossaryPreview}>预览术语</button>
          <button className="btn btn-primary" disabled={!termArtifact || busy} onClick={onGlossaryImport}>导入到项目术语</button>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx&${languageQuery(selectedLanguage)}`}>导出 {lang.short} 术语</a>
        </div>
      </div>
      {termArtifact ? <ArtifactNote artifact={termArtifact} /> : null}
      {glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} selectedLanguage={selectedLanguage} /> : null}
    </>
  )
}
