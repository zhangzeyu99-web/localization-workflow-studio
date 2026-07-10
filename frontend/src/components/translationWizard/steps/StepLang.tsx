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
      <div className="panel-title"><span className="badge">步骤 6/9</span>目标语言</div>
      <div className="panel-desc">选择本次翻译语言。</div>
      {readyForQa ? (
        <div className="translation-readiness-box ready">
          <div className="readiness-head">
            <strong>已识别目标语言</strong>
            <span>可直接校对</span>
          </div>
          <p>{selectedLabels || languageSpec(selectedLanguage).short}</p>
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
            title={selectedLanguage === lang.code ? '当前语言' : '选择语言'}
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
