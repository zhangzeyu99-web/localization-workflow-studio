import { languageSpec, normalizeLanguageArray, normalizeLanguageCode } from '../languages'
import type { Artifact, Project } from '../types'

export function newestArtifact(artifacts: Artifact[] | undefined, kinds: string[]): Artifact | null {
  return [...(artifacts || [])]
    .filter((artifact) => kinds.includes(artifact.kind))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null
}

export function artifactContentKey(artifact: Artifact): string {
  const sha256 = artifact.metadata?.sha256
  if (typeof sha256 === 'string' && sha256) return `sha:${sha256}`
  return `fallback:${artifact.kind}:${artifact.label}:${artifact.size}`
}

export function uniqueArtifactsByContent(artifacts: Artifact[]): Artifact[] {
  const seen = new Set<string>()
  return artifacts.filter((artifact) => {
    const key = artifactContentKey(artifact)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function artifactFileName(artifact: Artifact): string {
  const original = artifact.metadata?.original_filename
  if (typeof original === 'string' && original.trim()) return original.trim()
  const parts = String(artifact.path || artifact.label || '').split(/[\\/]/)
  return parts[parts.length - 1] || artifact.label
}

export function stripExtension(name: string): string {
  return name.replace(/\.[^.]+$/, '')
}

export function artifactSourceStem(artifact: Artifact): string {
  let stem = stripExtension(artifactFileName(artifact))
  stem = stem
    .replace(/_ID_CN_[A-Z0-9_]+$/i, '')
    .replace(/_glossary_details$/i, '')
    .replace(/_announcement_terms_\d{8}$/i, '')
    .replace(/_announcement_translation_workbook$/i, '')
    .replace(/_workpack_[A-Z]+$/i, '')
    .replace(/_ai_response_[A-Z]+$/i, '')
    .replace(/_prompt_[A-Z]+$/i, '')
  return stem || artifact.label
}

export function artifactDateLabel(artifact: Artifact): string {
  const date = new Date(artifact.created_at)
  if (Number.isNaN(date.getTime())) return ''
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function artifactKindLabel(artifact: Artifact): string {
  if (artifact.kind === 'asset') return '参考文件'
  if (artifact.kind === 'quick_input') return '快速任务输入'
  if (artifact.kind === 'quick_reference') return '快速任务参考'
  if (artifact.kind === 'quick_reference_snapshot') return '快速参考快照'
  if (artifact.kind === 'glossary_final') return '生成术语表'
  if (artifact.kind === 'term_base') return '上传术语表'
  if (artifact.kind === 'glossary_detail') return '术语提取明细'
  if (artifact.kind === 'language_table') return artifact.origin === 'uploaded' ? '上传语言表' : '语言表'
  if (artifact.kind === 'final_workbook' || artifact.kind === 'qa_final_workbook') return '已译语言表'
  if (artifact.kind === 'qa_changes') return '修改记录'
  if (artifact.kind === 'qa_result') return 'QA 回填表'
  if (artifact.kind === 'qa_report') return 'QA 报告'
  if (artifact.kind === 'quality_summary') return 'QA 摘要'
  if (artifact.kind === 'translation_workbook') return '翻译中转表'
  if (artifact.kind === 'announcement_terms_workbook') return '公告术语表'
  if (artifact.kind === 'announcement_translation_workbook') return '公告翻译中转表'
  if (artifact.kind === 'announcement_delivery_package' || artifact.kind === 'announcement_docx_delivery_package') return '公告交付 ZIP'
  if (artifact.kind === 'announcement_output_file' || artifact.kind === 'announcement_docx_output_docx') return '公告成品'
  if (artifact.kind === 'announcement_qa_summary' || artifact.kind === 'announcement_docx_qa_summary') return '公告 QA 摘要'
  if (artifact.kind === 'announcement_workpack') return '公告 Workpack'
  if (artifact.kind === 'announcement_docx_manifest' || artifact.kind === 'announcement_lookup_manifest' || artifact.kind === 'announcement_terms_manifest') return '公告 Manifest'
  if (artifact.kind === 'announcement_lookup_prompt_context') return '公告 Prompt Context'
  if (artifact.kind === 'announcement_ai_supplement_packet') return 'AI 补充包'
  if (artifact.kind === 'announcement_ai_supplement_report') return 'AI 补充报告'
  if (artifact.kind === 'announcement_terms_validation') return '公告术语校验'
  if (artifact.kind === 'prompt_snapshot') return '提示词快照'
  if (artifact.kind === 'project_harness_snapshot') return '项目规则快照'
  if (artifact.kind === 'glossary_snapshot') return '术语快照'
  if (artifact.kind === 'translation_prompt') return '项目翻译提示词'
  if (artifact.kind === 'project_brief') return '项目资料'
  if (artifact.kind === 'project_profile') return '项目分析结果'
  return artifact.origin === 'uploaded' ? '上传文件' : artifact.label
}

export function artifactLanguageLabel(artifact: Artifact): string {
  const single = normalizeLanguageCode(artifact.metadata?.language)
  if (single) return languageSpec(single).short
  const multiple = normalizeLanguageArray(artifact.metadata?.languages)
  return multiple.map((lang) => languageSpec(lang).short).join('/')
}

export function artifactPickerLabel(artifact: Artifact): string {
  const parts = [artifactKindLabel(artifact), artifactLanguageLabel(artifact), artifactSourceStem(artifact), artifactDateLabel(artifact)]
    .map((item) => item.trim())
    .filter(Boolean)
  return [...new Set(parts)].join('｜')
}

export function artifactPickerKey(artifact: Artifact): string {
  const sha256 = artifact.metadata?.sha256
  if (artifact.origin === 'uploaded') {
    return typeof sha256 === 'string' && sha256
      ? `uploaded:${artifact.kind}:${sha256}`
      : `uploaded:${artifact.kind}:${artifactSourceStem(artifact).toLowerCase()}:${artifact.size}`
  }
  const language = artifact.metadata?.language || artifact.metadata?.languages || ''
  if (['glossary_final', 'glossary_detail', 'announcement_terms_workbook', 'announcement_translation_workbook'].includes(artifact.kind)) {
    return `generated:${artifact.kind}:${artifactSourceStem(artifact).toLowerCase()}:${JSON.stringify(language)}`
  }
  return artifactContentKey(artifact)
}

export function isPickerProcessArtifact(artifact: Artifact): boolean {
  return artifact.kind === 'glossary_detail'
}

export function pickerArtifacts(artifacts: Artifact[]): Artifact[] {
  const seen = new Set<string>()
  return [...artifacts]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .filter((artifact) => !isPickerProcessArtifact(artifact))
    .filter((artifact) => {
      const key = artifactPickerKey(artifact)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

export function isAnnouncementSourceDocument(artifact: Artifact): boolean {
  const name = artifactFileName(artifact).toLowerCase()
  return /\.(docx|txt|xlsx)$/.test(name)
}

export function isGeneratedAnnouncementTermsArtifact(artifact: Artifact): boolean {
  if (artifact.kind === 'announcement_terms_workbook') return true
  const original = artifact.metadata?.original_filename
  const text = [artifact.label, artifact.path, typeof original === 'string' ? original : ''].join(' ').toLowerCase()
  return artifact.kind === 'language_table' && (text.includes('announcement_terms') || text.includes('公告术语'))
}

export function runArtifacts(project: Project, runId: string | undefined): Artifact[] {
  if (!runId) return []
  return (project.artifacts || []).filter((artifact) => artifact.run_id === runId)
}

export function artifactRole(artifact: Artifact): string {
  if (artifact.role) return artifact.role
  const map: Record<string, string> = {
    language_table: 'language_source',
    quick_input: 'quick_input',
    quick_reference: 'quick_reference',
    quick_reference_snapshot: 'run_snapshot',
    term_base: 'glossary_source',
    announcement_glossary: 'glossary_source',
    glossary_final: 'glossary_curated',
    final_workbook: 'translation_workbook',
    qa_final_workbook: 'translation_workbook',
    raw_translated_workbook: 'translation_draft',
    qa_report: 'qa_report',
    qa_result: 'qa_report',
    quality_summary: 'qa_report',
    glossary_snapshot: 'run_snapshot',
    prompt_snapshot: 'run_snapshot',
    announcement_lookup_workbook: 'reference_pack',
    announcement_lookup_manifest: 'reference_pack',
    announcement_lookup_prompt_context: 'reference_pack',
    translation_prompt: 'prompt',
    project_brief: 'profile',
    project_profile: 'profile',
    project_harness_snapshot: 'harness_snapshot'
  }
  return map[artifact.kind] || artifact.kind
}

export function artifactsByRole(project: Project, role: string): Artifact[] {
  return (project.artifacts || []).filter((artifact) => artifactRole(artifact) === role)
}

export function artifactsByRoles(project: Project, roles: string | string[]): Artifact[] {
  const accepted = Array.isArray(roles) ? roles : [roles]
  return (project.artifacts || []).filter((artifact) => accepted.includes(artifactRole(artifact)))
}
