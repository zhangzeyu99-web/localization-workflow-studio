import { canSkipModelTranslation } from '../../../domain/translationFlow'
import { languageSpec, supportedLanguages, unsupportedLanguages, type LanguageCode } from '../../../languages'
import type { Artifact, TranslationReadiness } from '../../../types'

export function StepLang({
  selectedLanguage,
  setSelectedLanguage,
  selectedLanguages,
  toggleSelectedLanguage,
  sourceArtifact,
  translationReadiness,
  setQaArtifact,
  setStep
}: {
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
  sourceArtifact?: Artifact | null
  translationReadiness?: TranslationReadiness | null
  setQaArtifact?: (artifact: Artifact | null) => void
  setStep?: (step: number) => void
}) {
  const readyForQa = Boolean(sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness))
  const selectedLabels = selectedLanguages.map((code) => languageSpec(code).short).join(' / ')
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 6</span>选择目标语言</div>
      <div className="panel-desc">目标语言优先从「判定输入」步骤的表头自动识别；识别到的语言会默认勾选。后续翻译 / QA 仍按语言拆成单语言任务执行。</div>
      {readyForQa ? (
        <div className="translation-readiness-box ready">
          <div className="readiness-head">
            <strong>已译表已完成语言判定</strong>
            <span>无需进入 AI 翻译</span>
          </div>
          <p>当前表已经有完整译文，已选目标语言为 {selectedLabels || languageSpec(selectedLanguage).short}。建议直接进入「QA 校对」步骤。</p>
          {sourceArtifact && setQaArtifact && setStep ? <button className="btn btn-primary btn-sm" onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>去校对</button> : null}
        </div>
      ) : null}
      <div className="lang-grid">
        {supportedLanguages.map((lang) => (
          <button
            key={lang.code}
            type="button"
            className={`lang-chip ${selectedLanguages.includes(lang.code) ? 'selected' : ''} ${selectedLanguage === lang.code ? 'current' : ''}`}
            onClick={() => toggleSelectedLanguage(lang.code)}
            onDoubleClick={() => setSelectedLanguage(lang.code)}
            title={selectedLanguage === lang.code ? '当前预览 / 当前执行语言' : '点击勾选并设为当前语言'}
          >
            <span className="lang-check">{selectedLanguages.includes(lang.code) ? '✓' : ''}</span>
            {lang.label}
            {selectedLanguage === lang.code ? <small>当前</small> : null}
          </button>
        ))}
        {unsupportedLanguages.map((lang) => (
          <button key={lang} className="lang-chip disabled" disabled title="暂未支持">{lang} · 未支持</button>
        ))}
      </div>
    </>
  )
}
