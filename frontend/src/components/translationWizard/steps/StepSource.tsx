import { translationInputMode, translationReadinessUserMessage } from '../../../domain/translationFlow'
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
    ? '下一步：直接进入「QA 校对」。QA 通过后可标准交付；未通过时可继续修复，或带问题摘要交付。'
    : mode === 'needs_translation'
      ? '下一步：进入「术语候选」步骤扫描术语候选，再进入 AI 翻译。'
      : mode === 'invalid'
        ? '下一步：重新上传正确文件；这份错误文件已被忽略，不会继续参与流程。'
        : '上传或选择文件后，系统会判断它是待翻译表还是已译校对表。'
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>判断输入类型</div>
      <div className="panel-desc">这里不直接翻译。系统先判断你上传的是“待翻译语言表”还是“已译校对表”，再决定后面走术语候选、AI 翻译，还是直接 QA 校对。</div>
      <div className="action-card input-type-card">
        <div className="input-source-grid">
          <AssetSelect label="使用已有语言表 / 已译表" project={displayProject} role="language_source" value={sourceArtifact && invalidSourceArtifactIds.includes(sourceArtifact.id) ? null : sourceArtifact} onChange={setSourceArtifact} />
          <FileBoxWithTemplate label="上传待翻译表 / 已译校对表" onFile={onUploadSource} templateKind="language-table" />
        </div>
        {notice ? (
          <div className={`translation-readiness-box ${tone}`}>
            <div className="readiness-head">
              <strong>判定结果：{modeLabel}</strong>
              <span>{translationReadinessUserMessage(notice)}</span>
            </div>
            <p>{notice.source_rows || 0} 行原文 / {notice.translated_rows || 0} 行已有译文 / 空译文 {notice.empty_target_rows || 0} / 中文残留 {notice.cjk_target_rows || 0}</p>
            <div className="branch-next-line">{nextActionText}</div>
            {mode === 'ready_for_qa' && sourceArtifact ? (
              <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button>
            ) : null}
            {mode === 'invalid' ? <div className="warn-line">请按模板修正后重新上传。旧的错误文件不会继续显示在可选语言表里。</div> : null}
          </div>
        ) : (
          <div className="translation-readiness-box idle">
            <div className="readiness-head">
              <strong>等待上传</strong>
              <span>支持待翻译表，也支持已译表</span>
            </div>
            <p>待翻译表：目标语言列为空或含中文残留，后续会走「术语候选」到「AI 翻译」。已译表：目标语言列已有完整译文，后续直接去「QA 校对」。</p>
          </div>
        )}
      </div>
      {sourceArtifact ? <ArtifactNote artifact={sourceArtifact} /> : null}
    </>
  )
}
