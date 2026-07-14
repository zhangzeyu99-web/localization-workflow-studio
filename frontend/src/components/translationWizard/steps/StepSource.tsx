import { translationInputMode } from '../../../domain/translationFlow'
import { type LanguageCode } from '../../../languages'
import { ArtifactNote, AssetSelect, FileBoxWithTemplate } from '../../shared/WorkflowPrimitives'
import type { Artifact, Project, TranslationReadiness } from '../../../types'

export function StepSource({
  project,
  onUploadSource,
  sourceArtifact,
  setSourceArtifact,
  selectedLanguage,
  translationReadiness,
  sourceInputNotice,
  invalidSourceArtifactIds = [],
  setQaArtifact,
  setStep
}: {
  project: Project
  onUploadSource: (file: File) => void
  sourceArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  selectedLanguage: LanguageCode
  translationReadiness?: TranslationReadiness | null
  sourceInputNotice?: TranslationReadiness | null
  invalidSourceArtifactIds?: string[]
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
}) {
  const displayProject = invalidSourceArtifactIds.length
    ? { ...project, artifacts: (project.artifacts || []).filter((artifact) => !invalidSourceArtifactIds.includes(artifact.id)) }
    : project
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id ? translationReadiness : null
  const notice = readiness || sourceInputNotice || null
  const mode = translationInputMode(notice)
  const tone = mode === 'ready_for_qa' ? 'ready' : mode === 'invalid' ? 'todo' : mode === 'needs_translation' ? 'checking' : 'idle'
  const modeLabel = mode === 'ready_for_qa'
    ? '已译校对表'
    : mode === 'needs_translation'
      ? '待翻译语言表'
      : mode === 'invalid'
        ? '格式需要修正'
        : '等待检查'
  const nextActionText = mode === 'ready_for_qa'
    ? '下一步：QA 校对'
    : mode === 'needs_translation'
      ? '下一步：术语候选'
      : mode === 'invalid'
        ? '请重新上传'
        : '上传后自动识别'
  const readinessSummary = !notice
    ? ''
    : mode === 'ready_for_qa'
      ? `${notice.translated_rows || 0}/${notice.source_rows || 0} 行已译`
      : mode === 'needs_translation'
        ? `${(notice.empty_target_rows || 0) + (notice.cjk_target_rows || 0)} 行待翻译`
        : '文件结构需要修正'
  return (
    <>
      <div className="panel-title"><span className="badge">步骤 4/9</span>判定输入</div>
      <div className="panel-desc">上传语言表，系统自动分流。</div>
      <div className="action-card input-type-card">
        <div className="input-source-grid">
          <AssetSelect label="选择已有语言表" project={displayProject} role="language_source" value={sourceArtifact && invalidSourceArtifactIds.includes(sourceArtifact.id) ? null : sourceArtifact} onChange={setSourceArtifact} allowEmpty />
          <FileBoxWithTemplate label="上传语言表" onFile={onUploadSource} templateKind="language-table" />
        </div>
        {notice ? (
          <div className={`translation-readiness-box ${tone}`}>
            <div className="readiness-head">
              <strong>{modeLabel}</strong>
              <span>{readinessSummary}</span>
            </div>
            <div className="branch-next-line">{nextActionText}</div>
            {mode === 'ready_for_qa' && sourceArtifact ? (
              <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button>
            ) : null}
            {mode === 'invalid' ? <div className="warn-line">请按模板修正后重传。</div> : null}
          </div>
        ) : (
          <div className="translation-readiness-box idle">
            <div className="readiness-head">
              <strong>等待语言表</strong>
              <span>上传后自动识别</span>
            </div>
          </div>
        )}
      </div>
      {sourceArtifact ? <ArtifactNote artifact={sourceArtifact} /> : null}
    </>
  )
}
