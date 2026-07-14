import { multilingualWorkflowItems } from '../../domain/translationFlow'
import { languageSpec, type LanguageCode } from '../../languages'
import type { Project } from '../../types'

export function MultilingualWorkflowBoard({
  project,
  languages,
  inputArtifactId,
  translationTaskId,
  selectedLanguage,
  onSelectLanguage,
}: {
  project: Project
  languages: LanguageCode[]
  inputArtifactId?: string | null
  translationTaskId?: string | null
  selectedLanguage: LanguageCode
  onSelectLanguage: (language: LanguageCode) => void
}) {
  const items = multilingualWorkflowItems(project, languages, inputArtifactId, translationTaskId)
  const ready = items.filter((item) => item.state === 'ready').length
  const issues = items.filter((item) => item.state === 'issues').length
  const active = items.filter((item) => item.state === 'running').length
  const retry = items.filter((item) => item.state === 'blocked' || item.state === 'pending').length

  return (
    <section className="translation-language-progress" data-testid="multilingual-workflow-board">
      <div className="section-head">
        <div>
          <strong>多语言任务总览</strong>
          <span>通过 {ready} · 带问题 {issues} · 处理中 {active} · 待处理 {retry}</span>
        </div>
      </div>
      <div className="translation-language-grid">
        {items.map((item) => (
          <button
            type="button"
            key={item.code}
            data-testid={`multilingual-language-${item.code}`}
            data-state={item.state}
            onClick={() => onSelectLanguage(item.code)}
            className={`translation-language-card ${item.code === selectedLanguage ? 'current' : ''} ${item.state}`}
            title={`查看 ${languageSpec(item.code).label}`}
          >
            <strong>{languageSpec(item.code).short}</strong>
            <span>{item.label}</span>
            <em>{item.detail}</em>
          </button>
        ))}
      </div>
    </section>
  )
}
