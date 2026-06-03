import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

type Project = {
  id: string
  name: string
  type: string
  icon: string
  description: string
  prompt_text: string
  created_at?: string
  updated_at?: string
  profile?: Record<string, unknown>
  stats: {
    tasks: number
    translation_runs?: number
    qa_runs?: number
    words: string
    archived_rows?: number
    langs: number
    glossary: number
  }
  artifacts?: Artifact[]
  runs?: Run[]
  glossary?: GlossaryTerm[]
  translations?: TranslationEntry[]
  announcement_tasks?: AnnouncementTask[]
  harness?: ProjectHarness
  duplicate?: boolean
}

type ProjectHarness = {
  schema_version?: number
  updated_at?: string
  project_metadata?: Record<string, unknown>
  style_guidance?: string
  target_audience?: string
  tone?: string
  forbidden_translations?: string[]
  fixed_terms?: { source?: string; target?: string; note?: string; severity?: string }[]
  hard_rules?: { label?: string; description?: string; pattern?: string; enabled?: boolean }[]
  soft_rules?: { label?: string; description?: string; pattern?: string; enabled?: boolean }[]
  reference_examples?: { source?: string; target?: string; note?: string }[]
  manual_fixes?: Record<string, unknown>[]
  qa_summary?: Record<string, unknown>
}

type Artifact = {
  id: string
  label: string
  kind: string
  role?: string
  origin?: string
  metadata?: Record<string, unknown>
  path: string
  size: number
  created_at: string
  run_id?: string | null
  duplicate?: boolean
}

type Run = {
  id: string
  project_id: string
  kind: string
  language: string
  status: string
  created_at: string
  updated_at: string
  metadata?: Record<string, unknown>
  events?: { id: number; level: string; message: string; created_at: string }[]
  artifacts?: Artifact[]
}

type GlossaryTerm = {
  id: string
  term_key?: string
  source: string
  target: string
  target_alt?: string
  language?: string
  category: string
  note: string
  source_type: string
  confirmed: boolean
}

type TranslationEntry = {
  id: string
  entry_key: string
  source: string
  target: string
  target_alt: string
  language: string
  sheet: string
  row_number: number
  note: string
  source_type: string
  source_artifact_id: string
}

type GlossaryPreviewRow = {
  term_key?: string
  source: string
  target: string
  target_alt?: string
  category: string
  note: string
  language?: string
}

type WideLanguageValue<T> = {
  record: T
  target: string
  target_alt?: string
}

type WideConflict = {
  field: string
  values: string[]
}

type WideGlossaryRow = {
  source_key: string
  source: string
  term_key: string
  category: string
  note: string
  translations: Partial<Record<LanguageCode, WideLanguageValue<GlossaryTerm>>>
  languages: LanguageCode[]
  conflicts: WideConflict[]
}

type WideTranslationRow = {
  source_key: string
  source: string
  entry_key: string
  note: string
  translations: Partial<Record<LanguageCode, WideLanguageValue<TranslationEntry>>>
  languages: LanguageCode[]
  conflicts: WideConflict[]
}

type GlossaryBatch = {
  id: string
  project_id: string
  run_id?: string
  source_artifact_id?: string
  label: string
  language?: string
  status: string
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
  counts: {
    total: number
    pending: number
    accepted: number
    rejected: number
    pending_new: number
    pending_supplement: number
  }
}

type GlossaryCandidate = {
  id: string
  batch_id: string
  project_id: string
  existing_term_id?: string
  action: 'new' | 'supplement' | string
  term_key?: string
  source: string
  target: string
  target_alt?: string
  language?: string
  category: string
  note: string
  translation_status?: 'needs_translation' | 'suggested' | 'reviewed' | string
  translation_source?: 'language_table' | 'model' | 'manual' | 'none' | string
  metadata?: Record<string, unknown>
  status: 'pending' | 'accepted' | 'rejected' | string
}

type QualityIssue = {
  id: string
  source: string
  rule_source: string
  severity: string
  sheet: string
  row: number
  check_type: string
  message: string
  current_translation: string
}

type AppSettings = {
  provider?: string
  preset?: string
  api_key?: string
  model?: string
  reasoning_effort?: string
  batch_size?: number
  max_concurrent_batches?: number
  max_requests_per_minute?: number
  max_estimated_tokens_per_minute?: number
  max_batch_input_tokens?: number
  api_budget_warning_tokens?: number
  max_batch_attempts?: number
}

type TranslationReadiness = {
  artifact_id: string
  label: string
  target_language: string
  source_rows: number
  translated_rows: number
  empty_target_rows: number
  cjk_target_rows: number
  invalid_id_rows?: number
  invalid_id_samples?: string[]
  needs_translation: boolean
  ready_for_qa: boolean
  reason: string
  batch_size: number
  estimated_batches: number
}

type TranslationTargets = {
  artifact_id: string
  label: string
  supported_file: boolean
  source_detected: boolean
  detected_languages: LanguageCode[]
  suggested_language?: LanguageCode | null
  reason?: string
}

type TranslationProgress = {
  total_rows: number
  completed_rows: number
  total_batches: number
  completed_batches: number
  remaining_batches: number
  current_batch?: number | null
  failed_batch?: number | null
  batch_size: number
  max_concurrent_batches?: number
  estimated_total_input_tokens?: number
  rate_limit_wait_seconds?: number
  percent: number
  elapsed_seconds?: number | null
  average_batch_seconds?: number | null
  eta_seconds?: number | null
}

type DeliveryFile = {
  kind: string
  filename: string
  path: string
  download_url?: string
}

type AnnouncementLookupSummary = {
  language: string
  text_chars: number
  materials: number
  matched_terms: number
  matched_translations: number
  constraint_status: string
}

type AnnouncementLookupResult = {
  run: Run
  summary: AnnouncementLookupSummary
  artifacts: Artifact[]
  manifest: Record<string, unknown>
}

type AnnouncementTaskLanguage = {
  id: string
  task_id: string
  project_id: string
  language: LanguageCode
  status: string
  current_step: number
  metadata?: Record<string, unknown>
}

type AnnouncementTask = {
  id: string
  project_id: string
  title: string
  source_artifact_id: string
  source_format: string
  selected_languages: LanguageCode[]
  status: string
  current_step: number
  metadata?: Record<string, unknown>
  languages?: AnnouncementTaskLanguage[]
  artifacts?: Artifact[]
  created_at?: string
  updated_at?: string
}

type AnnouncementTaskResult = {
  task: AnnouncementTask
  run?: Run
  summary?: Record<string, unknown>
  artifacts?: Artifact[]
  manifest?: Record<string, unknown>
  detected_languages?: LanguageCode[]
  selected_languages?: LanguageCode[]
  constraints?: Record<string, unknown>
}

type AnnouncementTermRow = {
  id?: string
  source?: string
  translations?: Record<string, string>
  hit_count?: number
  first_position?: number
}

type AnnouncementLookupOptions = {
  includeGlossary: boolean
  includeTranslationArchive: boolean
}

type DeliverableTask = {
  run_id: string
  task_code: 'A' | 'T' | 'QA' | string
  task_id: string
  task_label: string
  task_type: string
  language: string
  created_at: string
  updated_at: string
  status: string
  processed_rows: number
  source_rows?: number
  translated_rows?: number
  provider?: string
  model?: string
  input_label?: string
  qa_status?: string
  qa_hard_errors?: number
  qa_soft_warnings?: number
  files: {
    final?: DeliveryFile
    changes?: DeliveryFile
  }
}

const API = import.meta.env.VITE_API_BASE_URL || ''
const steps = ['项目资料', 'AI 分析', '术语表', '语言表', '高频词', '目标语言', '模型翻译', '自动校对', '交付']
type LanguageCode = 'en' | 'ko' | 'ja' | 'fr' | 'de' | 'ru' | 'it' | 'es' | 'pt' | 'tr' | 'idn' | 'th' | 'ar'
type LanguageOption = {
  code: LanguageCode
  label: string
  short: string
  targetHeader: string
  altHeader: string
}
const supportedLanguages: LanguageOption[] = [
  { code: 'en', label: 'EN 英语', short: 'EN', targetHeader: 'EN', altHeader: 'EN2' },
  { code: 'ko', label: 'KR 韩语', short: 'KR', targetHeader: 'KR', altHeader: '' },
  { code: 'ja', label: 'JP 日语', short: 'JP', targetHeader: 'JP', altHeader: '' },
  { code: 'fr', label: 'FR 法语', short: 'FR', targetHeader: 'FR', altHeader: '' },
  { code: 'de', label: 'DE 德语', short: 'DE', targetHeader: 'DE', altHeader: '' },
  { code: 'ru', label: 'RU 俄语', short: 'RU', targetHeader: 'RU', altHeader: '' },
  { code: 'it', label: 'IT 意大利语', short: 'IT', targetHeader: 'IT', altHeader: '' },
  { code: 'es', label: 'ES 西班牙语', short: 'ES', targetHeader: 'ES', altHeader: '' },
  { code: 'pt', label: 'PT 葡萄牙语', short: 'PT', targetHeader: 'PT', altHeader: '' },
  { code: 'tr', label: 'TR 土耳其语', short: 'TR', targetHeader: 'TR', altHeader: '' },
  { code: 'idn', label: 'ID 印尼语', short: 'ID', targetHeader: 'IDN', altHeader: '' },
  { code: 'th', label: 'TH 泰语', short: 'TH', targetHeader: 'TH', altHeader: '' },
  { code: 'ar', label: 'AR 阿拉伯语', short: 'AR', targetHeader: 'AR', altHeader: '' }
]
const announcementLanguages = supportedLanguages
const allLanguageOptions = supportedLanguages
const unsupportedLanguages: string[] = []

type ProjectTab = 'meta' | 'glossary' | 'translation' | 'qa' | 'archive' | 'delivery'
type AppView = 'overview' | 'wizard' | 'announcement' | 'quick'

function getProjectHarness(project: Project): ProjectHarness {
  return project.harness || {}
}

function languageSpec(code: string): LanguageOption {
  return allLanguageOptions.find((item) => item.code === code) || supportedLanguages[0]
}

function languageChipTitle(lang: LanguageOption): string {
  return lang.label
}

function languageQuery(code: LanguageCode): string {
  return `language=${encodeURIComponent(code)}`
}


function normalizeSourceKey(value: unknown): string {
  return String(value || '').trim().replace(/\s+/g, '').toLowerCase()
}

function termHasTranslation(term: GlossaryTerm): boolean {
  return Boolean(String(term.target || '').trim() || String(term.target_alt || '').trim())
}

function entryHasTranslation(entry: TranslationEntry): boolean {
  return Boolean(String(entry.target || '').trim() || String(entry.target_alt || '').trim())
}

function languageFromValue(value: unknown): LanguageCode | null {
  return normalizeLanguageCode(value || 'en')
}

function pickSharedValue<T extends Record<string, unknown>>(rows: T[], field: keyof T): string {
  for (const row of rows) {
    const value = String(row[field] || '').trim()
    if (value && value !== '-') return value
  }
  return ''
}

function sharedConflicts<T extends Record<string, unknown>>(rows: T[], fields: (keyof T)[]): WideConflict[] {
  return fields.flatMap((field) => {
    const values: string[] = []
    for (const row of rows) {
      const value = String(row[field] || '').trim()
      if (value && value !== '-' && !values.includes(value)) values.push(value)
    }
    return values.length > 1 ? [{ field: String(field), values }] : []
  })
}

function newestByUpdatedAt<T>(rows: T[]): T {
  return [...rows].sort((a, b) => String((b as { updated_at?: string }).updated_at || '').localeCompare(String((a as { updated_at?: string }).updated_at || '')))[0]
}

function glossaryWideRows(project: Project): WideGlossaryRow[] {
  const grouped = new Map<string, GlossaryTerm[]>()
  for (const term of project.glossary || []) {
    const key = normalizeSourceKey(term.source)
    if (!key) continue
    grouped.set(key, [...(grouped.get(key) || []), term])
  }
  return [...grouped.entries()].map(([sourceKey, rows]) => {
    const translations: WideGlossaryRow['translations'] = {}
    for (const lang of supportedLanguages.map((item) => item.code)) {
      const candidateRows = rows.filter((term) => languageFromValue(term.language) === lang && termHasTranslation(term))
      if (!candidateRows.length) continue
      const record = newestByUpdatedAt(candidateRows)
      translations[lang] = { record, target: record.target || '', target_alt: record.target_alt || '' }
    }
    return {
      source_key: sourceKey,
      source: pickSharedValue(rows, 'source'),
      term_key: pickSharedValue(rows, 'term_key'),
      category: pickSharedValue(rows, 'category'),
      note: normalizeGlossaryNote(pickSharedValue(rows, 'note')),
      translations,
      languages: supportedLanguages.map((item) => item.code).filter((lang) => Boolean(translations[lang])),
      conflicts: sharedConflicts(rows, ['source', 'term_key', 'category', 'note'])
    }
  }).sort((a, b) => a.source.localeCompare(b.source) || a.term_key.localeCompare(b.term_key))
}

function translationWideRows(project: Project): WideTranslationRow[] {
  const grouped = new Map<string, TranslationEntry[]>()
  for (const entry of project.translations || []) {
    const key = normalizeSourceKey(entry.source)
    if (!key) continue
    grouped.set(key, [...(grouped.get(key) || []), entry])
  }
  return [...grouped.entries()].map(([sourceKey, rows]) => {
    const translations: WideTranslationRow['translations'] = {}
    for (const lang of supportedLanguages.map((item) => item.code)) {
      const candidateRows = rows.filter((entry) => languageFromValue(entry.language) === lang && entryHasTranslation(entry))
      if (!candidateRows.length) continue
      const record = newestByUpdatedAt(candidateRows)
      translations[lang] = { record, target: record.target || '', target_alt: record.target_alt || '' }
    }
    return {
      source_key: sourceKey,
      source: pickSharedValue(rows, 'source'),
      entry_key: pickSharedValue(rows, 'entry_key'),
      note: pickSharedValue(rows, 'note'),
      translations,
      languages: supportedLanguages.map((item) => item.code).filter((lang) => Boolean(translations[lang])),
      conflicts: sharedConflicts(rows, ['source', 'entry_key', 'note'])
    }
  }).sort((a, b) => a.source.localeCompare(b.source) || a.entry_key.localeCompare(b.entry_key))
}

function visibleLanguagesFromRows(rows: { languages: LanguageCode[] }[]): LanguageCode[] {
  const found = new Set<LanguageCode>()
  for (const row of rows) row.languages.forEach((lang) => found.add(lang))
  return supportedLanguages.map((item) => item.code).filter((lang) => found.has(lang))
}

const WIDE_TABLE_PAGE_SIZE = 100

function normalizeWideSearch(value: unknown): string {
  return String(value ?? '').trim().toLocaleLowerCase()
}

function translationValuesForSearch(row: { translations: Partial<Record<LanguageCode, WideLanguageValue<GlossaryTerm | TranslationEntry>>> }): string[] {
  return supportedLanguages.flatMap((lang) => {
    const value = row.translations[lang.code]
    return value ? [value.target, value.target_alt || ''] : []
  })
}

function wideRowMatches(fields: unknown[], query: string): boolean {
  const needle = normalizeWideSearch(query)
  if (!needle) return true
  return fields.some((field) => normalizeWideSearch(field).includes(needle))
}

function glossaryWideRowMatches(row: WideGlossaryRow, query: string): boolean {
  return wideRowMatches([row.term_key, row.source, row.category, row.note, ...translationValuesForSearch(row)], query)
}

function translationWideRowMatches(row: WideTranslationRow, query: string): boolean {
  return wideRowMatches([row.entry_key, row.source, row.note, ...translationValuesForSearch(row)], query)
}

function displayLanguagesForWideRows(rows: { languages: LanguageCode[] }[], selectedLanguages: LanguageCode[]): LanguageCode[] {
  const available = new Set(visibleLanguagesFromRows(rows))
  const selected = new Set(selectedLanguages)
  return supportedLanguages
    .map((lang) => lang.code)
    .filter((code) => code === 'en' || (available.has(code) && selected.has(code)))
}

function rowRecords<T>(row: { translations: Partial<Record<LanguageCode, WideLanguageValue<T>>>; languages: LanguageCode[] }): T[] {
  return row.languages.map((code) => row.translations[code]?.record).filter(Boolean) as T[]
}

function pagedRows<T>(rows: T[], page: number): T[] {
  const start = (page - 1) * WIDE_TABLE_PAGE_SIZE
  return rows.slice(start, start + WIDE_TABLE_PAGE_SIZE)
}

function glossaryCoverage(project: Project): Record<LanguageCode, number> {
  const rows = glossaryWideRows(project)
  return supportedLanguages.reduce((acc, lang) => {
    acc[lang.code] = rows.filter((row) => Boolean(row.translations[lang.code])).length
    return acc
  }, {} as Record<LanguageCode, number>)
}

function archiveCoverage(project: Project): Record<LanguageCode, number> {
  const rows = translationWideRows(project)
  return supportedLanguages.reduce((acc, lang) => {
    acc[lang.code] = rows.filter((row) => Boolean(row.translations[lang.code])).length
    return acc
  }, {} as Record<LanguageCode, number>)
}

function coverageSummary(coverage: Record<LanguageCode, number>): string {
  const entries = supportedLanguages
    .map((lang) => ({ lang, count: coverage[lang.code] || 0 }))
    .filter((item) => item.count > 0)
  if (!entries.length) return '暂无覆盖'
  const visible = entries.slice(0, 2).map((item) => `${item.lang.short} ${item.count}`).join(' / ')
  return entries.length > 2 ? `${visible} / +${entries.length - 2}` : visible
}

function altColumnVisible(lang: LanguageCode): boolean {
  return lang === 'en'
}

function scopeProjectToLanguage(project: Project, code: LanguageCode): Project {
  const glossary = (project.glossary || []).filter((term) => (term.language || 'en') === code)
  const translations = (project.translations || []).filter((entry) => (entry.language || 'en') === code)
  return {
    ...project,
    glossary,
    translations,
    stats: {
      ...project.stats,
      glossary: glossary.length,
      archived_rows: translations.length,
      langs: project.stats.langs
    }
  }
}

function isLanguageCode(value: string): value is LanguageCode {
  return allLanguageOptions.some((lang) => lang.code === value)
}

function availableLookupLanguages(project: Project): LanguageCode[] {
  const found = new Set<LanguageCode>()
  for (const term of project.glossary || []) {
    const code = String(term.language || 'en').toLowerCase()
    if (isLanguageCode(code) && (term.target?.trim() || term.target_alt?.trim())) found.add(code)
  }
  for (const entry of project.translations || []) {
    const code = String(entry.language || 'en').toLowerCase()
    if (isLanguageCode(code) && (entry.target?.trim() || entry.target_alt?.trim())) found.add(code)
  }
  return supportedLanguages.map((lang) => lang.code).filter((code) => found.has(code))
}

function projectPromptForLanguage(project: Project, code: LanguageCode): string {
  const prompts = project.profile?.prompts_by_language
  if (prompts && typeof prompts === 'object' && code in prompts) {
    return String((prompts as Record<string, unknown>)[code] || '')
  }
  return project.prompt_text || ''
}

function listToLines(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).join('\n') : ''
}

function linesToList(value: string): string[] {
  return value.split('\n').map((line) => line.trim()).filter(Boolean)
}

function rulesToLines(rules: ProjectHarness['hard_rules']): string {
  return (rules || [])
    .map((rule) => [rule.label, rule.description, rule.pattern].filter(Boolean).join(' | '))
    .join('\n')
}

function linesToRules(value: string): ProjectHarness['hard_rules'] {
  return linesToList(value).map((line) => {
    const [label, description, pattern] = line.split('|').map((part) => part.trim())
    return { label: label || line, description: description || label || line, pattern: pattern || '', enabled: true }
  })
}

function fixedTermsToLines(terms: ProjectHarness['fixed_terms']): string {
  return (terms || [])
    .map((term) => `${term.source || ''} => ${term.target || ''}${term.note ? ` | ${term.note}` : ''}`.trim())
    .filter(Boolean)
    .join('\n')
}

function linesToFixedTerms(value: string): ProjectHarness['fixed_terms'] {
  return linesToList(value).map((line) => {
    const [pair, note] = line.split('|').map((part) => part.trim())
    const [source, target] = pair.split('=>').map((part) => part.trim())
    return { source: source || pair, target: target || '', note: note || '', severity: 'hard' }
  })
}

function newestArtifact(artifacts: Artifact[] | undefined, kinds: string[]): Artifact | null {
  return [...(artifacts || [])]
    .filter((artifact) => kinds.includes(artifact.kind))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null
}

function artifactContentKey(artifact: Artifact): string {
  const sha256 = artifact.metadata?.sha256
  if (typeof sha256 === 'string' && sha256) return `sha:${sha256}`
  return `fallback:${artifact.kind}:${artifact.label}:${artifact.size}`
}

function uniqueArtifactsByContent(artifacts: Artifact[]): Artifact[] {
  const seen = new Set<string>()
  return artifacts.filter((artifact) => {
    const key = artifactContentKey(artifact)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function artifactFileName(artifact: Artifact): string {
  const original = artifact.metadata?.original_filename
  if (typeof original === 'string' && original.trim()) return original.trim()
  const parts = String(artifact.path || artifact.label || '').split(/[\\/]/)
  return parts[parts.length - 1] || artifact.label
}

function stripExtension(name: string): string {
  return name.replace(/\.[^.]+$/, '')
}

function artifactSourceStem(artifact: Artifact): string {
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

function artifactDateLabel(artifact: Artifact): string {
  const date = new Date(artifact.created_at)
  if (Number.isNaN(date.getTime())) return ''
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function artifactKindLabel(artifact: Artifact): string {
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

function artifactLanguageLabel(artifact: Artifact): string {
  const single = normalizeLanguageCode(artifact.metadata?.language)
  if (single) return languageSpec(single).short
  const multiple = normalizeLanguageArray(artifact.metadata?.languages)
  return multiple.map((lang) => languageSpec(lang).short).join('/')
}

function artifactPickerLabel(artifact: Artifact): string {
  const parts = [artifactKindLabel(artifact), artifactLanguageLabel(artifact), artifactSourceStem(artifact), artifactDateLabel(artifact)]
    .map((item) => item.trim())
    .filter(Boolean)
  return [...new Set(parts)].join('｜')
}

function artifactPickerKey(artifact: Artifact): string {
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

function isPickerProcessArtifact(artifact: Artifact): boolean {
  return artifact.kind === 'glossary_detail'
}

function pickerArtifacts(artifacts: Artifact[]): Artifact[] {
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

function isAnnouncementSourceDocument(artifact: Artifact): boolean {
  const name = artifactFileName(artifact).toLowerCase()
  return /\.(docx|txt|xlsx)$/.test(name)
}

function isGeneratedAnnouncementTermsArtifact(artifact: Artifact): boolean {
  if (artifact.kind === 'announcement_terms_workbook') return true
  const original = artifact.metadata?.original_filename
  const text = [artifact.label, artifact.path, typeof original === 'string' ? original : ''].join(' ').toLowerCase()
  return artifact.kind === 'language_table' && (text.includes('announcement_terms') || text.includes('公告术语'))
}

function runArtifacts(project: Project, runId: string | undefined): Artifact[] {
  if (!runId) return []
  return (project.artifacts || []).filter((artifact) => artifact.run_id === runId)
}

function artifactRole(artifact: Artifact): string {
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

function artifactsByRole(project: Project, role: string): Artifact[] {
  return (project.artifacts || []).filter((artifact) => artifactRole(artifact) === role)
}

function artifactsByRoles(project: Project, roles: string | string[]): Artifact[] {
  const accepted = Array.isArray(roles) ? roles : [roles]
  return (project.artifacts || []).filter((artifact) => accepted.includes(artifactRole(artifact)))
}

function apiErrorText(text: string, fallback: string): string {
  if (!text.trim()) return fallback
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown }
    const detail = payload.detail ?? payload.message ?? payload.error
    if (typeof detail === 'string' && detail.trim()) return detail
  } catch {
    // Keep the original text when the backend returns plain text.
  }
  return text
}

function errorText(error: unknown): string {
  if (error instanceof Error) return apiErrorText(error.message, error.message)
  return String(error)
}

function clampBatchSize(value: number): number {
  if (!Number.isFinite(value)) return 90
  return Math.max(1, Math.min(200, Math.round(value)))
}

function effectiveBatchSize(settings: AppSettings | null | undefined, fallback = 90): number {
  return clampBatchSize(Number(settings?.batch_size || fallback))
}

function estimateBatches(rows: number | undefined, batchSize: number): number {
  const total = Number(rows || 0)
  return total > 0 ? Math.ceil(total / Math.max(1, batchSize)) : 0
}

function getTranslationProgress(run: Run | null): TranslationProgress | null {
  const progress = run?.metadata?.translation_progress
  if (!progress || typeof progress !== 'object') return null
  return progress as TranslationProgress
}

function canSkipModelTranslation(readiness: TranslationReadiness | null | undefined): boolean {
  if (!readiness || readiness.source_rows <= 0) return false
  if (readiness.ready_for_qa) return true
  if (readiness.empty_target_rows > 0 || readiness.translated_rows <= 0) return false
  const cjkLimit = Math.max(5, Math.ceil(readiness.source_rows * 0.01))
  return readiness.translated_rows >= readiness.source_rows * 0.8 && readiness.cjk_target_rows <= cjkLimit
}

function latestRunOfKind(project: Project, kind: string): Run | null {
  return (project.runs || []).find((run) => run.kind === kind) || null
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return '首批完成后估算'
  const value = Math.max(0, Math.round(Number(seconds)))
  const hours = Math.floor(value / 3600)
  const minutes = Math.floor((value % 3600) / 60)
  const secs = value % 60
  if (hours) return `${hours}h ${minutes}m`
  if (minutes) return `${minutes}m ${secs}s`
  return `${secs}s`
}

function normalizeGlossaryNote(value: string | undefined): string {
  const note = String(value || '')
  if (/高频词扫描补全 (EN|JP|JA|KR|KO)\/(EN2|JP2|JA2|KR2|KO2)\?+/.test(note)) return '高频词候选，需人工确认'
  return note
}

function formatDate(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toISOString().slice(0, 10)
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function shortRunId(runId?: string): string {
  return (runId || '').replace(/^run_/, '').slice(0, 6) || '-'
}

function fieldText(value: unknown, fallback = '未生成'): string {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item).trim()).filter(Boolean)
    return items.length ? items.join('、') : fallback
  }
  if (value === null || value === undefined) return fallback
  const text = String(value).trim()
  return text || fallback
}

function profileText(project: Project, key: string, fallback = '未生成'): string {
  return fieldText(project.profile?.[key], fallback)
}

function fixedTermsSummary(project: Project): string {
  const terms = getProjectHarness(project).fixed_terms || []
  if (!terms.length) return '未设置'
  return terms
    .slice(0, 5)
    .map((term) => [term.source, term.target].filter(Boolean).join(' => '))
    .filter(Boolean)
    .join('；') || '未设置'
}

function ruleSummary(project: Project): string {
  const harness = getProjectHarness(project)
  const hard = (harness.hard_rules || []).length
  const soft = (harness.soft_rules || []).length
  if (!hard && !soft) return '未设置'
  return `必须规则 ${hard} 条，建议规则 ${soft} 条`
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(apiErrorText(text, response.statusText))
  }
  return response.json()
}

function compactSummary(summary: Record<string, unknown>): string {
  return Object.entries(summary)
    .filter(([, value]) => value !== undefined && value !== null && typeof value !== 'object')
    .slice(0, 4)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(' / ')
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [currentId, setCurrentId] = useState<string>('')
  const [view, setView] = useState<AppView>('overview')
  const [tab, setTab] = useState<ProjectTab>('meta')
  const [step, setStep] = useState(1)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [deleteProjectTarget, setDeleteProjectTarget] = useState<Project | null>(null)
  const [deleteHoldProjectId, setDeleteHoldProjectId] = useState('')
  const deleteHoldTimer = useRef<number | null>(null)
  const longPressTriggeredProjectId = useRef('')
  const [announcementCancelTarget, setAnnouncementCancelTarget] = useState<AnnouncementTask | null>(null)
  const [announcementCancelHoldTaskId, setAnnouncementCancelHoldTaskId] = useState('')
  const announcementCancelHoldTimer = useRef<number | null>(null)
  const longPressTriggeredAnnouncementTaskId = useRef('')
  const [announcementFocusTaskId, setAnnouncementFocusTaskId] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [freqOpen, setFreqOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('准备就绪')
  const [intro, setIntro] = useState('')
  const [sourceArtifact, setSourceArtifact] = useState<Artifact | null>(null)
  const [termArtifact, setTermArtifact] = useState<Artifact | null>(null)
  const [qaArtifact, setQaArtifact] = useState<Artifact | null>(null)
  const [archiveArtifact, setArchiveArtifact] = useState<Artifact | null>(null)
  const [assetArtifacts, setAssetArtifacts] = useState<Artifact[]>([])
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [selectedLanguage, setSelectedLanguage] = useState<LanguageCode>('en')
  const [glossaryPreview, setGlossaryPreview] = useState<GlossaryPreviewRow[]>([])
  const [glossaryBatches, setGlossaryBatches] = useState<GlossaryBatch[]>([])
  const [glossaryCandidates, setGlossaryCandidates] = useState<GlossaryCandidate[]>([])
  const [qualityIssues, setQualityIssues] = useState<QualityIssue[]>([])
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [deliverables, setDeliverables] = useState<DeliverableTask[]>([])
  const [translationReadiness, setTranslationReadiness] = useState<TranslationReadiness | null>(null)
  const translationBatchSize = 90
  const [announcementText, setAnnouncementText] = useState('')
  const [announcementLookupResult, setAnnouncementLookupResult] = useState<AnnouncementLookupResult | null>(null)

  useEffect(() => {
    refreshProjects()
    refreshSettings()
  }, [])

  const current = useMemo(() => projects.find((p) => p.id === currentId), [projects, currentId])
  const currentScoped = useMemo(() => current ? scopeProjectToLanguage(current, selectedLanguage) : undefined, [current, selectedLanguage])
  const currentLang = languageSpec(selectedLanguage)

  useEffect(() => {
    return () => {
      if (deleteHoldTimer.current !== null) window.clearTimeout(deleteHoldTimer.current)
      if (announcementCancelHoldTimer.current !== null) window.clearTimeout(announcementCancelHoldTimer.current)
    }
  }, [])

  useEffect(() => {
    if (currentId) refreshCurrent()
  }, [currentId])

  useEffect(() => {
    if (!current) return
    setIntro(current.description || '')
    setAnnouncementText('')
    setAnnouncementLookupResult(null)
  }, [currentId])

  useEffect(() => {
    if (!current) {
      setSourceArtifact(null)
      setTermArtifact(null)
      setQaArtifact(null)
      setArchiveArtifact(null)
      setAssetArtifacts([])
      setLatestRun(null)
      setGlossaryPreview([])
      setGlossaryBatches([])
      setGlossaryCandidates([])
      setQualityIssues([])
      setDeliverables([])
      setAnnouncementText('')
      setAnnouncementLookupResult(null)
      return
    }
    const artifacts = current.artifacts || []
    const latestProjectRun = (current.runs || [])[0] || null
    const hydratedRun = latestProjectRun ? { ...latestProjectRun, artifacts: runArtifacts(current, latestProjectRun.id) } : null
    setSourceArtifact(artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['language_table']))
    setTermArtifact(artifactsByRole(current, 'glossary_curated')[0] || artifactsByRole(current, 'glossary_source')[0] || newestArtifact(artifacts, ['glossary_final', 'term_base']))
    setQaArtifact(artifactsByRole(current, 'translation_workbook')[0] || newestArtifact(artifacts, ['final_workbook']))
    setArchiveArtifact(artifactsByRole(current, 'translation_workbook')[0] || artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['final_workbook', 'language_table']))
    setAssetArtifacts(uniqueArtifactsByContent(artifacts.filter((artifact) => artifact.kind === 'asset')))
    setLatestRun(hydratedRun)
    setDeliverables([])
  }, [current?.id, current?.artifacts?.length, current?.runs?.length])

  useEffect(() => {
    if (current?.id) refreshGlossaryBatches(current.id)
  }, [current?.id, latestRun?.id, selectedLanguage])

  useEffect(() => {
    if (current?.id && tab === 'delivery') {
      refreshDeliverables()
    }
  }, [current?.id, current?.runs?.length, tab, selectedLanguage])

  useEffect(() => {
    if (!sourceArtifact?.id) {
      setTranslationReadiness(null)
      return
    }
    refreshTranslationReadiness(sourceArtifact.id)
  }, [sourceArtifact?.id, settings?.batch_size, selectedLanguage])

  useEffect(() => {
    if (!qaArtifact && sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness)) {
      setQaArtifact(sourceArtifact)
    }
  }, [qaArtifact?.id, sourceArtifact?.id, translationReadiness?.artifact_id, translationReadiness?.ready_for_qa, translationReadiness?.translated_rows, translationReadiness?.empty_target_rows, translationReadiness?.cjk_target_rows])

  useEffect(() => {
    if (!latestRun || !['failed', 'needs_input'].includes(latestRun.status)) {
      setQualityIssues([])
      return
    }
    loadQualityIssues(latestRun.id)
  }, [latestRun?.id, latestRun?.status])

  useEffect(() => {
    if (!latestRun || !['queued', 'running'].includes(latestRun.status)) return
    const poller = window.setInterval(async () => {
      try {
        const updated = await api<Run>(`/api/runs/${latestRun.id}`)
        setLatestRun(updated)
        const latestEvent = updated.events?.[updated.events.length - 1]
        if (updated.kind === 'translation' && updated.status === 'passed') {
          setStatus(`${languageSpec(normalizeLanguageCode(updated.language) || selectedLanguage).short} 翻译和 QA 已通过，最终产物已归档。`)
        } else if (latestEvent?.message) {
          setStatus(`后台任务${updated.status}：${latestEvent.message}`)
        }
        if (!['queued', 'running'].includes(updated.status)) {
          await refreshCurrent()
          if (tab === 'delivery') await refreshDeliverables()
        }
      } catch (error) {
        setStatus(`后台任务进度刷新失败：${errorText(error)}`)
      }
    }, 2000)
    return () => window.clearInterval(poller)
  }, [latestRun?.id, latestRun?.status, tab])

  useEffect(() => {
    if (!current?.announcement_tasks?.some((task) => ['queued', 'running'].includes(task.status))) return
    const poller = window.setInterval(() => {
      refreshCurrent()
    }, 2500)
    return () => window.clearInterval(poller)
  }, [current?.id, current?.announcement_tasks?.map((task) => `${task.id}:${task.status}`).join('|')])

  function cancelProjectDeleteHold() {
    if (deleteHoldTimer.current !== null) {
      window.clearTimeout(deleteHoldTimer.current)
      deleteHoldTimer.current = null
    }
    setDeleteHoldProjectId('')
  }

  function beginProjectDeleteHold(project: Project) {
    if (busy) return
    cancelProjectDeleteHold()
    setDeleteHoldProjectId(project.id)
    deleteHoldTimer.current = window.setTimeout(() => {
      longPressTriggeredProjectId.current = project.id
      deleteHoldTimer.current = null
      setDeleteHoldProjectId('')
      setDeleteProjectTarget(project)
    }, 850)
  }

  function selectProject(project: Project, event: React.MouseEvent<HTMLButtonElement>) {
    if (longPressTriggeredProjectId.current === project.id) {
      event.preventDefault()
      longPressTriggeredProjectId.current = ''
      return
    }
    setCurrentId(project.id)
    setView('overview')
  }

  async function deleteProject(project: Project) {
    setBusy(true)
    setStatus(`正在删除项目“${project.name}”...`)
    try {
      await api(`/api/projects/${project.id}`, { method: 'DELETE' })
      const loaded = await api<Project[]>('/api/projects')
      const nextId = loaded.some((item) => item.id === currentId) ? currentId : loaded[0]?.id || ''
      setProjects(loaded)
      setCurrentId(nextId)
      if (project.id === currentId) {
        setView('overview')
        setTab('meta')
      }
      longPressTriggeredProjectId.current = ''
      setDeleteProjectTarget(null)
      setStatus(`项目“${project.name}”已删除`)
    } catch (error) {
      setStatus(`删除项目失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  function cancelAnnouncementCancelHold() {
    if (announcementCancelHoldTimer.current !== null) {
      window.clearTimeout(announcementCancelHoldTimer.current)
      announcementCancelHoldTimer.current = null
    }
    setAnnouncementCancelHoldTaskId('')
  }

  function beginAnnouncementCancelHold(task: AnnouncementTask) {
    if (busy) return
    cancelAnnouncementCancelHold()
    setAnnouncementCancelHoldTaskId(task.id)
    announcementCancelHoldTimer.current = window.setTimeout(() => {
      longPressTriggeredAnnouncementTaskId.current = task.id
      announcementCancelHoldTimer.current = null
      setAnnouncementCancelHoldTaskId('')
      setAnnouncementCancelTarget(task)
    }, 850)
  }

  function openAnnouncementTask(task?: AnnouncementTask) {
    if (task && longPressTriggeredAnnouncementTaskId.current === task.id) {
      longPressTriggeredAnnouncementTaskId.current = ''
      return
    }
    setAnnouncementFocusTaskId(task?.id || '')
    setView('announcement')
  }

  async function cancelAnnouncementTask(task: AnnouncementTask) {
    setBusy(true)
    setStatus(`正在取消公告任务“${task.title || task.id}”...`)
    try {
      await api(`/api/announcement-tasks/${task.id}/cancel`, { method: 'POST' })
      await refreshCurrent()
      if (announcementFocusTaskId === task.id) setAnnouncementFocusTaskId('')
      longPressTriggeredAnnouncementTaskId.current = ''
      setAnnouncementCancelTarget(null)
      setStatus(`公告任务“${task.title || task.id}”已取消`)
    } catch (error) {
      setStatus(`取消公告任务失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function refreshProjects(selectId?: string) {
    const loaded = await api<Project[]>('/api/projects')
    setProjects(loaded)
    setCurrentId(selectId || currentId || loaded[0]?.id || '')
  }

  async function refreshCurrent() {
    if (!currentId) return
    const loaded = await api<Project>(`/api/projects/${currentId}`)
    setProjects((prev) => prev.map((p) => (p.id === loaded.id ? loaded : p)))
  }

  async function refreshGlossaryBatches(projectId = currentId) {
    if (!projectId) return
    const loaded = await api<{ batches: GlossaryBatch[]; active_batch: GlossaryBatch | null; candidates: GlossaryCandidate[] }>(`/api/projects/${projectId}/glossary/batches?${languageQuery(selectedLanguage)}`)
    setGlossaryBatches(loaded.batches || [])
    setGlossaryCandidates(loaded.candidates || [])
  }

  async function refreshSettings() {
    setSettings(await api<AppSettings>('/api/settings'))
  }

  async function saveProjectMeta(updates: Partial<Project>) {
    if (!current) return
    await api<Project>(`/api/projects/${current.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
    setStatus('项目元信息已保存')
  }

  async function loadQualityIssues(runId: string) {
    try {
      const result = await api<{ issues: QualityIssue[] }>(`/api/runs/${runId}/quality-issues`)
      setQualityIssues(result.issues)
    } catch (error) {
      setStatus(`QA issue load failed: ${errorText(error)}`)
    }
  }

  async function createProject(form: FormData) {
    const created = await api<Project>('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: form.get('name'),
        type: form.get('type'),
        icon: form.get('icon') || '🎮',
        description: form.get('description') || ''
      })
    })
    setNewProjectOpen(false)
    await refreshProjects(created.id)
    setView('overview')
    setTab('meta')
    setStatus(created.duplicate ? `项目“${created.name}”已存在，已切换到已有项目。` : `项目“${created.name}”已创建。`)
  }

  async function upload(file: File, kind: string) {
    if (!current) return null
    setBusy(true)
    setStatus(`正在上传：${file.name}`)
    try {
      const data = new FormData()
      data.append('file', file)
      const artifact = await api<Artifact>(`/api/projects/${current.id}/files?kind=${kind}`, {
        method: 'POST',
        body: data
      })
      await refreshCurrent()
      if (artifact.duplicate) {
        setStatus(`已存在，已复用：${artifactPickerLabel(artifact)}`)
      } else {
        setStatus(`已上传：${artifactPickerLabel(artifact)}`)
      }
      return artifact
    } catch (error) {
      setStatus(`上传失败：${errorText(error)}`)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function runAnalysis() {
    if (!current) return
    setBusy(true)
    setStatus('正在生成项目 profile 和翻译提示词...')
    try {
      await api(`/api/projects/${current.id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intro: intro.trim() || current.description || `${current.name} ${current.type}`,
          asset_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
          target_language: selectedLanguage
        })
      })
      await refreshCurrent()
      setStatus(`${currentLang.short} 项目提示词已生成`)
    } catch (error) {
      setStatus(`项目分析失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function runGlossaryExtract() {
    if (!current || !sourceArtifact) return
    setBusy(true)
    setStatus('正在提取术语并生成 project brief...')
    try {
      const result = await api<{
        run: Run
        artifacts: Artifact[]
        glossary_backfill?: {
          candidates?: number
          unique_candidates?: number
          inserted?: number
          updated?: number
          skipped_existing?: number
          skipped_duplicate?: number
          conflicts?: number
          pending_confirmation?: number
        }
      }>(`/api/projects/${current.id}/glossary/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: sourceArtifact.id,
          project_name: current.name,
          source_only: false,
          id_column: 'ID',
          source_column: 'cn',
          target_column: currentLang.targetHeader,
          language: selectedLanguage,
          project_material_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
          project_notes: [intro.trim() || current.description || `${current.name} ${current.type}`].filter(Boolean),
          include_empty_final_terms: true
        })
      })
      setTermArtifact(result.artifacts.find((a) => a.kind === 'glossary_final') || null)
      setLatestRun(result.run)
      await refreshCurrent()
      await refreshGlossaryBatches(current.id)
      const backfill = result.glossary_backfill || {}
      const pendingConfirmation = backfill.pending_confirmation ?? backfill.inserted ?? 0
      setStatus(`术语扫描完成：候选 ${backfill.candidates ?? 0}，按中文去重后 ${backfill.unique_candidates ?? 0}，已在库中跳过 ${backfill.skipped_existing ?? 0}，新增待审核 ${pendingConfirmation}，重复跳过 ${backfill.skipped_duplicate ?? 0}`)
    } catch (error) {
      setStatus(`术语提取失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function previewGlossaryImport() {
    if (!current || !termArtifact) return
    setBusy(true)
    setStatus('正在预览术语表...')
    try {
      const result = await api<{ rows: GlossaryPreviewRow[]; languages?: LanguageCode[] }>(`/api/projects/${current.id}/glossary/import-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: termArtifact.id, language: selectedLanguage })
      })
      setGlossaryPreview(result.rows)
      const languageText = result.languages?.length ? `（${result.languages.map((item) => item.toUpperCase()).join('/')}）` : ''
      setStatus(`术语表预览完成：${result.rows.length} 条${languageText}`)
    } catch (error) {
      setStatus(`术语表预览失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function importGlossaryArtifact() {
    if (!current || !termArtifact) return
    setBusy(true)
    setStatus('正在导入术语表...')
    try {
      const result = await api<{ imported_count: number; languages?: LanguageCode[] }>(`/api/projects/${current.id}/glossary/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: termArtifact.id, language: selectedLanguage })
      })
      await refreshCurrent()
      const languageText = result.languages?.length ? `（${result.languages.map((item) => item.toUpperCase()).join('/')}）` : ''
      setStatus(`术语表已导入：${result.imported_count} 条${languageText}`)
    } catch (error) {
      setStatus(`术语表导入失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function refreshTranslationReadiness(artifactId: string) {
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    try {
      const result = await api<TranslationReadiness>(`/api/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}&${languageQuery(selectedLanguage)}`)
      setTranslationReadiness(result)
      return result
    } catch {
      setTranslationReadiness(null)
      return null
    }
  }

  async function inspectTranslationTargets(artifactId: string): Promise<TranslationTargets | null> {
    try {
      const result = await api<TranslationTargets>(`/api/artifacts/${artifactId}/translation-targets`)
      const languages = normalizeLanguageArray(result.detected_languages)
      return { ...result, detected_languages: languages, suggested_language: normalizeLanguageCode(result.suggested_language) }
    } catch (error) {
      setStatus(`语言识别失败：${errorText(error)}`)
      return null
    }
  }

  async function startQuickTask(payload: { inputArtifact: Artifact; referenceArtifacts: Artifact[]; objective: 'translate' | 'qa'; language: LanguageCode }): Promise<Run | null> {
    if (!current) return null
    const { inputArtifact, referenceArtifacts, objective, language } = payload
    const referenceArtifactIds = referenceArtifacts.map((artifact) => artifact.id)
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    setBusy(true)
    setStatus(objective === 'qa' ? `快速校对准备中：${languageSpec(language).short}` : `快速翻译准备中：${languageSpec(language).short}`)
    try {
      if (objective === 'qa') {
        const run = await api<Run>('/api/runs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: current.id,
            kind: 'qa',
            language,
            input_artifact_id: inputArtifact.id,
            term_artifact_id: termArtifact?.id || null,
            reference_artifact_ids: referenceArtifactIds,
            task_origin: 'quick_task',
            task_code: 'QA'
          })
        })
        const result = await api<{ run: Run; artifacts: Artifact[]; quality_summary?: Record<string, unknown> }>(`/api/runs/${run.id}/qa`, { method: 'POST' })
        const hydrated = { ...result.run, artifacts: result.artifacts }
        setLatestRun(hydrated)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        setStatus(result.run.status === 'passed' ? '快速校对已通过，可在交付页生成最终文件。' : `快速校对结束：${result.run.status}`)
        return hydrated
      }

      const readiness = await api<TranslationReadiness>(`/api/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      if (canSkipModelTranslation(readiness)) {
        setStatus(`已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文；建议切换为“校对”直接跑 QA。`)
        return null
      }
      const blockReason = formalTranslationBlockReason(settings, inputArtifact, current, readiness)
      if (blockReason) {
        setStatus(`无法开始快速翻译：${blockReason}`)
        return null
      }
      const run = await api<Run>('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: current.id,
          kind: 'translation',
          language,
          input_artifact_id: inputArtifact.id,
          term_artifact_id: termArtifact?.id || null,
          reference_artifact_ids: referenceArtifactIds,
          batch_size: batchSize,
          task_origin: 'quick_task',
          task_code: 'T'
        })
      })
      setLatestRun(run)
      const started = await api<Run>(`/api/runs/${run.id}/translate/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize })
      })
      setLatestRun(started)
      setStatus(`快速翻译已进入后台：${languageSpec(language).short} · ${readiness.source_rows} 行 · 预计 ${readiness.estimated_batches || '-'} 批。`)
      return started
    } catch (error) {
      setStatus(`快速任务失败：${errorText(error)}`)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function runTranslate(taskCode: 'A' | 'T' = 'T') {
    if (!current || !sourceArtifact) return
    const selectedBatchSize = effectiveBatchSize(settings, translationBatchSize)
    const readiness = translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === selectedBatchSize
      ? translationReadiness
      : await refreshTranslationReadiness(sourceArtifact.id)
    if (readiness && canSkipModelTranslation(readiness)) {
      setQaArtifact(sourceArtifact)
      setStep(8)
      setStatus(`已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文，无需模型翻译，请直接运行 QA。`)
      return
    }
    const blockReason = formalTranslationBlockReason(settings, sourceArtifact, current, readiness)
    if (blockReason) {
      setStatus(`无法开始翻译：${blockReason}`)
      return
    }
    setBusy(true)
    setStatus(`${currentLang.short} 翻译前检查通过，准备分批翻译：${readiness?.source_rows || 0} 行，预计 ${readiness?.estimated_batches || '-'} 批。`)
    try {
      const batchSize = selectedBatchSize
      const resumableRun = latestRun?.kind === 'translation'
        && ['failed', 'needs_input', 'canceled'].includes(latestRun.status)
        && latestRun.language === selectedLanguage
        && latestRun.metadata?.input_artifact_id === sourceArtifact.id
        ? latestRun
        : null
      const run = resumableRun || await api<Run>('/api/runs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: current.id,
            kind: 'translation',
            language: selectedLanguage,
            input_artifact_id: sourceArtifact.id,
            term_artifact_id: termArtifact?.id || null,
            batch_size: batchSize,
            task_code: taskCode
          })
        })
      setLatestRun(run)
      const needsBudgetConfirm = run.metadata?.reason === 'api_budget_confirmation_required'
      const confirmedBudget = needsBudgetConfirm
        ? window.confirm('该任务预计 API token 用量超过设置的提醒阈值。确认后会从已完成批次继续，不会重跑已落盘批次。是否继续？')
        : false
      if (needsBudgetConfirm && !confirmedBudget) {
        setStatus('已暂停：等待确认 API 用量预算后继续。')
        return
      }
      const endpoint = resumableRun ? 'resume' : 'start'
      const started = await api<Run>(`/api/runs/${run.id}/translate/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize, confirm_api_budget: confirmedBudget })
      })
      setLatestRun(started)
      setStatus(`${currentLang.short} 翻译已进入后台队列：系统会自动拆批、限流、落盘和续跑。`)
    } catch (error) {
      setStatus(`翻译失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function cancelTranslateRun() {
    if (!latestRun || latestRun.kind !== 'translation') return
    setBusy(true)
    setStatus('正在取消后台翻译任务...')
    try {
      const canceled = await api<Run>(`/api/runs/${latestRun.id}/translate/cancel`, { method: 'POST' })
      setLatestRun(canceled)
      setStatus('已请求取消：当前已完成批次会保留，后续可继续。')
    } catch (error) {
      setStatus(`取消翻译失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function runDirectQA(taskCode: 'QA' = 'QA') {
    if (!current || !qaArtifact) return
    if (artifactRole(qaArtifact) === 'language_source') {
      const readiness = await refreshTranslationReadiness(qaArtifact.id)
      if (!canSkipModelTranslation(readiness)) {
        setSourceArtifact(qaArtifact)
        setStep(7)
        setStatus('这份语言表还不像完整译文表：请先进入模型翻译补齐空译文或明显非目标语言内容，再运行 QA。')
        return
      }
    }
    const sourceRunId = qaArtifact.run_id && (current.runs || []).some((run) => run.id === qaArtifact.run_id && run.kind === 'translation')
      ? qaArtifact.run_id
      : null
    setBusy(true)
    setStatus('正在对已有译文 workbook 执行 QA...')
    try {
      const run = await api<Run>('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: current.id,
          kind: 'qa',
          language: selectedLanguage,
          input_artifact_id: qaArtifact.id,
          term_artifact_id: termArtifact?.id || null,
          task_origin: sourceRunId ? 'translation_continuation' : 'direct_import',
          source_run_id: sourceRunId,
          task_code: taskCode
        })
      })
      const result = await api<{ run: Run; artifacts: Artifact[]; quality_summary?: Record<string, unknown> }>(`/api/runs/${run.id}/qa`, {
        method: 'POST'
      })
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      await refreshCurrent()
      if (tab === 'delivery') await refreshDeliverables()
      setStatus(result.run.status === 'passed' ? '已有译文 QA 通过' : `已有译文 QA 结束：${result.run.status}`)
    } catch (error) {
      setStatus(`已有译文 QA 失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function applyManualFixes(fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) {
    if (!current || !latestRun || !fixes.length) return
    setBusy(true)
    setStatus('正在保存手工修复并重新 QA...')
    try {
      const result = await api<{
        fixed_artifact: Artifact
        manual_fixes: Record<string, unknown>[]
        qa_result?: { run: Run; artifacts: Artifact[]; quality_summary?: Record<string, unknown> }
      }>(`/api/runs/${latestRun.id}/manual-fixes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fixes, rerun_qa: true })
      })
      if (result.qa_result) {
        setLatestRun({ ...result.qa_result.run, artifacts: result.qa_result.artifacts })
        setQualityIssues([])
        setStatus(`手工修复已重新 QA：${result.qa_result.run.status}`)
      } else {
        setQaArtifact(result.fixed_artifact)
        setStatus('手工修复已保存，等待重新 QA')
      }
      await refreshCurrent()
    } catch (error) {
      setStatus(`手工修复失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function applyModelFixes() {
    if (!current || !latestRun) return
    setBusy(true)
    setStatus('正在调用模型修复 QA 问题并重新校对...')
    try {
      const result = await api<{
        fixed_artifact: Artifact
        model_fixes: Record<string, unknown>[]
        qa_result?: { run: Run; artifacts: Artifact[]; quality_summary?: Record<string, unknown> }
      }>(`/api/runs/${latestRun.id}/model-fixes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_issues: 80, rerun_qa: true })
      })
      if (result.qa_result) {
        setLatestRun({ ...result.qa_result.run, artifacts: result.qa_result.artifacts })
        setQualityIssues([])
        setStatus(`模型已修复 ${result.model_fixes.length} 条并重新 QA：${result.qa_result.run.status}`)
      } else {
        setQaArtifact(result.fixed_artifact)
        setStatus(`模型已修复 ${result.model_fixes.length} 条，等待重新 QA`)
      }
      await refreshCurrent()
    } catch (error) {
      setStatus(`模型修复失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function uploadAsset(file: File) {
    const artifact = await upload(file, 'asset')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `参考素材已存在，已复用：${artifactPickerLabel(artifact)}` : `参考素材已归档：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function uploadAnnouncementResponse(file: File) {
    const artifact = await upload(file, 'asset')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `AI response 已存在，已复用：${artifactPickerLabel(artifact)}` : `AI response 已上传：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function uploadAnnouncementConstraint(file: File) {
    const artifact = await upload(file, 'language_table')
    if (artifact) {
      setStatus(artifact.duplicate ? `约束文件已存在，已复用：${artifactPickerLabel(artifact)}` : `公告约束文件已归档：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function uploadAnnouncementTermsFile(file: File) {
    const artifact = await upload(file, 'announcement_terms_workbook')
    if (artifact) {
      setStatus(artifact.duplicate ? `公告术语表已存在，已复用：${artifactPickerLabel(artifact)}` : `公告术语表已上传：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function createAnnouncementTask(payload: Record<string, unknown>) {
    if (!current) return null
    setBusy(true)
    setStatus('正在创建公告任务...')
    try {
      const task = await api<AnnouncementTask>(`/api/projects/${current.id}/announcement-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      await refreshCurrent()
      setStatus(`公告任务已创建：${task.title || task.id}`)
      return task
    } catch (error) {
      setStatus(`公告任务创建失败：${errorText(error)}`)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function runAnnouncementTaskAction(taskId: string, endpoint: string, payload: Record<string, unknown> = {}) {
    if (!current) return null
    setBusy(true)
    setStatus(`正在执行公告任务：${endpoint}...`)
    try {
      const result = await api<AnnouncementTaskResult>(`/api/announcement-tasks/${taskId}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (result.run) setLatestRun({ ...result.run, artifacts: result.artifacts || [] })
      await refreshCurrent()
      const summary = result.summary ? ` · ${compactSummary(result.summary)}` : ''
      setStatus(`公告任务完成：${endpoint}${summary}`)
      return result
    } catch (error) {
      setStatus(`公告任务失败：${errorText(error)}`)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function runAnnouncementLookup(text: string, materialArtifactIds: string[], options: AnnouncementLookupOptions) {
    if (!current) return
    if (!text.trim() && !materialArtifactIds.length) {
      setStatus('请先上传/选择公告素材，或直接输入公告长文本。')
      return
    }
    setBusy(true)
    setStatus(`正在生成 ${currentLang.short} 公告检索包...`)
    try {
      const result = await api<AnnouncementLookupResult>(`/api/projects/${current.id}/announcement-lookup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          material_artifact_ids: materialArtifactIds,
          language: selectedLanguage,
          include_glossary: options.includeGlossary,
          include_translation_archive: options.includeTranslationArchive
        })
      })
      setAnnouncementLookupResult(result)
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      await refreshCurrent()
      setStatus(`公告检索包完成：命中术语 ${result.summary.matched_terms} 条，译文参考 ${result.summary.matched_translations} 条。`)
    } catch (error) {
      setStatus(`公告检索包生成失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function addGlossaryTerm(form: FormData) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        term_key: form.get('term_key') || '',
        source: form.get('source'),
        target: form.get('target'),
        target_alt: form.get('target_alt') || '',
        language: form.get('language') || selectedLanguage,
        category: form.get('category') || 'manual',
        note: form.get('note') || '',
        source_type: 'manual',
        confirmed: true
      })
    })
    await refreshCurrent()
    setStatus('词条已新增')
  }

  async function updateGlossaryTerm(term: GlossaryTerm, updates: Partial<GlossaryTerm>) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary/${term.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
    setStatus('词条已保存')
  }

  async function updateGlossaryCandidate(candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary/candidates/${candidate.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshGlossaryBatches(current.id)
    setStatus('候选词条已保存')
  }

  async function translateMissingGlossaryCandidates(batchId: string) {
    if (!current || !batchId) return
    setBusy(true)
    setStatus(`正在补齐缺失 ${currentLang.short} 译文...`)
    try {
      const result = await api<{ translated_count: number; skipped_count: number }>(`/api/projects/${current.id}/glossary/batches/${batchId}/translate-missing`, {
        method: 'POST'
      })
      await refreshGlossaryBatches(current.id)
      setStatus(`候选译文已补齐 ${result.translated_count} 条，跳过已有译文 ${result.skipped_count} 条；请人工审核后加入术语库。`)
    } catch (error) {
      setStatus(`候选译文补齐失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function resolveGlossaryCandidates(batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') {
    if (!current || !batchId || !candidates.length) return
    setBusy(true)
    setStatus(action === 'accept' ? `正在确认加入 ${candidates.length} 条术语...` : `正在跳过 ${candidates.length} 条候选...`)
    try {
      await api(`/api/projects/${current.id}/glossary/batches/${batchId}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_ids: candidates.map((candidate) => candidate.id) })
      })
      await refreshCurrent()
      await refreshGlossaryBatches(current.id)
      setStatus(action === 'accept' ? `已加入 ${candidates.length} 条术语，后续翻译和 QA 会使用项目术语库。` : `已跳过 ${candidates.length} 条候选，不会进入项目术语库。`)
    } catch (error) {
      setStatus(`术语批次处理失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function deleteGlossaryTerm(term: GlossaryTerm) {
    if (!current) return
    await api(`/api/projects/${current.id}/glossary/${term.id}`, { method: 'DELETE' })
    await refreshCurrent()
    setStatus('词条已删除')
  }

  async function addTranslationEntry(form: FormData) {
    if (!current) return
    await api(`/api/projects/${current.id}/translations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entry_key: String(form.get('entry_key') || ''),
        source: String(form.get('source') || ''),
        target: String(form.get('target') || ''),
        target_alt: String(form.get('target_alt') || ''),
        language: form.get('language') || selectedLanguage,
        note: String(form.get('note') || ''),
        source_type: 'manual'
      })
    })
    await refreshCurrent()
    setStatus('译文条目已保存')
  }

  async function updateTranslationEntry(entry: TranslationEntry, updates: Partial<TranslationEntry>) {
    if (!current) return
    await api(`/api/projects/${current.id}/translations/${entry.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
    setStatus('译文条目已保存')
  }

  async function deleteTranslationEntry(entry: TranslationEntry) {
    if (!current) return
    await api(`/api/projects/${current.id}/translations/${entry.id}`, { method: 'DELETE' })
    await refreshCurrent()
    setStatus('译文条目已删除')
  }

  async function uploadArchiveWorkbook(file: File) {
    const artifact = await upload(file, 'final_workbook')
    if (artifact) setArchiveArtifact(artifact)
  }

  async function importTranslationArchive() {
    if (!current || !archiveArtifact) return
    setBusy(true)
    setStatus('正在导入译文归档...')
    try {
      const result = await api<{ imported_count: number; languages?: LanguageCode[] }>(`/api/projects/${current.id}/translations/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: archiveArtifact.id, language: selectedLanguage })
      })
      await refreshCurrent()
      const languageText = result.languages?.length ? `（${result.languages.map((item) => item.toUpperCase()).join('/')}）` : ''
      setStatus(`译文归档已导入：${result.imported_count} 条${languageText}`)
    } catch (error) {
      setStatus(`译文归档导入失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function saveHarness(updates: Partial<ProjectHarness>) {
    if (!current) return
    await api(`/api/projects/${current.id}/harness`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshCurrent()
    setStatus('项目规则已保存，仅对当前项目生效')
  }

  async function uploadTranslationWorkbook(file: File) {
    const artifact = await upload(file, 'final_workbook')
    if (artifact) {
      setQaArtifact(artifact)
      setStatus(`已有译文已登记：${artifactPickerLabel(artifact)}`)
    }
  }

  async function refreshDeliverables() {
    if (!current) {
      setDeliverables([])
      return
    }
    try {
      const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${current.id}/deliverables`)
      setDeliverables((result.deliverables || []).filter((task) => normalizeLanguageCode(task.language) === selectedLanguage))
    } catch {
      setDeliverables([])
    }
  }

  async function createDeliveryPackage(runId: string) {
    if (!current) return
    setBusy(true)
    setStatus('正在生成最终交付文件...')
    try {
      const result = await api<{ files: DeliveryFile[] }>(`/api/projects/${current.id}/delivery-package?run_id=${encodeURIComponent(runId)}`, { method: 'POST' })
      await refreshDeliverables()
      setStatus(`最终交付已生成：${result.files.length} 个文件`)
    } catch (error) {
      setStatus(`最终交付生成失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="shell">
      <div className="app">
        <header className="header">
          <div>
            <h1>🎮 游戏翻译本地化 · 项目工作台</h1>
            <p>Localization Workflow Studio</p>
          </div>
          <div className="header-actions">
            <span className={`status ${busy ? 'running' : ''}`}>{busy ? <span className="loading" /> : null}{status}</span>
            <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}>⚙ 设置</button>
          </div>
        </header>

        <div className="layout">
          <aside className="sidebar">
            <div className="sidebar-title">📁 我的项目</div>
            <div className="project-list">
              {projects.map((project) => (
                <button
                  key={project.id}
                  className={`project-item ${project.id === currentId ? 'active' : ''} ${deleteHoldProjectId === project.id ? 'delete-hold' : ''}`}
                  title="点击切换项目；长按删除项目"
                  onPointerDown={(event) => { if (event.button === 0) beginProjectDeleteHold(project) }}
                  onPointerUp={cancelProjectDeleteHold}
                  onPointerLeave={cancelProjectDeleteHold}
                  onPointerCancel={cancelProjectDeleteHold}
                  onContextMenu={(event) => event.preventDefault()}
                  onClick={(event) => selectProject(project, event)}
                >
                  <span className="pname">{project.icon ? `${project.icon} ` : ''}{project.name}</span>
                  <span className="pmeta">{project.stats.tasks} 个任务 · {project.stats.archived_rows || 0} 条归档</span>
                  {project.type ? <span className="ptag">{project.type}</span> : null}
                </button>
              ))}
            </div>
            <button className="new-project-btn" onClick={() => setNewProjectOpen(true)}>+ 新建项目</button>
            <div className="sidebar-title quick">⚡ 快捷入口</div>
            <button className="project-item quick-entry" onClick={() => current && setView('wizard')} disabled={!current}>
              <span className="pname">🚀 开始新翻译任务</span>
              <span className="pmeta">基于当前项目启动工作流</span>
            </button>
            <button className="project-item quick-entry" data-testid="quick-task-entry" onClick={() => current && setView('quick')} disabled={!current}>
              <span className="pname">⚡ 快速任务</span>
              <span className="pmeta">三步完成翻译或校对</span>
            </button>
            {current ? <QuickTaskRecent project={current} /> : null}
          </aside>

          <main className="main">
            {!current ? <EmptyState onCreate={() => setNewProjectOpen(true)} /> : view === 'overview' ? (
              <ProjectOverview
                project={current}
                tab={tab}
                setTab={setTab}
                settings={settings}
                busy={busy}
                status={status}
                intro={intro}
                setIntro={setIntro}
                sourceArtifact={sourceArtifact}
                termArtifact={termArtifact}
                qaArtifact={qaArtifact}
                archiveArtifact={archiveArtifact}
                latestRun={latestRun}
                translationReadiness={translationReadiness}
                qualityIssues={qualityIssues}
                glossaryPreview={glossaryPreview}
                deliverables={deliverables}
                setSourceArtifact={setSourceArtifact}
                setTermArtifact={setTermArtifact}
                setQaArtifact={setQaArtifact}
                setArchiveArtifact={setArchiveArtifact}
                onSaveMeta={saveProjectMeta}
                onAnalyze={runAnalysis}
                onUploadSource={async (file) => setSourceArtifact(await upload(file, 'language_table'))}
                onUploadTerm={async (file) => setTermArtifact(await upload(file, 'term_base'))}
                onGlossaryPreview={previewGlossaryImport}
                onGlossaryImport={importGlossaryArtifact}
                onGlossaryExtract={runGlossaryExtract}
                onAddTerm={addGlossaryTerm}
                onUpdateTerm={updateGlossaryTerm}
                onDeleteTerm={deleteGlossaryTerm}
                onAddTranslation={addTranslationEntry}
                onUpdateTranslation={updateTranslationEntry}
                onDeleteTranslation={deleteTranslationEntry}
                onUploadArchive={uploadArchiveWorkbook}
                onImportArchive={importTranslationArchive}
                onSaveHarness={saveHarness}
                onTranslate={() => runTranslate('T')}
                onDirectQA={() => runDirectQA('QA')}
                onManualFixes={applyManualFixes}
                onModelFixes={applyModelFixes}
                onUploadTranslation={uploadTranslationWorkbook}
                onCreateDelivery={createDeliveryPackage}
                onStartTask={() => setView('wizard')}
                onStartAnnouncement={() => openAnnouncementTask()}
                onStartAnnouncementTask={openAnnouncementTask}
                onBeginAnnouncementCancelHold={beginAnnouncementCancelHold}
                onCancelAnnouncementHold={cancelAnnouncementCancelHold}
                announcementCancelHoldTaskId={announcementCancelHoldTaskId}
                selectedLanguage={selectedLanguage}
                setSelectedLanguage={setSelectedLanguage}
              />
            ) : view === 'quick' ? (
              <QuickTaskWizard
                project={current}
                busy={busy}
                status={status}
                settings={settings}
                latestRun={latestRun}
                onBack={() => setView('overview')}
                onUploadFile={upload}
                onInspectTargets={inspectTranslationTargets}
                onStartQuickTask={startQuickTask}
                onViewResult={(run) => { setView('overview'); setTab(run?.kind === 'qa' ? 'qa' : 'translation') }}
              />
            ) : view === 'announcement' ? (
              <AnnouncementWizard
                project={current}
                busy={busy}
                status={status}
                selectedLanguage={selectedLanguage}
                setSelectedLanguage={setSelectedLanguage}
                assetArtifacts={assetArtifacts}
                announcementText={announcementText}
                setAnnouncementText={setAnnouncementText}
                lookupResult={announcementLookupResult}
                onUploadAsset={uploadAsset}
                onUploadConstraint={uploadAnnouncementConstraint}
                onUploadTermsFile={uploadAnnouncementTermsFile}
                onCreateTask={createAnnouncementTask}
                onTaskAction={runAnnouncementTaskAction}
                onLookup={runAnnouncementLookup}
                onBack={() => setView('overview')}
                onUploadResponse={uploadAnnouncementResponse}
                onBeginAnnouncementCancelHold={beginAnnouncementCancelHold}
                onCancelAnnouncementHold={cancelAnnouncementCancelHold}
                announcementCancelHoldTaskId={announcementCancelHoldTaskId}
                initialTaskId={announcementFocusTaskId}
                settings={settings}
              />
            ) : (
              <Wizard
                project={currentScoped || current}
                step={step}
                setStep={setStep}
                intro={intro}
                setIntro={setIntro}
                sourceArtifact={sourceArtifact}
                termArtifact={termArtifact}
                qaArtifact={qaArtifact}
                assetArtifacts={assetArtifacts}
                latestRun={latestRun}
                translationReadiness={translationReadiness}
                glossaryBatches={glossaryBatches}
                glossaryCandidates={glossaryCandidates}
                qualityIssues={qualityIssues}
                selectedLanguage={selectedLanguage}
                setSelectedLanguage={setSelectedLanguage}
                setSourceArtifact={setSourceArtifact}
                setTermArtifact={setTermArtifact}
                setQaArtifact={setQaArtifact}
                glossaryPreview={glossaryPreview}
                settings={settings}
                status={status}
                onBack={() => setView('overview')}
                onUploadSource={async (file) => setSourceArtifact(await upload(file, 'language_table'))}
                onUploadTerm={async (file) => setTermArtifact(await upload(file, 'term_base'))}
                onUploadAsset={uploadAsset}
                onAnalyze={runAnalysis}
                onGlossaryExtract={runGlossaryExtract}
                onGlossaryPreview={previewGlossaryImport}
                onGlossaryImport={importGlossaryArtifact}
                onTranslate={() => runTranslate('A')}
                onCancelTranslate={cancelTranslateRun}
                onDirectQA={() => runDirectQA('QA')}
                onManualFixes={applyManualFixes}
                onModelFixes={applyModelFixes}
                onUploadTranslation={uploadTranslationWorkbook}
                onFreq={() => setFreqOpen(true)}
                onSaveHarness={saveHarness}
                onUpdateCandidate={updateGlossaryCandidate}
                onResolveCandidates={resolveGlossaryCandidates}
                onTranslateMissingCandidates={translateMissingGlossaryCandidates}
                busy={busy}
              />
            )}
          </main>
        </div>
      </div>

      {newProjectOpen ? <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} /> : null}
      {deleteProjectTarget ? <DeleteProjectModal project={deleteProjectTarget} busy={busy} onClose={() => { longPressTriggeredProjectId.current = ''; setDeleteProjectTarget(null) }} onDelete={deleteProject} /> : null}
      {announcementCancelTarget ? <CancelAnnouncementTaskModal task={announcementCancelTarget} busy={busy} onClose={() => { longPressTriggeredAnnouncementTaskId.current = ''; setAnnouncementCancelTarget(null) }} onCancelTask={cancelAnnouncementTask} /> : null}
      {settingsOpen ? <SettingsModal onClose={() => { setSettingsOpen(false); refreshSettings() }} /> : null}
      {freqOpen ? <FrequencyModal onClose={() => setFreqOpen(false)} /> : null}
    </div>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return <div className="empty"><h2>还没有项目</h2><p>先创建一个本地化项目，再进入完整工作流。</p><button className="btn btn-primary" onClick={onCreate}>新建项目</button></div>
}

function ProjectOverview({
  project,
  tab,
  setTab,
  settings,
  busy,
  status,
  intro,
  setIntro,
  sourceArtifact,
  termArtifact,
  qaArtifact,
  archiveArtifact,
  latestRun,
  translationReadiness,
  qualityIssues,
  glossaryPreview,
  deliverables,
  setSourceArtifact,
  setTermArtifact,
  setQaArtifact,
  setArchiveArtifact,
  onSaveMeta,
  onAnalyze,
  onUploadSource,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onGlossaryExtract,
  onAddTerm,
  onUpdateTerm,
  onDeleteTerm,
  onAddTranslation,
  onUpdateTranslation,
  onDeleteTranslation,
  onUploadArchive,
  onImportArchive,
  onSaveHarness,
  onTranslate,
  onDirectQA,
  onManualFixes,
  onModelFixes,
  onUploadTranslation,
  onCreateDelivery,
  onStartTask,
  onStartAnnouncement,
  onStartAnnouncementTask,
  onBeginAnnouncementCancelHold,
  onCancelAnnouncementHold,
  announcementCancelHoldTaskId,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  tab: ProjectTab
  setTab: (tab: ProjectTab) => void
  settings: AppSettings | null
  busy: boolean
  status: string
  intro: string
  setIntro: (value: string) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  qaArtifact: Artifact | null
  archiveArtifact: Artifact | null
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  glossaryPreview: GlossaryPreviewRow[]
  deliverables: DeliverableTask[]
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  setArchiveArtifact: (artifact: Artifact | null) => void
  onSaveMeta: (updates: Partial<Project>) => Promise<void>
  onAnalyze: () => void
  onUploadSource: (file: File) => void
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onGlossaryExtract: () => void
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
  onAddTranslation: (form: FormData) => void
  onUpdateTranslation: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDeleteTranslation: (entry: TranslationEntry) => Promise<void>
  onUploadArchive: (file: File) => void
  onImportArchive: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onTranslate: () => void
  onDirectQA: () => void
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  onCreateDelivery: (runId: string) => void
  onStartTask: () => void
  onStartAnnouncement: () => void
  onStartAnnouncementTask: (task: AnnouncementTask) => void
  onBeginAnnouncementCancelHold: (task: AnnouncementTask) => void
  onCancelAnnouncementHold: () => void
  announcementCancelHoldTaskId: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const glossaryRows = glossaryWideRows(project)
  const archiveRows = translationWideRows(project)
  const termCoverage = glossaryCoverage(project)
  const translationCoverage = archiveCoverage(project)
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>{project.icon ? <span className="project-icon">{project.icon}</span> : null}{project.name}</h2>
        </div>
        <div className="row-actions">
          <button className="btn btn-primary" onClick={onStartTask}>🚀 启动新翻译任务</button>
          <button className="btn btn-ghost" onClick={onStartAnnouncement}>📣 公告翻译</button>
        </div>
      </div>
      <div className="stat-grid">
        <div className="stat-card"><div className="num">{project.stats.tasks}</div><div className="lbl">累计任务</div></div>
        <div className="stat-card"><div className="num">{glossaryRows.length}</div><div className="lbl">CN 术语概念 · {coverageSummary(termCoverage)}</div></div>
        <div className="stat-card"><div className="num">{archiveRows.length}</div><div className="lbl">CN 归档源文 · {coverageSummary(translationCoverage)}</div></div>
        <div className="stat-card"><div className="num">{project.stats.words}</div><div className="lbl">归档译文字数</div></div>
      </div>
      <AnnouncementProjectPanel
        tasks={project.announcement_tasks || []}
        holdTaskId={announcementCancelHoldTaskId}
        onStartAnnouncement={onStartAnnouncement}
        onStartTask={onStartAnnouncementTask}
        onBeginCancelHold={onBeginAnnouncementCancelHold}
        onCancelHold={onCancelAnnouncementHold}
      />
      <div className="view-tabs">
        <button className={`view-tab ${tab === 'meta' ? 'active' : ''}`} onClick={() => setTab('meta')}>📝 元信息</button>
        <button className={`view-tab ${tab === 'glossary' ? 'active' : ''}`} onClick={() => setTab('glossary')}>📚 术语表</button>
        <button className={`view-tab ${tab === 'translation' ? 'active' : ''}`} onClick={() => setTab('translation')}>⚡ 翻译</button>
        <button className={`view-tab ${tab === 'qa' ? 'active' : ''}`} onClick={() => setTab('qa')}>🔧 校对</button>
        <button className={`view-tab ${tab === 'archive' ? 'active' : ''}`} onClick={() => setTab('archive')}>🗄️ 译文归档</button>
        <button className={`view-tab ${tab === 'delivery' ? 'active' : ''}`} onClick={() => setTab('delivery')}>📥 交付</button>
      </div>
      {tab === 'meta' ? <MetaTab project={project} intro={intro} setIntro={setIntro} busy={busy} selectedLanguage={selectedLanguage} onSaveMeta={onSaveMeta} onAnalyze={onAnalyze} onSaveHarness={onSaveHarness} /> : null}
      {tab === 'glossary' ? (
        <GlossaryTab
          project={project}
          sourceArtifact={sourceArtifact}
          termArtifact={termArtifact}
          setTermArtifact={setTermArtifact}
          glossaryPreview={glossaryPreview}
          busy={busy}
          status={status}
          onUploadTerm={onUploadTerm}
          onGlossaryPreview={onGlossaryPreview}
          onGlossaryImport={onGlossaryImport}
          onGlossaryExtract={onGlossaryExtract}
          onAddTerm={onAddTerm}
          onUpdateTerm={onUpdateTerm}
          onDeleteTerm={onDeleteTerm}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
        />
      ) : null}
      {tab === 'translation' ? (
        <TranslationTab
          project={project}
          settings={settings}
          busy={busy}
          status={status}
          sourceArtifact={sourceArtifact}
          termArtifact={termArtifact}
          latestRun={latestRun}
          translationReadiness={translationReadiness}
          qualityIssues={qualityIssues}
          setSourceArtifact={setSourceArtifact}
          setTermArtifact={setTermArtifact}
          onUploadSource={onUploadSource}
          onTranslate={onTranslate}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
        />
      ) : null}
      {tab === 'qa' ? (
        <StepQA
          project={project}
          latestRun={latestRun}
          sourceArtifact={sourceArtifact}
          translationReadiness={translationReadiness}
          qualityIssues={qualityIssues}
          qaArtifact={qaArtifact}
          setQaArtifact={setQaArtifact}
          onDirectQA={onDirectQA}
          onManualFixes={onManualFixes}
          onModelFixes={onModelFixes}
          onUploadTranslation={onUploadTranslation}
          busy={busy}
          status={status}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
        />
      ) : null}
      {tab === 'archive' ? (
        <TranslationArchiveTab
          project={project}
          archiveArtifact={archiveArtifact}
          setArchiveArtifact={setArchiveArtifact}
          busy={busy}
          status={status}
          onUploadArchive={onUploadArchive}
          onImportArchive={onImportArchive}
          onAddTranslation={onAddTranslation}
          onUpdateTranslation={onUpdateTranslation}
          onDeleteTranslation={onDeleteTranslation}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
        />
      ) : null}
      {tab === 'delivery' ? <DeliveryTab project={project} deliverables={deliverables} busy={busy} status={status} onCreateDelivery={onCreateDelivery} /> : null}
    </>
  )
}

function MetaTab({
  project,
  intro,
  setIntro,
  busy,
  selectedLanguage,
  onSaveMeta,
  onAnalyze,
  onSaveHarness
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  busy: boolean
  selectedLanguage: LanguageCode
  onSaveMeta: (updates: Partial<Project>) => Promise<void>
  onAnalyze: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
}) {
  const promptText = projectPromptForLanguage(project, selectedLanguage)
  const lang = languageSpec(selectedLanguage)
  const [name, setName] = useState(project.name)
  const [type, setType] = useState(project.type || '')
  const [description, setDescription] = useState(project.description || '')
  const [promptDraft, setPromptDraft] = useState(promptText)
  const [editingPrompt, setEditingPrompt] = useState(false)

  useEffect(() => {
    setName(project.name)
    setType(project.type || '')
    setDescription(project.description || '')
    setPromptDraft(projectPromptForLanguage(project, selectedLanguage))
    setEditingPrompt(false)
  }, [project.id, project.name, project.type, project.description, project.prompt_text, project.profile, selectedLanguage])

  async function submit() {
    await onSaveMeta({ name: name.trim() || project.name, type, description })
    setIntro(description)
  }

  async function savePrompt() {
    const profile = { ...(project.profile || {}) }
    const prompts = { ...((profile.prompts_by_language as Record<string, unknown> | undefined) || {}) }
    prompts[selectedLanguage] = promptDraft
    profile.prompts_by_language = prompts
    await onSaveMeta(selectedLanguage === 'en' ? { prompt_text: promptDraft, profile } : { profile })
    setEditingPrompt(false)
  }

  async function copyPrompt() {
    await navigator.clipboard.writeText(promptText)
  }

  return (
    <>
      <div className="card reference-card">
        <div className="card-title">
          <div className="left">🤖 AI 生成的专属翻译提示词（{lang.short}）</div>
          <div className="card-actions">
            <button className="btn btn-ghost btn-sm" disabled={!promptText} onClick={copyPrompt}>📋 复制</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditingPrompt((value) => !value)}>✏️ 编辑</button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onAnalyze}>🔄 重新生成</button>
          </div>
        </div>
        {editingPrompt ? (
          <>
            <textarea className="prompt-editor" value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} placeholder="输入当前项目专属翻译提示词" />
            <div className="row-actions align-right">
              <button className="btn btn-ghost btn-sm" onClick={() => { setPromptDraft(promptText); setEditingPrompt(false) }}>取消</button>
              <button className="btn btn-primary btn-sm" onClick={savePrompt}>保存提示词</button>
            </div>
          </>
        ) : (
          <pre>{promptText || `尚未生成 ${lang.short} 提示词。点击“重新生成”后会自动保存到当前项目。`}</pre>
        )}
      </div>
      <ProjectMetaTable project={project} />
      <details className="advanced-panel edit-panel">
        <summary>编辑项目元信息 / 重新生成输入</summary>
        <div className="advanced-body">
          <div className="card">
            <div className="card-title">
              <div className="left">项目元信息编辑</div>
              <button className="btn btn-primary btn-sm" onClick={submit}>保存元信息</button>
            </div>
            <div className="meta-grid">
              <label><span>主项目名</span><input value={name} onChange={(event) => setName(event.target.value)} /></label>
              <label><span>题材/分类</span><input value={type} onChange={(event) => setType(event.target.value)} placeholder="飞行射击 / 休闲战斗" /></label>
              <label className="wide"><span>来源标注、目标语言、风格要求、素材来源</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder={`来源：语言表、术语表、校对表\n目标语言：${lang.label}\n风格：短句准确，按钮和任务文案清晰，核心术语统一`} /></label>
              <label className="wide"><span>重新生成提示词输入</span><textarea className="compact-textarea" value={intro} onChange={(event) => setIntro(event.target.value)} placeholder="补充本次分析需要的上下文；留空时使用项目描述。" /></label>
            </div>
          </div>
        </div>
      </details>
      <details className="advanced-panel">
        <summary>高级：项目规则与持续改进</summary>
        <div className="advanced-body">
          <HarnessEditor project={project} onSave={onSaveHarness} compact />
          <ImprovementQueue projectId={project.id} />
        </div>
      </details>
    </>
  )
}

function ProjectMetaTable({ project }: { project: Project }) {
  const harness = getProjectHarness(project)
  const forbidden = fieldText(harness.forbidden_translations, '未设置')
  const fixedTerms = fixedTermsSummary(project)
  const rules = ruleSummary(project)
  const ruleUpdated = harness.updated_at ? `保存于 ${formatDate(harness.updated_at)}` : '未单独保存'
  return (
    <div className="card reference-card">
      <div className="card-title">
        <div className="left">📌 项目元信息</div>
      </div>
      <table className="meta-table">
        <tbody>
          <tr><th>游戏类型</th><td>{profileText(project, 'game_type', project.type || '未填写')}</td></tr>
          <tr><th>目标用户</th><td>{profileText(project, 'target_audience')}</td></tr>
          <tr><th>内容构成</th><td>{profileText(project, 'content_scope')}</td></tr>
          <tr><th>翻译风格</th><td>{profileText(project, 'translation_style')}</td></tr>
          <tr><th>语言资产</th><td>{profileText(project, 'language_assets')}</td></tr>
          <tr><th>素材来源</th><td>{profileText(project, 'source_materials')}</td></tr>
          <tr><th>质量规则摘要</th><td>固定译名：{fixedTerms}；禁用译法：{forbidden}；项目规则：{rules}。{ruleUpdated}</td></tr>
          <tr><th>生成日期</th><td>{profileText(project, 'generated_date', formatDate(project.updated_at))}</td></tr>
        </tbody>
      </table>
    </div>
  )
}

function ImprovementQueue({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Record<string, unknown>[]>([])
  async function load() {
    setItems(await api<Record<string, unknown>[]>(`/api/projects/${projectId}/improvements`))
  }
  useEffect(() => {
    load()
  }, [projectId])
  return (
    <div className="card">
      <div className="card-title">
        <div className="left">持续改进建议队列</div>
        <button className="btn btn-sm" onClick={load}>刷新</button>
      </div>
      <table>
        <thead><tr><th>类别</th><th>标题</th><th>状态</th></tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={String(item.id)}>
              <td>{String(item.category || '-')}</td>
              <td>{String(item.title || '-')}</td>
              <td><span className="tag tag-new">{String(item.status || 'pending_review')}</span></td>
            </tr>
          ))}
          {!items.length ? <tr><td colSpan={3} className="muted">暂无建议；可在翻译历史里从某次 run 生成。</td></tr> : null}
        </tbody>
      </table>
    </div>
  )
}

function HarnessEditor({
  project,
  onSave,
  compact = false
}: {
  project: Project
  onSave: (updates: Partial<ProjectHarness>) => Promise<void>
  compact?: boolean
}) {
  const harness = getProjectHarness(project)
  const [styleGuidance, setStyleGuidance] = useState(harness.style_guidance || '')
  const [targetAudience, setTargetAudience] = useState(harness.target_audience || '')
  const [tone, setTone] = useState(harness.tone || '')
  const [forbidden, setForbidden] = useState(listToLines(harness.forbidden_translations))
  const [fixedTerms, setFixedTerms] = useState(fixedTermsToLines(harness.fixed_terms))
  const [hardRules, setHardRules] = useState(rulesToLines(harness.hard_rules))
  const [softRules, setSoftRules] = useState(rulesToLines(harness.soft_rules))
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setStyleGuidance(harness.style_guidance || '')
    setTargetAudience(harness.target_audience || '')
    setTone(harness.tone || '')
    setForbidden(listToLines(harness.forbidden_translations))
    setFixedTerms(fixedTermsToLines(harness.fixed_terms))
    setHardRules(rulesToLines(harness.hard_rules))
    setSoftRules(rulesToLines(harness.soft_rules))
  }, [project.id, harness.updated_at])

  async function submit() {
    setSaving(true)
    try {
      await onSave({
        style_guidance: styleGuidance,
        target_audience: targetAudience,
        tone,
        forbidden_translations: linesToList(forbidden),
        fixed_terms: linesToFixedTerms(fixedTerms),
        hard_rules: linesToRules(hardRules),
        soft_rules: linesToRules(softRules)
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`card ${compact ? 'compact-harness' : ''}`}>
      <div className="card-title">
        <div className="left">项目规则编辑</div>
        <button className="btn btn-primary btn-sm" disabled={saving} onClick={submit}>{saving ? '保存中...' : '保存项目规则'}</button>
      </div>
      <div className="harness-editor">
        <label><span>目标受众</span><input value={targetAudience} onChange={(event) => setTargetAudience(event.target.value)} placeholder="欧美移动端玩家 / 核心策略用户" /></label>
        <label><span>语气</span><input value={tone} onChange={(event) => setTone(event.target.value)} placeholder="冷静、现代、军事化 / 轻松、活泼" /></label>
        <label className="wide"><span>项目风格要求</span><textarea value={styleGuidance} onChange={(event) => setStyleGuidance(event.target.value)} placeholder="只写当前项目特有要求，不写进整体通用规则。" /></label>
        <label><span>禁用译法（一行一个）</span><textarea value={forbidden} onChange={(event) => setForbidden(event.target.value)} placeholder={'例如：\nMock\nraw CN'} /></label>
        <label><span>固定译名（一行一个 source =&gt; target）</span><textarea value={fixedTerms} onChange={(event) => setFixedTerms(event.target.value)} placeholder={'例如：\n最强指挥官 => Strongest Commander'} /></label>
        <label><span>必须规则（一行一个 label | description | regex）</span><textarea value={hardRules} onChange={(event) => setHardRules(event.target.value)} placeholder={'例如：\nNo mock marker | Mock marker must not ship | Mock'} /></label>
        <label><span>建议规则（一行一个 label | description）</span><textarea value={softRules} onChange={(event) => setSoftRules(event.target.value)} placeholder="例如：短 UI 文案优先用动词开头" /></label>
      </div>
    </div>
  )
}

function WideTableSearchBar({
  testId,
  value,
  onChange,
  totalRows,
  filteredRows,
  placeholder
}: {
  testId: string
  value: string
  onChange: (value: string) => void
  totalRows: number
  filteredRows: number
  placeholder: string
}) {
  return (
    <div className="wide-table-search">
      <input
        data-testid={testId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
      <span>{value.trim() ? `匹配 ${filteredRows} / ${totalRows}` : `共 ${totalRows} 行`}</span>
    </div>
  )
}

function WideTableLanguageControls({
  testIdPrefix,
  availableLanguages,
  selectedLanguages,
  onToggle
}: {
  testIdPrefix: string
  availableLanguages: LanguageCode[]
  selectedLanguages: LanguageCode[]
  onToggle: (language: LanguageCode) => void
}) {
  if (!availableLanguages.length) return null
  const selected = new Set(selectedLanguages)
  return (
    <div className="wide-table-language-controls">
      <span>展示语言：</span>
      {availableLanguages.map((code) => {
        const lang = languageSpec(code)
        return (
          <button
            key={code}
            type="button"
            data-testid={`${testIdPrefix}-display-lang-${code}`}
            className={`lang-chip ${selected.has(code) ? 'selected' : ''}`}
            onClick={() => onToggle(code)}
          >
            {lang.short} {lang.label.replace(`${lang.short} `, '')}
          </button>
        )
      })}
    </div>
  )
}

function WideTablePager({
  testIdPrefix,
  page,
  totalRows,
  onPageChange
}: {
  testIdPrefix: string
  page: number
  totalRows: number
  onPageChange: (page: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(totalRows / WIDE_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  if (totalRows <= WIDE_TABLE_PAGE_SIZE) {
    return <div className="wide-table-pager muted-left">第 1 页 / 共 1 页</div>
  }
  return (
    <div className="wide-table-pager">
      <span>{totalRows} 行 · 第 {currentPage} / {totalPages} 页</span>
      <div className="row-actions compact-actions">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid={`${testIdPrefix}-page-prev`}
          disabled={currentPage <= 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
        >
          上一页
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid={`${testIdPrefix}-page-next`}
          disabled={currentPage >= totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
        >
          下一页
        </button>
      </div>
    </div>
  )
}

function GlossaryTab({
  project,
  sourceArtifact,
  termArtifact,
  setTermArtifact,
  glossaryPreview,
  busy,
  status,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onGlossaryExtract,
  onAddTerm,
  onUpdateTerm,
  onDeleteTerm,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  busy: boolean
  status: string
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onGlossaryExtract: () => void
  onAddTerm: (form: FormData) => void
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const [toolsOpen, setToolsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [displayLanguages, setDisplayLanguages] = useState<LanguageCode[]>([])
  const [page, setPage] = useState(1)
  const lang = languageSpec(selectedLanguage)
  const rows = glossaryWideRows(project)
  const availableDisplayLanguages = visibleLanguagesFromRows(rows).filter((code) => code !== 'en')
  const visibleLanguages = displayLanguagesForWideRows(rows, displayLanguages)
  const filteredRows = rows.filter((row) => glossaryWideRowMatches(row, searchQuery))
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / WIDE_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const currentRows = pagedRows(filteredRows, currentPage)
  const colSpan = 5 + visibleLanguages.reduce((total, code) => total + (altColumnVisible(code) ? 2 : 1), 0)

  useEffect(() => {
    setPage(1)
  }, [searchQuery, displayLanguages.join('|'), rows.length])

  function toggleDisplayLanguage(code: LanguageCode) {
    setDisplayLanguages((value) => value.includes(code) ? value.filter((item) => item !== code) : [...value, code])
  }

  return (
    <>
      <div className="card">
        <div className="card-title">
          <div className="left">项目术语表（{rows.length} 个 CN 概念）</div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToolsOpen((value) => !value)}>{toolsOpen ? '收起导入/导出' : '导入 / 生成 / 导出'}</button>
        </div>
        <WideTableSearchBar
          testId="glossary-search"
          value={searchQuery}
          onChange={setSearchQuery}
          totalRows={rows.length}
          filteredRows={filteredRows.length}
          placeholder="强匹配搜索 ID / CN / 译文 / 分类 / 备注"
        />
        {toolsOpen ? (
          <GlossaryToolsPanel
            project={project}
            sourceArtifact={sourceArtifact}
            termArtifact={termArtifact}
            setTermArtifact={setTermArtifact}
            busy={busy}
            onUploadTerm={onUploadTerm}
            onGlossaryPreview={onGlossaryPreview}
            onGlossaryImport={onGlossaryImport}
            onGlossaryExtract={onGlossaryExtract}
            selectedLanguage={selectedLanguage}
            setSelectedLanguage={setSelectedLanguage}
          />
        ) : null}
        <ActionStatus status={status} busy={busy} />
        {toolsOpen && glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} selectedLanguage={selectedLanguage} /> : null}
        <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); onAddTerm(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
          <input name="term_key" placeholder="ID" />
          <input name="source" placeholder="CN" required />
          <input name="target" placeholder={lang.targetHeader} />
          {altColumnVisible(selectedLanguage) ? <input name="target_alt" placeholder={lang.altHeader} /> : <input name="target_alt" type="hidden" value="" />}
          <input name="category" placeholder="分类" />
          <input name="note" placeholder="备注" />
          <input name="language" type="hidden" value={selectedLanguage} />
          <button className="btn btn-primary btn-sm">+ 新增 {lang.short}</button>
        </form>
        <div className="language-inline-select">
          <span>新增 / 生成语言：</span>
          <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
        </div>
        <WideTableLanguageControls
          testIdPrefix="glossary"
          availableLanguages={availableDisplayLanguages}
          selectedLanguages={displayLanguages}
          onToggle={toggleDisplayLanguage}
        />
        <div className="table-scroll">
          <table className="glossary-table glossary-wide-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>CN</th>
                {visibleLanguages.map((code) => {
                  const spec = languageSpec(code)
                  return (
                    <React.Fragment key={code}>
                      <th>{spec.targetHeader}</th>
                      {altColumnVisible(code) ? <th>{spec.altHeader}</th> : null}
                    </React.Fragment>
                  )
                })}
                <th>分类</th>
                <th>备注</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {currentRows.map((row) => (
                <WideGlossaryTermRow key={row.source_key} row={row} visibleLanguages={visibleLanguages} onUpdateTerm={onUpdateTerm} onDeleteTerm={onDeleteTerm} />
              ))}
              {!rows.length ? <tr><td colSpan={colSpan} className="muted">暂无术语。可上传已有术语表、从语言表生成，或手工新增。</td></tr> : null}
              {rows.length && !filteredRows.length ? <tr><td colSpan={colSpan} className="muted">暂无匹配结果</td></tr> : null}
            </tbody>
          </table>
        </div>
        <WideTablePager testIdPrefix="glossary" page={currentPage} totalRows={filteredRows.length} onPageChange={setPage} />
      </div>
    </>
  )
}

function GlossaryToolsPanel({
  project,
  sourceArtifact,
  termArtifact,
  setTermArtifact,
  busy,
  onUploadTerm,
  onGlossaryPreview,
  onGlossaryImport,
  onGlossaryExtract,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  busy: boolean
  onUploadTerm: (file: File) => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onGlossaryExtract: () => void
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <div className="glossary-tools-panel">
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} allowEmpty />
        <FileBox label="上传术语表 xlsx/csv/json" onFile={onUploadTerm} />
        <div className="language-inline-select">
          <span>从语言表生成 / 单语言兜底：</span>
          <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
        </div>
        <div className="row-actions">
          <button type="button" className="btn btn-ghost" disabled={!termArtifact || busy} onClick={onGlossaryPreview}>自动预览导入</button>
          <button type="button" className="btn btn-primary" disabled={!termArtifact || busy} onClick={onGlossaryImport}>自动导入多语言术语</button>
          <button type="button" className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>生成 {lang.short} 术语候选</button>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx`}>导出全部 XLSX</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=csv`}>导出全部 CSV</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=json`}>导出全部 JSON</a>
        </div>
        {!sourceArtifact ? <div className="warn-line">需要从语言表生成术语时，先在“翻译”页上传待翻译表。</div> : null}
        <div className="muted-left">自动导入会识别 EN/EN2、KR/KO、JP/JA；KR/JP 默认不使用第二译名列。</div>
      </div>
    </div>
  )
}

function WideGlossaryTermRow({
  row,
  visibleLanguages,
  onUpdateTerm,
  onDeleteTerm
}: {
  row: WideGlossaryRow
  visibleLanguages: LanguageCode[]
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: row.term_key || '',
    source: row.source || '',
    category: row.category || '',
    note: normalizeGlossaryNote(row.note),
    targets: supportedLanguages.reduce((acc, lang) => {
      acc[lang.code] = row.translations[lang.code]?.target || ''
      return acc
    }, {} as Record<LanguageCode, string>),
    enAlt: row.translations.en?.target_alt || ''
  })

  useEffect(() => {
    setDraft({
      term_key: row.term_key || '',
      source: row.source || '',
      category: row.category || '',
      note: normalizeGlossaryNote(row.note),
      targets: supportedLanguages.reduce((acc, lang) => {
        acc[lang.code] = row.translations[lang.code]?.target || ''
        return acc
      }, {} as Record<LanguageCode, string>),
      enAlt: row.translations.en?.target_alt || ''
    })
    setEditing(false)
  }, [row.source_key, row.term_key, row.source, row.category, row.note, JSON.stringify(row.translations)])

  async function save() {
    const records = rowRecords<GlossaryTerm>(row)
    for (const record of records) {
      const code = languageFromValue(record.language) || 'en'
      await onUpdateTerm(record, {
        term_key: draft.term_key,
        source: draft.source,
        target: draft.targets[code] || '',
        target_alt: code === 'en' ? draft.enAlt : '',
        category: draft.category,
        note: draft.note
      })
    }
    setEditing(false)
  }

  async function remove() {
    const records = rowRecords<GlossaryTerm>(row)
    for (const record of records) await onDeleteTerm(record)
  }

  function sharedCell(key: 'term_key' | 'source' | 'category' | 'note') {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  function targetCell(code: LanguageCode) {
    if (!editing) return <span className="readonly-cell">{draft.targets[code] || '-'}</span>
    return <input className="cell-input" value={draft.targets[code] || ''} onChange={(event) => setDraft((value) => ({ ...value, targets: { ...value.targets, [code]: event.target.value } }))} />
  }

  function enAltCell() {
    if (!editing) return <span className="readonly-cell">{draft.enAlt || '-'}</span>
    return <input className="cell-input" value={draft.enAlt} onChange={(event) => setDraft((value) => ({ ...value, enAlt: event.target.value }))} />
  }

  return (
    <tr className={row.conflicts.length ? 'has-conflict' : ''}>
      <td>{sharedCell('term_key')}{row.conflicts.length ? <span className="conflict-badge" title={row.conflicts.map((item) => `${item.field}: ${item.values.join(' / ')}`).join('\n')}>字段冲突</span> : null}</td>
      <td>{sharedCell('source')}</td>
      {visibleLanguages.map((code) => (
        <React.Fragment key={code}>
          <td>{targetCell(code)}</td>
          {altColumnVisible(code) ? <td>{enAltCell()}</td> : null}
        </React.Fragment>
      ))}
      <td>{sharedCell('category')}</td>
      <td>{sharedCell('note')}</td>
      <td>
        <div className="table-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={save}>保存</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={remove}>删除</button>
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>编辑</button>
          )}
        </div>
      </td>
    </tr>
  )
}

function TranslationArchiveTab({
  project,
  archiveArtifact,
  setArchiveArtifact,
  busy,
  status,
  onUploadArchive,
  onImportArchive,
  onAddTranslation,
  onUpdateTranslation,
  onDeleteTranslation,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  archiveArtifact: Artifact | null
  setArchiveArtifact: (artifact: Artifact | null) => void
  busy: boolean
  status: string
  onUploadArchive: (file: File) => void
  onImportArchive: () => void
  onAddTranslation: (form: FormData) => void
  onUpdateTranslation: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDeleteTranslation: (entry: TranslationEntry) => Promise<void>
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const [toolsOpen, setToolsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [displayLanguages, setDisplayLanguages] = useState<LanguageCode[]>([])
  const [page, setPage] = useState(1)
  const rows = translationWideRows(project)
  const availableDisplayLanguages = visibleLanguagesFromRows(rows).filter((code) => code !== 'en')
  const visibleLanguages = displayLanguagesForWideRows(rows, displayLanguages)
  const filteredRows = rows.filter((row) => translationWideRowMatches(row, searchQuery))
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / WIDE_TABLE_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const currentRows = pagedRows(filteredRows, currentPage)
  const lang = languageSpec(selectedLanguage)
  const colSpan = 4 + visibleLanguages.reduce((total, code) => total + (altColumnVisible(code) ? 2 : 1), 0)

  useEffect(() => {
    setPage(1)
  }, [searchQuery, displayLanguages.join('|'), rows.length])

  function toggleDisplayLanguage(code: LanguageCode) {
    setDisplayLanguages((value) => value.includes(code) ? value.filter((item) => item !== code) : [...value, code])
  }

  return (
    <div className="card">
      <div className="card-title">
        <div className="left">项目译文归档（{rows.length} 个 CN 源文）</div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToolsOpen((value) => !value)}>{toolsOpen ? '收起导入/导出' : '导入 / 导出'}</button>
      </div>
      <WideTableSearchBar
        testId="archive-search"
        value={searchQuery}
        onChange={setSearchQuery}
        totalRows={rows.length}
        filteredRows={filteredRows.length}
        placeholder="强匹配搜索 ID / CN / 译文 / 备注"
      />
      {toolsOpen ? (
        <div className="glossary-tools-panel">
          <div className="action-card">
            <AssetSelect label="使用已有译文资产" project={project} role={['translation_workbook', 'language_source']} value={archiveArtifact} onChange={setArchiveArtifact} allowEmpty />
            <FileBox label="上传译文 workbook/csv/json" onFile={onUploadArchive} />
            <div className="language-inline-select">
              <span>单语言兜底：</span>
              <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
            </div>
            <div className="row-actions">
              <button type="button" className="btn btn-primary" disabled={!archiveArtifact || busy} onClick={onImportArchive}>自动导入多语言归档</button>
              <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=xlsx`}>导出全部 XLSX</a>
              <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=csv`}>导出全部 CSV</a>
              <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=json`}>导出全部 JSON</a>
            </div>
            <div className="muted-left">自动导入会识别 EN/EN2、KR/KO、JP/JA；KR/JP 默认不使用第二译名列。</div>
          </div>
        </div>
      ) : null}
      <ActionStatus status={status} busy={busy} />
      <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); onAddTranslation(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
        <input name="entry_key" placeholder="ID" />
        <input name="source" placeholder="CN" required />
        <input name="target" placeholder={lang.targetHeader} />
        {altColumnVisible(selectedLanguage) ? <input name="target_alt" placeholder={lang.altHeader} /> : <input name="target_alt" type="hidden" value="" />}
        <input name="note" placeholder="备注" />
        <input name="language" type="hidden" value={selectedLanguage} />
        <button className="btn btn-primary btn-sm">+ 新增 {lang.short}</button>
      </form>
      <div className="language-inline-select">
        <span>新增语言：</span>
        <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
      </div>
      <WideTableLanguageControls
        testIdPrefix="archive"
        availableLanguages={availableDisplayLanguages}
        selectedLanguages={displayLanguages}
        onToggle={toggleDisplayLanguage}
      />
      <div className="table-scroll">
        <table className="glossary-table translation-archive-table translation-wide-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>CN</th>
              {visibleLanguages.map((code) => {
                const spec = languageSpec(code)
                return (
                  <React.Fragment key={code}>
                    <th>{spec.targetHeader}</th>
                    {altColumnVisible(code) ? <th>{spec.altHeader}</th> : null}
                  </React.Fragment>
                )
              })}
              <th>备注</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {currentRows.map((row) => (
              <WideTranslationEntryRow key={row.source_key} row={row} visibleLanguages={visibleLanguages} onUpdate={onUpdateTranslation} onDelete={onDeleteTranslation} />
            ))}
            {!rows.length ? <tr><td colSpan={colSpan} className="muted">暂无译文归档。QA 通过后会自动写入，也可以从已有译文表导入。</td></tr> : null}
            {rows.length && !filteredRows.length ? <tr><td colSpan={colSpan} className="muted">暂无匹配结果</td></tr> : null}
          </tbody>
        </table>
      </div>
      <WideTablePager testIdPrefix="archive" page={currentPage} totalRows={filteredRows.length} onPageChange={setPage} />
    </div>
  )
}

function WideTranslationEntryRow({
  row,
  visibleLanguages,
  onUpdate,
  onDelete
}: {
  row: WideTranslationRow
  visibleLanguages: LanguageCode[]
  onUpdate: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDelete: (entry: TranslationEntry) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    entry_key: row.entry_key || '',
    source: row.source || '',
    note: row.note || '',
    targets: supportedLanguages.reduce((acc, lang) => {
      acc[lang.code] = row.translations[lang.code]?.target || ''
      return acc
    }, {} as Record<LanguageCode, string>),
    enAlt: row.translations.en?.target_alt || ''
  })

  useEffect(() => {
    setDraft({
      entry_key: row.entry_key || '',
      source: row.source || '',
      note: row.note || '',
      targets: supportedLanguages.reduce((acc, lang) => {
        acc[lang.code] = row.translations[lang.code]?.target || ''
        return acc
      }, {} as Record<LanguageCode, string>),
      enAlt: row.translations.en?.target_alt || ''
    })
    setEditing(false)
  }, [row.source_key, row.entry_key, row.source, row.note, JSON.stringify(row.translations)])

  async function save() {
    const records = rowRecords<TranslationEntry>(row)
    for (const record of records) {
      const code = languageFromValue(record.language) || 'en'
      await onUpdate(record, {
        entry_key: draft.entry_key,
        source: draft.source,
        target: draft.targets[code] || '',
        target_alt: code === 'en' ? draft.enAlt : '',
        note: draft.note
      })
    }
    setEditing(false)
  }

  async function remove() {
    const records = rowRecords<TranslationEntry>(row)
    for (const record of records) await onDelete(record)
  }

  function sharedCell(key: 'entry_key' | 'source' | 'note') {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  function targetCell(code: LanguageCode) {
    if (!editing) return <span className="readonly-cell">{draft.targets[code] || '-'}</span>
    return <input className="cell-input" value={draft.targets[code] || ''} onChange={(event) => setDraft((value) => ({ ...value, targets: { ...value.targets, [code]: event.target.value } }))} />
  }

  function enAltCell() {
    if (!editing) return <span className="readonly-cell">{draft.enAlt || '-'}</span>
    return <input className="cell-input" value={draft.enAlt} onChange={(event) => setDraft((value) => ({ ...value, enAlt: event.target.value }))} />
  }

  return (
    <tr className={row.conflicts.length ? 'has-conflict' : ''}>
      <td>{sharedCell('entry_key')}{row.conflicts.length ? <span className="conflict-badge" title={row.conflicts.map((item) => `${item.field}: ${item.values.join(' / ')}`).join('\n')}>字段冲突</span> : null}</td>
      <td>{sharedCell('source')}</td>
      {visibleLanguages.map((code) => (
        <React.Fragment key={code}>
          <td>{targetCell(code)}</td>
          {altColumnVisible(code) ? <td>{enAltCell()}</td> : null}
        </React.Fragment>
      ))}
      <td>{sharedCell('note')}</td>
      <td>
        <div className="table-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={save}>保存</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={remove}>删除</button>
            </>
          ) : (
            <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>编辑</button>
          )}
        </div>
      </td>
    </tr>
  )
}

function TranslationTab({
  project,
  settings,
  busy,
  status,
  sourceArtifact,
  termArtifact,
  latestRun,
  translationReadiness,
  qualityIssues,
  setSourceArtifact,
  setTermArtifact,
  onUploadSource,
  onTranslate,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  settings: AppSettings | null
  busy: boolean
  status: string
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  onUploadSource: (file: File) => void
  onTranslate: () => void
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id ? translationReadiness : null
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project, readiness)
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const lang = languageSpec(selectedLanguage)
  const promptReady = Boolean(projectPromptForLanguage(project, selectedLanguage))
  return (
    <>
      <div className="card">
        <div className="card-title"><div className="left">{lang.short} 翻译任务</div></div>
        <div className="action-card">
          <div className="language-inline-select">
            <span>翻译目标语言：</span>
            <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
          </div>
          <AssetSelect label="待翻译语言表" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} allowEmpty />
          <FileBox label="上传待翻译 workbook" onFile={onUploadSource} />
          <button className="btn btn-primary" data-testid="formal-translate" disabled={busy || Boolean(blockReason)} onClick={onTranslate}>开始正式翻译</button>
          {blockReason ? <div className="warn-line">{blockReason}</div> : null}
          <ActionStatus status={status} busy={busy} />
        </div>
        <SelectedInput label="语言表" artifact={sourceArtifact} />
        <div className="workflow-note-grid">
          <div><strong>{lang.short} 提示词</strong><span>{promptReady ? '已在元信息页生成' : '未生成'}</span></div>
          <div><strong>项目术语库</strong><span>{glossaryCount} 条，run 开始时生成快照</span></div>
          <div><strong>质量门槛</strong><span>必须修复问题为 0 才能交付</span></div>
        </div>
      </div>
      <TaskHistoryTable project={project} kind="translation" title="🕒 翻译历史记录" />
      {latestRun && latestRun.kind === 'translation' ? <TaskRunSummary run={latestRun} /> : null}
    </>
  )
}

function DeliveryTab({
  project,
  deliverables,
  busy,
  status,
  onCreateDelivery
}: {
  project: Project
  deliverables: DeliverableTask[]
  busy: boolean
  status: string
  onCreateDelivery: (runId: string) => void
}) {
  return (
    <div className="card">
      <div className="card-title">
        <div className="left">最终交付</div>
      </div>
      {!deliverables.length ? <div className="warn-line">暂无最终交付，需先完成翻译/校对并通过 QA。</div> : null}
      <ActionStatus status={status} busy={busy} />
      <div className="delivery-list">
        {deliverables.map((task) => {
          const finalFile = task.files.final
          const changesFile = task.files.changes
          return (
            <div key={task.run_id} className="delivery-card">
              <div className="delivery-head">
                <div>
                  <strong>{project.name} · {task.language} · {task.task_label}</strong>
                  <span>{task.task_type} / {task.input_label || '-'}</span>
                </div>
                <span className="tag tag-done">{task.qa_status || task.status}</span>
              </div>
              <div className="delivery-meta">
                <div><strong>任务时间</strong><span>{formatDateTime(task.created_at)}</span></div>
                <div><strong>任务类型</strong><span>{task.task_type}</span></div>
                <div><strong>处理条数</strong><span>{task.processed_rows || 0}</span></div>
                <div><strong>完成状态</strong><span>{task.status}</span></div>
                <div><strong>模型/来源</strong><span>{[task.provider, task.model].filter((item) => item && item !== '-').join(' / ') || '-'}</span></div>
                <div><strong>QA 结果</strong><span>必须修复 {task.qa_hard_errors ?? 0} / 建议修复 {task.qa_soft_warnings ?? 0}</span></div>
              </div>
              <div className="row-actions">
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onCreateDelivery(task.run_id)}>生成/刷新最终交付文件</button>
                {finalFile?.download_url ? <a className="btn btn-ghost btn-sm" href={finalFile.download_url}>最终译文 Excel</a> : <span className="muted-inline">最终译文 Excel 未生成</span>}
                {changesFile?.download_url ? <a className="btn btn-ghost btn-sm" href={changesFile.download_url}>修改记录 Excel</a> : <span className="muted-inline">修改记录 Excel 未生成</span>}
              </div>
              <div className="delivery-files">
                <span>{finalFile?.filename || '-'}</span>
                <span>{changesFile?.filename || '-'}</span>
              </div>
            </div>
          )
        })}
      </div>
      <div className="muted-left">语言包最终交付固定为最终译文 Excel + 修改记录 Excel；术语、提示词、workpack 等过程产物不放入最终交付。</div>
    </div>
  )
}

function providerName(settings: AppSettings | null): string {
  if (!settings) return '未加载'
  if (settings.provider === 'openai') return 'GPT'
  if (settings.provider === 'anthropic') return 'Claude'
  if (settings.provider === 'mock') return 'Mock（仅测试）'
  return settings.provider || '未配置'
}

function formalTranslationBlockReason(settings: AppSettings | null, sourceArtifact: Artifact | null, project?: Project, readiness?: TranslationReadiness | null): string {
  if (!sourceArtifact) return '请先上传或选择待翻译语言表。'
  if (!settings) return '模型配置尚未加载。'
  const readinessBlock = translationReadinessBlockReason(readiness)
  if (readinessBlock) return readinessBlock
  if (settings.provider === 'mock' && project?.name.startsWith('E2E ')) return ''
  if (settings.provider === 'mock') return '当前是 mock provider。真实项目禁止用 mock 假装完成，请先配置 GPT API key。'
  if ((settings.provider === 'openai' || settings.provider === 'anthropic') && !settings.api_key) return `${providerName(settings)} API key 未配置，正式翻译已阻断。`
  return ''
}

function translationReadinessBlockReason(readiness?: TranslationReadiness | null): string {
  if (!readiness) return ''
  if (Number(readiness.invalid_id_rows || 0) > 0) {
    const samples = readiness.invalid_id_samples?.length ? ` 示例：${readiness.invalid_id_samples.join(', ')}` : ''
    return `语言表有 ${readiness.invalid_id_rows} 行缺少可回写 ID；请先补齐非空 ID。${samples}`
  }
  if (readiness.reason === 'no_source_rows') return '语言表未检测到原文行。'
  return ''
}


const announcementSteps = ['公告资料', '约束来源', '目标语言', '术语提取', '译文反查', '翻译准备', 'AI翻译/导入', '校对回填', '交付']

function activeAnnouncementTasks(tasks: AnnouncementTask[]): AnnouncementTask[] {
  return tasks.filter((task) => task.status !== 'canceled')
}

function AnnouncementProjectPanel({
  tasks,
  holdTaskId,
  onStartAnnouncement,
  onStartTask,
  onBeginCancelHold,
  onCancelHold
}: {
  tasks: AnnouncementTask[]
  holdTaskId: string
  onStartAnnouncement: () => void
  onStartTask: (task: AnnouncementTask) => void
  onBeginCancelHold: (task: AnnouncementTask) => void
  onCancelHold: () => void
}) {
  const activeTasks = activeAnnouncementTasks(tasks)
  const latest = activeTasks[0]
  return (
    <div className="card tight announcement-project-panel">
      <div className="card-title">
        <div className="left">📣 公告任务 / 外文本</div>
        <button className="btn btn-ghost btn-sm" onClick={onStartAnnouncement}>进入公告工作流</button>
      </div>
      {!activeTasks.length ? (
        <div className="panel-desc">暂无公告任务。公告翻译归属于当前项目，用项目术语、QA归档和项目提示词约束游戏外文本。</div>
      ) : (
        <div className="announcement-task-list">
          {activeTasks.slice(0, 4).map((task) => (
            <div
              key={task.id}
              className={`announcement-task-row ${holdTaskId === task.id ? 'cancel-hold' : ''}`}
              onPointerDown={(event) => { if (event.button === 0) onBeginCancelHold(task) }}
              onPointerUp={onCancelHold}
              onPointerLeave={onCancelHold}
              onPointerCancel={onCancelHold}
            >
              <div>
                <strong>{task.title || task.id}</strong>
                <span>{task.source_format?.toUpperCase() || '-'} · STEP {task.current_step || 1}/9 · {announcementStatusLabel(task.status)}</span>
                <span>{announcementLanguageSummary(task)}</span>
              </div>
              <button className="btn btn-ghost btn-sm" onPointerDown={(event) => event.stopPropagation()} onClick={() => onStartTask(task)}>继续</button>
            </div>
          ))}
          {latest ? <div className="panel-desc">最近任务：{latest.title || latest.id}</div> : null}
        </div>
      )}
    </div>
  )
}

function announcementStatusLabel(status?: string): string {
  const labels: Record<string, string> = {
    created: '已创建',
    constraints_ready: '约束已识别',
    languages_ready: '目标语言已确认',
    terms_ready: '术语已提取',
    lookup_ready: '译文已反查',
    prepared: '翻译准备完成',
    queued: '后台排队',
    running: '后台翻译中',
    needs_input: '需要确认/继续',
    translated: '译文已导入',
    applied: '已回填',
    delivered: '已交付',
    canceled: '已取消',
    failed: '失败',
  }
  return labels[status || ''] || status || '未开始'
}

function announcementLanguageSummary(task: AnnouncementTask): string {
  const languages = normalizeLanguageArray(task.selected_languages || [])
  return languages.length ? `目标语言：${languages.map((lang) => languageSpec(lang).short).join(' / ')}` : '目标语言：待识别'
}

function getAnnouncementTranslationProgress(task: AnnouncementTask | null): TranslationProgress | null {
  const progress = task?.metadata?.translation_progress as TranslationProgress | undefined
  return progress?.total_rows ? progress : null
}

function AnnouncementWizard({
  project,
  busy,
  status,
  settings,
  assetArtifacts,
  onUploadAsset,
  onUploadConstraint,
  onUploadTermsFile,
  onUploadResponse,
  onCreateTask,
  onTaskAction,
  onBeginAnnouncementCancelHold,
  onCancelAnnouncementHold,
  announcementCancelHoldTaskId,
  initialTaskId,
  onBack
}: {
  project: Project
  busy: boolean
  status: string
  settings: AppSettings | null
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  assetArtifacts: Artifact[]
  announcementText: string
  setAnnouncementText: (value: string) => void
  lookupResult: AnnouncementLookupResult | null
  onUploadAsset: (file: File) => Promise<Artifact | null>
  onUploadConstraint: (file: File) => Promise<Artifact | null>
  onUploadTermsFile: (file: File) => Promise<Artifact | null>
  onUploadResponse: (file: File) => Promise<Artifact | null>
  onCreateTask: (payload: Record<string, unknown>) => Promise<AnnouncementTask | null>
  onTaskAction: (taskId: string, endpoint: string, payload?: Record<string, unknown>) => Promise<AnnouncementTaskResult | null>
  onLookup: (text: string, materialArtifactIds: string[], options: AnnouncementLookupOptions) => void
  onBeginAnnouncementCancelHold: (task: AnnouncementTask) => void
  onCancelAnnouncementHold: () => void
  announcementCancelHoldTaskId: string
  initialTaskId: string
  onBack: () => void
}) {
  const tasks = activeAnnouncementTasks(project.announcement_tasks || [])
  const [step, setStep] = useState(1)
  const [taskId, setTaskId] = useState(initialTaskId || tasks[0]?.id || '')
  const activeTask = tasks.find((task) => task.id === taskId) || null
  const [sourceArtifactId, setSourceArtifactId] = useState(activeTask?.source_artifact_id || '')
  const [constraintArtifactIds, setConstraintArtifactIds] = useState<string[]>(announcementTaskConstraintIds(activeTask))
  const [selectedLanguages, setSelectedLanguages] = useState<LanguageCode[]>(activeTask?.selected_languages?.length ? activeTask.selected_languages : [])
  const [responseArtifactIds, setResponseArtifactIds] = useState<string[]>([])
  const [aiSupplement, setAiSupplement] = useState(() => {
    const aiMeta = (activeTask?.metadata || {}).ai_supplement as Record<string, unknown> | undefined
    return aiMeta?.enabled !== false
  })
  const [aiSupplementResponseArtifactId, setAiSupplementResponseArtifactId] = useState('')
  const artifacts = project.artifacts || []
  const sourceCandidates = pickerArtifacts([...assetArtifacts, ...artifacts.filter((artifact) => artifact.kind === 'asset')].filter(isAnnouncementSourceDocument))
  const hiddenAnnouncementTermsArtifacts = artifacts.filter(isGeneratedAnnouncementTermsArtifact)
  const constraintCandidates = pickerArtifacts(artifacts.filter((artifact) => artifact.kind === 'language_table' && !isGeneratedAnnouncementTermsArtifact(artifact)))
  const selectableConstraintIds = new Set(constraintCandidates.map((artifact) => artifact.id))
  const activeConstraintArtifactIds = constraintArtifactIds.filter((id) => selectableConstraintIds.has(id))
  const activeMeta = (activeTask?.metadata || {}) as Record<string, unknown>
  const detectedLanguages = normalizeLanguageArray(activeMeta.detected_languages)
  const effectiveLanguages = selectedLanguages
  const providerReady = settings?.provider && settings.provider !== 'mock' && settings.api_key === 'configured'
  const showLanguageSubflows = Boolean(activeTask && step >= 6)

  useEffect(() => {
    if (initialTaskId && tasks.some((task) => task.id === initialTaskId)) {
      setTaskId(initialTaskId)
      return
    }
    if (taskId && !tasks.some((task) => task.id === taskId)) {
      setTaskId(tasks[0]?.id || '')
      return
    }
    if (!taskId && tasks[0]) setTaskId(tasks[0].id)
  }, [initialTaskId, tasks.length, taskId])

  useEffect(() => {
    if (!activeTask) return
    setStep(activeTask.current_step || 1)
    setSourceArtifactId(activeTask.source_artifact_id || '')
    setConstraintArtifactIds(announcementTaskConstraintIds(activeTask))
    setSelectedLanguages(activeTask.selected_languages?.length ? activeTask.selected_languages : normalizeLanguageArray((activeTask.metadata || {}).detected_languages))
    const aiMeta = (activeTask.metadata || {}).ai_supplement as Record<string, unknown> | undefined
    setAiSupplement(aiMeta?.enabled !== false)
    setAiSupplementResponseArtifactId(String(aiMeta?.response_artifact_id || ''))
  }, [activeTask?.id, activeTask?.updated_at])

  function toggleConstraint(id: string) {
    setConstraintArtifactIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id])
  }

  function toggleLanguage(code: LanguageCode) {
    setSelectedLanguages((prev) => prev.includes(code) ? prev.filter((item) => item !== code) : [...prev, code])
  }

  async function createTaskFromCurrent() {
    const task = await onCreateTask({
      source_artifact_id: sourceArtifactId,
      language_table_artifact_ids: activeConstraintArtifactIds,
      constraint_artifact_ids: activeConstraintArtifactIds,
      languages: selectedLanguages,
      include_project_archive: true,
      output_policy: 'same_format'
    })
    if (task) {
      setTaskId(task.id)
      setStep(2)
    }
  }

  async function run(endpoint: string, nextStep?: number, extra: Record<string, unknown> = {}) {
    if (!activeTask) return
    const result = await onTaskAction(activeTask.id, endpoint, {
      language_table_artifact_ids: activeConstraintArtifactIds,
      constraint_artifact_ids: activeConstraintArtifactIds,
      languages: effectiveLanguages,
      include_project_archive: true,
      response_artifact_ids: responseArtifactIds,
      ai_supplement: aiSupplement,
      ai_supplement_response_artifact_id: aiSupplementResponseArtifactId || undefined,
      ...extra
    })
    if (result?.task) setTaskId(result.task.id)
    if (result && nextStep) setStep(nextStep)
  }

  async function importExtractedTermsFile(file: File) {
    if (!activeTask) return
    const artifact = await onUploadTermsFile(file)
    if (!artifact) return
    await run('import-terms', 4, { terms_artifact_id: artifact.id })
  }

  async function saveEditedTerms(terms: AnnouncementTermRow[], languages: LanguageCode[]) {
    await run('import-terms', 4, { terms, languages })
  }

  return (
    <div className="wizard announcement-wizard">
      <div className="proj-head">
        <div>
          <h2>📣 公告翻译 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">单文档多语言外文本工作流：先提取公告术语，再按 QA 归档优先反查译文，最后走 AI 翻译、QA 回填和交付。不会使用谷歌机翻。</div>
        </div>
        <button className="btn btn-ghost" onClick={onBack}>← 返回项目概览</button>
      </div>

      <div className="steps-nav announcement-steps">
        {announcementSteps.map((title, index) => (
          <button key={title} className={`step-item ${index + 1 === step ? 'active' : activeTask && (activeTask.current_step || 1) > index + 1 ? 'done' : ''}`} onClick={() => setStep(index + 1)}>
            <span className="num">{index + 1}</span>{title}
          </button>
        ))}
      </div>
      <ActionStatus status={status} busy={busy} />
      {activeTask ? (
        <div
          className={`announcement-current-task ${announcementCancelHoldTaskId === activeTask.id ? 'cancel-hold' : ''}`}
          onPointerDown={(event) => { if (event.button === 0) onBeginAnnouncementCancelHold(activeTask) }}
          onPointerUp={onCancelAnnouncementHold}
          onPointerLeave={onCancelAnnouncementHold}
          onPointerCancel={onCancelAnnouncementHold}
        >
          <span>当前公告任务：{activeTask.title || activeTask.id}</span>
          <em>STEP {activeTask.current_step || 1}/9 · {announcementStatusLabel(activeTask.status)} · 长按取消</em>
        </div>
      ) : null}

      <div className="announcement-shell">
        <section className="wizard-panel announcement-panel">
          {showLanguageSubflows ? (
            <AnnouncementLanguageSubflows
              task={activeTask}
              effectiveLanguages={effectiveLanguages}
              detectedLanguages={detectedLanguages}
              onToggleLanguage={toggleLanguage}
            />
          ) : null}
          {step === 1 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 1</span>公告资料</div>
              <div className="panel-desc">上传一个待翻译公告文档。v1 支持 DOCX / TXT / XLSX；默认交付同格式，同时保留 Excel 中转表和 QA 摘要。</div>
              <div className="upload-row">
                <FileBox label="上传公告源文档（DOCX / TXT / XLSX）" onFile={async (file) => { const artifact = await onUploadAsset(file); if (artifact) setSourceArtifactId(artifact.id) }} />
                <div className="asset-list">
                  <div className="ai-header">选择公告源文档</div>
                  {!sourceCandidates.length ? <div className="warn-line">暂无源文档，请先上传。</div> : null}
                  {sourceCandidates.map((artifact) => (
                    <label key={artifact.id} className="check-row">
                      <input type="radio" name="announcement-source" checked={sourceArtifactId === artifact.id} onChange={() => setSourceArtifactId(artifact.id)} />
                      <span>{artifactPickerLabel(artifact)}<em>{artifactFileName(artifact)}</em></span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="row-actions">
                <button className="btn btn-primary" disabled={busy || !sourceArtifactId} onClick={createTaskFromCurrent}>{activeTask ? '用当前选择新建任务' : '创建公告任务'}</button>
                {activeTask ? <button className="btn btn-ghost" onClick={() => setStep(2)}>继续当前任务</button> : null}
              </div>
            </>
          ) : step === 2 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 2</span>约束来源</div>
              <div className="panel-desc">选择完整语言表 / 完整术语交付表，用它从公告原文里反查并生成本任务公告术语表；已生成的公告术语表请在 STEP 4 导入，不放在这里。</div>
              <div className="upload-row">
                <FileBox label="上传语言表 / 术语交付表（XLSX）" onFile={async (file) => { const artifact = await onUploadConstraint(file); if (artifact) setConstraintArtifactIds((prev) => [...new Set([artifact.id, ...prev])]) }} />
                <div className="asset-list">
                  <div className="ai-header">约束文件</div>
                  {!constraintCandidates.length ? <div className="warn-line">没有约束文件；仍可只用项目 QA 归档或生成缺约束提示。</div> : null}
                  {hiddenAnnouncementTermsArtifacts.length ? <div className="warn-line">已隐藏 {hiddenAnnouncementTermsArtifacts.length} 个已生成公告术语表；如需复用，请到 STEP 4 导入。</div> : null}
                  {constraintCandidates.map((artifact) => (
                    <label key={artifact.id} className="check-row">
                      <input type="checkbox" checked={constraintArtifactIds.includes(artifact.id)} onChange={() => toggleConstraint(artifact.id)} />
                      <span>{artifactPickerLabel(artifact)}<em>{artifactFileName(artifact)}</em></span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="workflow-note-grid">
                <div><strong>项目 QA 归档</strong><span>默认参与，且优先级高于语言表</span></div>
                <div><strong>已选约束文件</strong><span>{activeConstraintArtifactIds.length} 个</span></div>
                <div><strong>当前任务</strong><span>{activeTask ? activeTask.id : '请先创建任务'}</span></div>
              </div>
              <div className="row-actions"><button className="btn btn-primary" disabled={!activeTask || busy} onClick={() => run('inspect-constraints', 3)}>识别语言与约束</button></div>
            </>
          ) : step === 3 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 3</span>目标语言</div>
              <div className="panel-desc">系统从约束文件和项目归档识别目标语言；识别到的语言默认勾选，也可以手动勾选或取消。</div>
              <div className="announcement-language-chip-grid">
                {announcementLanguages.map((lang) => {
                  const selected = effectiveLanguages.includes(lang.code)
                  const detected = detectedLanguages.includes(lang.code)
                  return (
                    <label key={lang.code} className={`announcement-language-chip ${selected ? 'selected' : ''} ${detected ? 'detected' : 'manual'}`}>
                      <input type="checkbox" checked={selected} onChange={() => toggleLanguage(lang.code)} />
                      <span><strong>{languageChipTitle(lang)}</strong><em>{detected ? '已识别' : '手动'} · {selected ? '已选' : '未选'}</em></span>
                    </label>
                  )
                })}
              </div>
              <div className="row-actions"><button className="btn btn-primary" disabled={!activeTask || busy || !effectiveLanguages.length} onClick={() => run('inspect-constraints', 4, { confirm_languages: true })}>确认目标语言</button></div>
            </>
          ) : step === 4 ? (
            <AnnouncementTermsStep
              activeTask={activeTask}
              busy={busy}
              effectiveLanguages={effectiveLanguages}
              onExtract={(enabled, responseArtifactId) => run('extract-terms', 4, { ai_supplement: enabled, ai_supplement_response_artifact_id: responseArtifactId || undefined })}
              onImportFile={importExtractedTermsFile}
              onUploadAiSupplementResponse={async (file) => { const artifact = await onUploadResponse(file); if (artifact) setAiSupplementResponseArtifactId(artifact.id) }}
              onSaveTerms={saveEditedTerms}
              aiSupplement={aiSupplement}
              setAiSupplement={setAiSupplement}
              aiSupplementResponseArtifactId={aiSupplementResponseArtifactId}
            />
          ) : step === 5 ? (
            <AnnouncementActionStep title="译文反查" step={5} desc="按目标语言从项目 QA 归档和语言表反查译文，QA 归档优先；缺失术语会标记但不阻断翻译准备。" activeTask={activeTask} busy={busy} actionLabel="反查术语译文" onAction={() => run('lookup-translations', 6)} />
          ) : step === 6 ? (
            <AnnouncementActionStep title="翻译准备" step={6} desc="按语言生成中转表、manifest、prompt snapshot 和 workpack。后续可直接调用 AI provider 或下载 workpack 外部翻译。" activeTask={activeTask} busy={busy} actionLabel="生成翻译准备包" onAction={() => run('prepare', 7)} />
          ) : step === 7 ? (
            <>
              <div className="panel-title"><span className="badge">STEP 7</span>AI 翻译 / 导入</div>
              <div className="panel-desc">有正式 OpenAI/Claude 配置时可直接翻译；否则下载 workpack 后上传外部 AI response。不会使用谷歌机翻或在线机翻聚合器。</div>
              {getAnnouncementTranslationProgress(activeTask) ? <TranslationProgressBar progress={getAnnouncementTranslationProgress(activeTask)!} /> : null}
              {activeTask?.metadata?.reason === 'background_job_interrupted' ? <div className="warn-line">后台翻译曾中断；可点击“调用已配置 AI 翻译”继续，已完成批次不会重跑。</div> : null}
              {activeTask?.metadata?.reason === 'api_budget_confirmation_required' ? <div className="warn-line">预计 API token 超过提醒阈值；请确认预算后再继续后台翻译。</div> : null}
              <div className="workflow-note-grid">
                <div><strong>AI provider</strong><span>{providerReady ? `${settings?.provider} 已配置` : '未配置或为 mock，建议上传 AI response'}</span></div>
                <div><strong>目标语言</strong><span>{effectiveLanguages.map((lang) => languageSpec(lang).short).join(' / ') || '-'}</span></div>
                <div><strong>上传 response</strong><span>{responseArtifactIds.length} 个</span></div>
              </div>
              <div className="upload-row">
                <FileBox label="上传 ai_response_<lang>.jsonl" onFile={async (file) => { const artifact = await onUploadResponse(file); if (artifact) setResponseArtifactIds((prev) => [...new Set([artifact.id, ...prev])]) }} />
                <ArtifactLinks artifacts={activeTask?.artifacts || []} kinds={["announcement_workpack", "prompt_snapshot", "announcement_translation_workbook"]} />
              </div>
              <div className="row-actions">
                <button
                  className="btn btn-ghost"
                  disabled={!activeTask || busy}
                  onClick={() => {
                    const needsBudgetConfirm = activeTask?.metadata?.reason === 'api_budget_confirmation_required'
                    const confirmed = needsBudgetConfirm ? window.confirm('该公告翻译预计 API token 用量超过提醒阈值。确认后会从已完成批次继续。是否继续？') : false
                    if (needsBudgetConfirm && !confirmed) return
                    run('translate/start', undefined, { confirm_api_budget: confirmed })
                  }}
                >
                  {activeTask?.status === 'needs_input' ? '确认后继续 AI 翻译' : '调用已配置 AI 翻译'}
                </button>
                <button className="btn btn-ghost" disabled={!activeTask || busy || !['queued', 'running'].includes(activeTask?.status || '')} onClick={() => run('translate/cancel', 7)}>暂停后台翻译</button>
                <button className="btn btn-primary" disabled={!activeTask || busy || !responseArtifactIds.length} onClick={() => run('import-ai', 8)}>导入 AI response</button>
              </div>
            </>
          ) : step === 8 ? (
            <AnnouncementActionStep title="校对回填" step={8} desc="按语言校验 ID、顺序、变量、标签、术语、中文残留和格式指纹；hard blocker 未清零不生成最终交付包。" activeTask={activeTask} busy={busy} actionLabel="QA 并回填同格式文件" onAction={() => run('apply', 9)} />
          ) : (
            <AnnouncementActionStep title="交付" step={9} desc="生成公告交付总包：只包含按语言分目录的成品和 QA 摘要；中转表、manifest、workpack 留在过程产物区。" activeTask={activeTask} busy={busy} actionLabel="生成交付总包" onAction={() => run('deliver', 9, { date_stamp: new Date().toISOString().slice(0, 10).replace(/-/g, '') })} />
          )}

          {activeTask ? <AnnouncementTaskArtifacts task={activeTask} /> : null}
        </section>
      </div>
    </div>
  )
}

function AnnouncementTermsStep({
  activeTask,
  busy,
  effectiveLanguages,
  onExtract,
  onImportFile,
  onUploadAiSupplementResponse,
  onSaveTerms,
  aiSupplement,
  setAiSupplement,
  aiSupplementResponseArtifactId
}: {
  activeTask: AnnouncementTask | null
  busy: boolean
  effectiveLanguages: LanguageCode[]
  onExtract: (aiSupplement: boolean, aiSupplementResponseArtifactId: string) => void
  onImportFile: (file: File) => void
  onUploadAiSupplementResponse: (file: File) => void
  onSaveTerms: (terms: AnnouncementTermRow[], languages: LanguageCode[]) => void
  aiSupplement: boolean
  setAiSupplement: (value: boolean) => void
  aiSupplementResponseArtifactId: string
}) {
  const [draftTerms, setDraftTerms] = useState<AnnouncementTermRow[]>([])
  const languages = announcementTermLanguages(activeTask, effectiveLanguages)
  const meta = activeTask?.metadata || {}
  const exportArtifact = activeTask?.artifacts?.find((artifact) => artifact.id === meta.terms_artifact_id)
    || activeTask?.artifacts?.find((artifact) => artifact.kind === 'announcement_terms_workbook')
  const aiPacketArtifact = activeTask?.artifacts?.find((artifact) => artifact.kind === 'announcement_ai_supplement_packet')
  const aiReportArtifact = activeTask?.artifacts?.find((artifact) => artifact.kind === 'announcement_ai_supplement_report')
  const aiMeta = (meta.ai_supplement && typeof meta.ai_supplement === 'object' ? meta.ai_supplement : {}) as Record<string, unknown>
  const languageText = languages.map((lang) => languageSpec(lang).short).join(' / ') || '-'
  const aiStatus = aiSupplement
    ? aiMeta.provider_status === 'provider_response'
      ? 'API 已复查'
      : aiMeta.provider_status === 'provider_error'
        ? 'API 失败，已保留本地结果'
        : aiPacketArtifact
          ? '已生成检查包'
          : '默认开启'
    : '已关闭'

  useEffect(() => {
    setDraftTerms(announcementTermsFromTask(activeTask))
  }, [activeTask?.id, activeTask?.updated_at])

  function updateTerm(index: number, patch: Partial<AnnouncementTermRow>) {
    setDraftTerms((prev) => prev.map((term, termIndex) => termIndex === index ? { ...term, ...patch } : term))
  }

  function updateTranslation(index: number, language: LanguageCode, value: string) {
    setDraftTerms((prev) => prev.map((term, termIndex) => {
      if (termIndex !== index) return term
      return { ...term, translations: { ...(term.translations || {}), [language]: value } }
    }))
  }

  function addTerm() {
    setDraftTerms((prev) => [...prev, { id: '', source: '', translations: {} }])
  }

  function removeTerm(index: number) {
    setDraftTerms((prev) => prev.filter((_, termIndex) => termIndex !== index))
  }

  if (!activeTask) {
    return (
      <>
        <div className="panel-title"><span className="badge">STEP 4</span>术语提取</div>
        <div className="panel-desc">从公告原文中提取本次需要的术语，生成任务内临时术语表；可导出、上传已有提取结果模拟、编辑后保存，不自动写回项目术语库。</div>
        <div className="warn-line">请先在 STEP 1 创建公告任务。</div>
      </>
    )
  }

  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>术语提取</div>
      <div className="panel-desc">本步只做一件事：从公告原文生成任务内临时术语表。检查表格后保存，下一步再反查译文；不会写回项目术语库。</div>
      <div className="announcement-terms-guide">
        <div>
          <strong>操作顺序</strong>
          <span>1. 提取术语 → 2. 检查/删改下方表格 → 3. 保存或导出 → 进入 STEP 5 译文反查。</span>
        </div>
        <button className="btn btn-primary" disabled={busy} onClick={() => onExtract(aiSupplement, aiSupplementResponseArtifactId)}>{aiSupplement ? '提取术语并 AI 复查' : '仅本地提取术语'}</button>
      </div>
      <div className="announcement-terms-summary">
        <div><strong>源格式</strong><span>{activeTask.source_format?.toUpperCase() || '-'}</span></div>
        <div><strong>目标语言</strong><span>{languageText}</span></div>
        <div><strong>术语</strong><span>{draftTerms.length ? `${draftTerms.length} 条` : '未提取'}</span></div>
        <div><strong>AI 复查</strong><span>{aiStatus}</span></div>
      </div>
      <div className="announcement-terms-editor-head">
        <div>
          <strong>临时术语表</strong>
          <span>可直接改表格。保存后会重新生成导出表，不会污染项目术语库。</span>
        </div>
        <div className="row-actions wrap">
          <button className="btn btn-ghost" disabled={busy || !draftTerms.length} onClick={() => onSaveTerms(draftTerms, languages)}>保存编辑</button>
          <button className="btn btn-ghost" disabled={busy} onClick={addTerm}>+ 新增术语</button>
          {exportArtifact ? <a className="btn btn-ghost" href={`/api/artifacts/${exportArtifact.id}/download`}>导出 XLSX</a> : null}
        </div>
      </div>
      <details className="asset-list gap-top optional-panel" open={!draftTerms.length || Boolean(aiPacketArtifact || aiReportArtifact)}>
        <summary>更多操作：导入已有术语 / AI 复查设置 / 审计产物</summary>
        <div className="announcement-more-grid">
          <FileBox label="上传已提取术语表（XLSX）" onFile={onImportFile} />
          <div className="asset-list compact-asset-list">
            <label className="check-row">
              <input type="checkbox" checked={aiSupplement} onChange={(event) => setAiSupplement(event.target.checked)} />
              <span>默认启用 AI 漏词复查<em>API 已配置时自动复查；没配置时只生成检查包，不阻断本地提取。</em></span>
            </label>
            <div className="row-actions wrap gap-top">
              {aiPacketArtifact ? <a className="btn btn-ghost btn-sm" href={`/api/artifacts/${aiPacketArtifact.id}/download`}>下载检查包</a> : null}
              {aiReportArtifact ? <a className="btn btn-ghost btn-sm" href={`/api/artifacts/${aiReportArtifact.id}/download`}>下载 AI 报告</a> : null}
            </div>
            <div className="gap-top">
              <FileBox label="上传外部 AI 结果 JSON（可选）" onFile={onUploadAiSupplementResponse} />
            </div>
          </div>
        </div>
      </details>
      {!draftTerms.length ? (
        <div className="warn-line gap-top">暂无术语。点击上方主按钮提取；如果已有 announcement_terms.xlsx，可在“更多操作”里上传。</div>
      ) : (
        <div className="announcement-terms-table-wrap gap-top">
          <table className="announcement-terms-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>CN</th>
                {languages.map((language) => <th key={language}>{languageSpec(language).targetHeader}</th>)}
                <th>命中</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {draftTerms.map((term, index) => (
                <tr key={`${index}-${term.id || ''}`}>
                  <td><input value={term.id || ''} onChange={(event) => updateTerm(index, { id: event.target.value })} /></td>
                  <td><input value={term.source || ''} onChange={(event) => updateTerm(index, { source: event.target.value })} /></td>
                  {languages.map((language) => (
                    <td key={language}><input value={(term.translations || {})[language] || ''} onChange={(event) => updateTranslation(index, language, event.target.value)} /></td>
                  ))}
                  <td>{term.hit_count ?? '-'}</td>
                  <td><button className="btn btn-ghost btn-sm" onClick={() => removeTerm(index)}>删除</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

function announcementTermsFromTask(task: AnnouncementTask | null): AnnouncementTermRow[] {
  const terms = task?.metadata?.terms
  if (!Array.isArray(terms)) return []
  return terms.map((item, index) => {
    const row = item as Record<string, unknown>
    const translations = (row.translations && typeof row.translations === 'object' ? row.translations : {}) as Record<string, unknown>
    const normalizedTranslations: Record<string, string> = {}
    for (const [key, value] of Object.entries(translations)) {
      const language = normalizeLanguageCode(key)
      if (language) normalizedTranslations[language] = String(value || '')
    }
    return {
      id: String(row.id || row.term_key || index + 1),
      source: String(row.source || row.cn || ''),
      translations: normalizedTranslations,
      hit_count: typeof row.hit_count === 'number' ? row.hit_count : undefined,
      first_position: typeof row.first_position === 'number' ? row.first_position : undefined
    }
  })
}

function announcementTermLanguages(task: AnnouncementTask | null, effectiveLanguages: LanguageCode[]): LanguageCode[] {
  const found = new Set<LanguageCode>()
  effectiveLanguages.forEach((language) => found.add(language))
  normalizeLanguageArray(task?.selected_languages || []).forEach((language) => found.add(language))
  normalizeLanguageArray((task?.metadata || {}).languages).forEach((language) => found.add(language))
  for (const term of announcementTermsFromTask(task)) {
    Object.keys(term.translations || {}).forEach((language) => {
      const code = normalizeLanguageCode(language)
      if (code) found.add(code)
    })
  }
  return allLanguageOptions.map((language) => language.code).filter((code) => found.has(code))
}


function AnnouncementActionStep({ title, step, desc, activeTask, busy, actionLabel, onAction }: { title: string; step: number; desc: string; activeTask: AnnouncementTask | null; busy: boolean; actionLabel: string; onAction: () => void }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP {step}</span>{title}</div>
      <div className="panel-desc">{desc}</div>
      {!activeTask ? <div className="warn-line">请先在 STEP 1 创建公告任务。</div> : null}
      <AnnouncementTaskSnapshot task={activeTask} />
      <div className="row-actions"><button className="btn btn-primary" disabled={!activeTask || busy} onClick={onAction}>{actionLabel}</button></div>
    </>
  )
}

function AnnouncementLanguageSubflows({
  task,
  effectiveLanguages,
  detectedLanguages,
  onToggleLanguage
}: {
  task: AnnouncementTask | null
  effectiveLanguages: LanguageCode[]
  detectedLanguages: LanguageCode[]
  onToggleLanguage: (code: LanguageCode) => void
}) {
  if (!task) return null
  return (
    <div className="announcement-subflow-strip">
      <div className="ai-header">语言子流程</div>
      <div className="announcement-subflow-row">
        {announcementLanguages.map((lang) => {
          const child = task.languages?.find((item) => item.language === lang.code)
          const selected = effectiveLanguages.includes(lang.code)
          if (!selected && !child && !detectedLanguages.includes(lang.code)) return null
          return (
            <button key={lang.code} className={`announcement-subflow-card ${selected ? 'selected' : ''} ${child ? child.status : 'is-empty'}`} onClick={() => onToggleLanguage(lang.code)}>
              <strong>{lang.label}</strong>
              <span>{child ? `STEP ${child.current_step}/9` : selected ? '已选择' : '未选择'}</span>
              <em>{child?.status || (detectedLanguages.includes(lang.code) ? '检测到约束' : '待选择')}</em>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function AnnouncementTaskSnapshot({ task }: { task: AnnouncementTask | null }) {
  if (!task) return null
  const meta = task.metadata || {}
  return (
    <div className="workflow-note-grid">
      <div><strong>任务状态</strong><span>{task.status} · STEP {task.current_step}/9</span></div>
      <div><strong>源格式</strong><span>{task.source_format?.toUpperCase() || '-'}</span></div>
      <div><strong>目标语言</strong><span>{(task.selected_languages || []).map((lang) => languageSpec(lang).short).join(' / ') || '-'}</span></div>
      <div><strong>术语数</strong><span>{String((meta.terms_summary as Record<string, unknown> | undefined)?.terms ?? '-')}</span></div>
      <div><strong>缺失术语</strong><span>{String((meta.lookup_summary as Record<string, unknown> | undefined)?.missing_terms ?? '-')}</span></div>
      <div><strong>Hard blocker</strong><span>{String(meta.hard_blockers ?? '-')}</span></div>
    </div>
  )
}

function AnnouncementTaskArtifacts({ task }: { task: AnnouncementTask }) {
  const artifacts = task.artifacts || []
  if (!artifacts.length) return null
  const finalKinds = new Set(['announcement_delivery_package', 'announcement_docx_delivery_package'])
  const qaKinds = new Set(['announcement_output_file', 'announcement_docx_output_docx', 'announcement_qa_summary', 'announcement_docx_qa_summary'])
  const finalArtifacts = pickerArtifacts(artifacts.filter((artifact) => finalKinds.has(artifact.kind)))
  const qaArtifacts = pickerArtifacts(artifacts.filter((artifact) => qaKinds.has(artifact.kind)))
  const processArtifacts = pickerArtifacts(artifacts.filter((artifact) => !finalKinds.has(artifact.kind) && !qaKinds.has(artifact.kind)))
  return (
    <div className="card tight announcement-artifacts">
      <div className="card-title"><div className="left">任务产物</div></div>
      {finalArtifacts.length ? (
        <div className="asset-list">
          <div className="ai-header">最终交付</div>
          <div className="row-actions wrap">
            {finalArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-primary btn-sm" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}</a>)}
          </div>
        </div>
      ) : null}
      {qaArtifacts.length ? (
        <div className="asset-list">
          <div className="ai-header">成品与 QA</div>
          <div className="row-actions wrap">
            {qaArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-ghost btn-sm" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}</a>)}
          </div>
        </div>
      ) : null}
      {processArtifacts.length ? (
        <details className="asset-list">
          <summary className="ai-header">过程产物 / 审计产物（{processArtifacts.length}）</summary>
          <div className="row-actions wrap">
            {processArtifacts.map((artifact) => <a key={artifact.id} className="btn btn-ghost btn-sm" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}</a>)}
          </div>
        </details>
      ) : null}
    </div>
  )
}

function announcementArtifactTypeLabel(artifact: Artifact): string {
  if (artifact.kind.includes('delivery_package')) return '公告交付 ZIP'
  if (artifact.kind.includes('qa_summary')) return 'QA 摘要'
  if (artifact.kind.includes('output')) return '公告成品'
  if (artifact.kind.includes('workpack')) return '过程产物 / 审计产物'
  if (artifact.kind.includes('manifest')) return '过程产物 / 审计产物'
  if (artifact.kind.includes('prompt')) return '过程产物 / 审计产物'
  if (artifact.kind.includes('ai_supplement_packet')) return 'AI 补充包'
  if (artifact.kind.includes('ai_supplement_response')) return 'AI 补充响应'
  if (artifact.kind.includes('ai_supplement_report')) return 'AI 补充报告'
  if (artifact.kind.includes('translation_workbook')) return '中转表'
  if (artifact.kind.includes('terms')) return '公告术语表'
  return '过程产物 / 审计产物'
}

function ArtifactLinks({ artifacts, kinds }: { artifacts: Artifact[]; kinds: string[] }) {
  const filtered = artifacts.filter((artifact) => kinds.includes(artifact.kind))
  return (
    <div className="asset-list">
      <div className="ai-header">可下载准备产物</div>
      {!filtered.length ? <div className="warn-line">准备产物尚未生成，请先完成 STEP 6。</div> : null}
      {filtered.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
    </div>
  )
}

function announcementTaskConstraintIds(task: AnnouncementTask | null): string[] {
  const meta = task?.metadata || {}
  const values = [...((meta.language_table_artifact_ids as string[] | undefined) || []), ...((meta.constraint_artifact_ids as string[] | undefined) || [])]
  return [...new Set(values.filter(Boolean))]
}

function normalizeLanguageCode(value: unknown): LanguageCode | null {
  const raw = String(value || '').trim().toLowerCase().replace('_', '-')
  const compact = raw.replace(/[\s-]/g, '')
  const aliases: Record<string, LanguageCode> = {
    kr: 'ko', jp: 'ja', fre: 'fr', ger: 'de', rus: 'ru', ita: 'it', spa: 'es', por: 'pt', ptbr: 'pt', 'pt-br': 'pt', tk: 'tr', tur: 'tr', id: 'idn', ind: 'idn', tha: 'th', ara: 'ar'
  }
  const code = aliases[raw] || aliases[compact] || raw
  return isLanguageCode(code) ? code : null
}

function normalizeLanguageArray(value: unknown): LanguageCode[] {
  if (!Array.isArray(value)) return []
  const normalized: LanguageCode[] = []
  for (const item of value) {
    const code = normalizeLanguageCode(item)
    if (code && !normalized.includes(code)) normalized.push(code)
  }
  return allLanguageOptions.map((lang) => lang.code).filter((code) => normalized.includes(code))
}

type QuickObjective = 'translate' | 'qa'

function quickTaskRuns(project: Project): Run[] {
  return (project.runs || []).filter((run) => run.metadata?.task_origin === 'quick_task')
}

function quickTaskName(run: Run): string {
  return run.kind === 'qa' ? '快速校对' : '快速翻译'
}

function QuickTaskRecent({ project }: { project: Project }) {
  const runs = quickTaskRuns(project).slice(0, 3)
  if (!runs.length) return null
  return (
    <div className="quick-recent">
      <div className="quick-recent-title">最近快速任务</div>
      {runs.map((run) => (
        <div key={run.id} className="quick-recent-item">
          <span>{quickTaskName(run)} · {languageSpec(normalizeLanguageCode(run.language) || 'en').short}</span>
          <em>{run.status}</em>
        </div>
      ))}
    </div>
  )
}

function QuickTaskWizard({
  project,
  busy,
  status,
  settings,
  latestRun,
  onBack,
  onUploadFile,
  onInspectTargets,
  onStartQuickTask,
  onViewResult
}: {
  project: Project
  busy: boolean
  status: string
  settings: AppSettings | null
  latestRun: Run | null
  onBack: () => void
  onUploadFile: (file: File, kind: string) => Promise<Artifact | null>
  onInspectTargets: (artifactId: string) => Promise<TranslationTargets | null>
  onStartQuickTask: (payload: { inputArtifact: Artifact; referenceArtifacts: Artifact[]; objective: QuickObjective; language: LanguageCode }) => Promise<Run | null>
  onViewResult: (run: Run | null) => void
}) {
  const [quickStep, setQuickStep] = useState(1)
  const [inputArtifact, setInputArtifact] = useState<Artifact | null>(null)
  const [referenceArtifacts, setReferenceArtifacts] = useState<Artifact[]>([])
  const [targets, setTargets] = useState<TranslationTargets | null>(null)
  const [objective, setObjective] = useState<QuickObjective>('translate')
  const [language, setLanguage] = useState<LanguageCode>('en')
  const [readiness, setReadiness] = useState<TranslationReadiness | null>(null)
  const [startedRun, setStartedRun] = useState<Run | null>(null)

  useEffect(() => {
    if (!inputArtifact?.id) {
      setReadiness(null)
      return
    }
    const batchSize = effectiveBatchSize(settings)
    let canceled = false
    api<TranslationReadiness>(`/api/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      .then((result) => {
        if (canceled) return
        setReadiness(result)
        if (canSkipModelTranslation(result)) setObjective('qa')
      })
      .catch(() => {
        if (!canceled) setReadiness(null)
      })
    return () => { canceled = true }
  }, [inputArtifact?.id, language, settings?.batch_size])

  async function uploadInput(file: File) {
    const artifact = await onUploadFile(file, 'quick_input')
    if (!artifact) return
    setInputArtifact(artifact)
    const inspected = await onInspectTargets(artifact.id)
    setTargets(inspected)
    const suggested = normalizeLanguageCode(inspected?.suggested_language) || inspected?.detected_languages?.[0] || 'en'
    setLanguage(suggested)
    setQuickStep(2)
  }

  async function uploadReference(file: File) {
    const artifact = await onUploadFile(file, 'quick_reference')
    if (!artifact) return
    setReferenceArtifacts((items) => uniqueArtifactsByContent([artifact, ...items]))
  }

  async function start() {
    if (!inputArtifact) return
    const run = await onStartQuickTask({ inputArtifact, referenceArtifacts, objective, language })
    if (run) setStartedRun(run)
  }

  const detected = normalizeLanguageArray(targets?.detected_languages)
  const quickRuns = quickTaskRuns(project).slice(0, 3)
  const lang = languageSpec(language)
  const readySummary = readiness
    ? `${readiness.source_rows} 行源文 / 已译 ${readiness.translated_rows} / 空译文 ${readiness.empty_target_rows} / 预计 ${readiness.estimated_batches || '-'} 批`
    : '上传后自动检查'
  const canStart = Boolean(inputArtifact && !busy)
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>⚡ 快速任务 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">三步启动翻译或校对；项目提示词、术语库和 QA 归档自动带入，上传参考只对本次任务生效。</div>
        </div>
        <button className="btn btn-ghost" onClick={onBack}>← 返回项目概览</button>
      </div>
      <div className="quick-steps">
        {['投入内容', '投入参考', '目标并启动'].map((title, index) => (
          <button key={title} className={`quick-step ${quickStep === index + 1 ? 'active' : quickStep > index + 1 ? 'done' : ''}`} onClick={() => setQuickStep(index + 1)}>
            <span>{index + 1}</span>{title}
          </button>
        ))}
      </div>
      <ActionStatus status={status} busy={busy} />
      <div className="quick-task-card">
        {quickStep === 1 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 1</span>投入要处理的内容</div>
            <div className="panel-desc">v1 先支持语言表 workbook。上传后系统只做本次任务输入，不写入长期语言表资产。</div>
            <div className="upload-row">
              <FileBox label="上传待翻译 / 待校对 workbook（XLSX）" onFile={uploadInput} testId="quick-input-upload" />
              {inputArtifact ? <ArtifactNote artifact={inputArtifact} /> : null}
            </div>
          </>
        ) : null}
        {quickStep === 2 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 2</span>投入可选参考</div>
            <div className="panel-desc">默认已经使用项目提示词、项目术语和 QA 归档；这里上传的术语表、风格说明或参考素材只作为本次 run 的临时约束。</div>
            <div className="quick-reference-row">
              <FileBox label="上传本次参考（可选）" onFile={uploadReference} testId="quick-reference-upload" />
              <div className="quick-reference-summary">
                <strong>已上传 {referenceArtifacts.length} 个参考</strong>
                <span>不会写入项目资产库；启动时会生成 reference snapshot。</span>
                {referenceArtifacts.length ? (
                  <div className="row-actions wrap">
                    {referenceArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
                  </div>
                ) : null}
              </div>
            </div>
            <div className="actions inline-actions">
              <button className="btn btn-ghost" onClick={() => setQuickStep(1)}>← 上一步</button>
              <button className="btn btn-primary" data-testid="quick-reference-next" onClick={() => setQuickStep(3)}>下一步：选择目标</button>
            </div>
          </>
        ) : null}
        {quickStep === 3 ? (
          <>
            <div className="panel-title"><span className="badge">STEP 3</span>选择目标并启动</div>
            <div className="panel-desc">语言从输入表头自动识别；识别不到时手动选择。质量门槛沿用正式翻译/QA 流程。</div>
            <div className="quick-launch-grid">
              <div className="quick-block">
                <label>任务目标</label>
                <div className="segmented-control">
                  <button data-testid="quick-objective-translate" className={objective === 'translate' ? 'active' : ''} onClick={() => setObjective('translate')}>翻译</button>
                  <button data-testid="quick-objective-qa" className={objective === 'qa' ? 'active' : ''} onClick={() => setObjective('qa')}>校对</button>
                </div>
              </div>
              <label className="quick-block">
                <span>目标语言</span>
                <select value={language} onChange={(event) => setLanguage(normalizeLanguageCode(event.target.value) || 'en')}>
                  {allLanguageOptions.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                </select>
                <em>{detected.length ? `已识别：${detected.map((item) => languageSpec(item).short).join(' / ')}` : '未识别语言，可手动选择'}</em>
              </label>
              <div className="quick-block">
                <strong>输入检查</strong>
                <span>{inputArtifact ? artifactPickerLabel(inputArtifact) : '未上传'}</span>
                <em>{readySummary}</em>
              </div>
            </div>
            {readiness && canSkipModelTranslation(readiness) ? <div className="warn-line">这份表已有可校对译文，系统已建议切换为校对。</div> : null}
            {settings?.provider === 'mock' && objective === 'translate' && !project.name.startsWith('E2E ') ? <div className="warn-line">当前是 mock provider，真实项目会阻断翻译；请先配置 GPT / Claude API key。</div> : null}
            <div className="row-actions">
              <button className="btn btn-ghost" onClick={() => setQuickStep(2)}>← 上一步</button>
              <button className="btn btn-primary" data-testid="quick-task-start" disabled={!canStart} onClick={start}>{objective === 'qa' ? `开始 ${lang.short} 校对` : `开始 ${lang.short} 翻译`}</button>
              <button className="btn btn-ghost" disabled={!startedRun && !latestRun} onClick={() => onViewResult(startedRun || latestRun)}>查看结果</button>
            </div>
            {startedRun ? <div className="scan-explain"><strong>{quickTaskName(startedRun)} 已创建</strong><span>{languageSpec(normalizeLanguageCode(startedRun.language) || language).short} · {startedRun.status} · {startedRun.id}</span></div> : null}
          </>
        ) : null}
      </div>
      {quickRuns.length ? (
        <div className="card tight">
          <div className="card-title"><div className="left">最近快速任务</div></div>
          <table>
            <thead><tr><th>类型</th><th>语言</th><th>状态</th><th>创建时间</th></tr></thead>
            <tbody>
              {quickRuns.map((run) => (
                <tr key={run.id}><td>{quickTaskName(run)}</td><td>{languageSpec(normalizeLanguageCode(run.language) || 'en').short}</td><td>{run.status}</td><td>{new Date(run.created_at).toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </>
  )
}

function Wizard(props: {
  project: Project
  step: number
  setStep: (step: number) => void
  intro: string
  setIntro: (value: string) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  qaArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  qualityIssues: QualityIssue[]
  settings: AppSettings | null
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  onBack: () => void
  onUploadSource: (file: File) => void
  onUploadTerm: (file: File) => void
  onUploadAsset: (file: File) => void
  onAnalyze: () => void
  onGlossaryExtract: () => void
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  onTranslate: () => void
  onCancelTranslate: () => void
  onDirectQA: () => void
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  onFreq: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  busy: boolean
}) {
  const { project, step, setStep } = props
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>🚀 新翻译任务 · 当前项目：{project.icon} {project.name}</h2>
          <div className="desc">完成 9 个步骤即可输出译文，过程中的术语、提示词和产物将回写到本项目。</div>
        </div>
        <button className="btn btn-ghost" onClick={props.onBack}>← 返回项目概览</button>
      </div>
      <div className="steps-nav">
        {steps.map((title, index) => (
          <button key={title} data-testid={`step-${index + 1}`} className={`step-item ${index + 1 === step ? 'active' : index + 1 < step ? 'done' : ''}`} onClick={() => setStep(index + 1)}>
            <span className="num">{index + 1}</span>{title}
          </button>
        ))}
      </div>
      {step !== 7 ? <ActionStatus status={props.status} busy={props.busy} /> : null}
      <div className="step-panel active">
        {step === 1 ? <StepIntro {...props} /> : null}
        {step === 2 ? <StepAnalyze {...props} /> : null}
        {step === 3 ? <StepTerm {...props} /> : null}
        {step === 4 ? <StepSource {...props} /> : null}
        {step === 5 ? <StepFreqV2 {...props} /> : null}
        {step === 6 ? <StepLang {...props} /> : null}
        {step === 7 ? <StepTranslate {...props} /> : null}
        {step === 8 ? <StepQA {...props} /> : null}
        {step === 9 ? <StepDone {...props} /> : null}
      </div>
      <div className="actions">
        <button className="btn btn-ghost" disabled={step === 1} onClick={() => setStep(step - 1)}>← 上一步</button>
        <button className="btn btn-primary" disabled={props.busy} onClick={() => setStep(Math.min(9, step + 1))}>{step === 9 ? '🏁 完成' : '下一步 →'}</button>
      </div>
    </>
  )
}

function StepIntro({
  project,
  intro,
  setIntro,
  assetArtifacts,
  onUploadAsset
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  assetArtifacts: Artifact[]
  onUploadAsset: (file: File) => void
}) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 1</span>确认项目资料与参考素材</div>
      <div className="panel-desc">已从项目描述带入基础信息；这里只需要补充本次任务特有的风格、玩法、角色或素材。</div>
      <textarea value={intro} onChange={(event) => setIntro(event.target.value)} placeholder={'游戏名：《星际边境》\n类型：科幻 SLG\n目标用户：欧美移动端玩家\n玩法：基地建造 + 英雄养成 + 联盟战争'} />
      <div className="field-foot">
        <span>{intro.trim().length} 字</span>
        <span className={intro.trim().length > 20 || project.description ? 'ok' : 'warn'}>{intro.trim().length > 20 || project.description ? '✓ 信息可用于生成 prompt' : '⚠ 建议补充更多信息'}</span>
      </div>
      <div className="upload-row">
        <FileBox label="上传 Markdown / 文档 / 图片 / PDF / 音视频素材" onFile={onUploadAsset} />
        {assetArtifacts.length ? (
          <div className="asset-list">
            <div className="ai-header">已归档参考素材</div>
            {assetArtifacts.map((artifact) => <ArtifactNote key={artifact.id} artifact={artifact} compact />)}
          </div>
        ) : null}
      </div>
    </>
  )
}

function StepAnalyze({
  onAnalyze,
  project,
  busy,
  assetArtifacts,
  selectedLanguage
}: {
  onAnalyze: () => void
  project: Project
  busy: boolean
  assetArtifacts: Artifact[]
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 2</span>AI 分析与专属提示词生成</div>
      <div className="panel-desc">基于文字资料、已归档素材和项目资产生成提示词、项目规则与元信息。生成后会自动保存到当前项目。当前素材：{assetArtifacts.length} 个。</div>
      <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>🤖 启动 AI 分析</button>
      <div className="ai-card"><div className="ai-header">当前 {lang.short} 提示词</div><pre>{projectPromptForLanguage(project, selectedLanguage) || '尚未生成'}</pre></div>
      <ProjectMetaTable project={project} />
    </>
  )
}

function StepTerm({
  project,
  onUploadTerm,
  termArtifact,
  setTermArtifact,
  glossaryPreview,
  onGlossaryPreview,
  onGlossaryImport,
  busy,
  selectedLanguage
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
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 3</span>导入游戏术语表</div>
      <div className="panel-desc">可使用已有术语表、上传新文件、预览后导入，也可跳过由 Step 5 生成。</div>
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} />
        <FileBox label="上传术语表 xlsx/csv/json" onFile={onUploadTerm} />
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

function StepSource({
  project,
  onUploadSource,
  sourceArtifact,
  setSourceArtifact,
  selectedLanguage
}: {
  project: Project
  onUploadSource: (file: File) => void
  sourceArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>导入待翻译内容</div>
      <div className="panel-desc">可选择已有语言表，也可上传新的 Excel 语言表；默认字段：ID | cn | {lang.targetHeader}。</div>
      <div className="action-card">
        <AssetSelect label="使用已有语言表" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} />
        <FileBox label="上传 language.xlsx" onFile={onUploadSource} />
      </div>
      {sourceArtifact ? <ArtifactNote artifact={sourceArtifact} /> : null}
    </>
  )
}

function StepFreqV2({
  onGlossaryExtract,
  onFreq,
  sourceArtifact,
  assetArtifacts,
  latestRun,
  glossaryBatches,
  glossaryCandidates,
  busy,
  onUpdateCandidate,
  onResolveCandidates,
  onTranslateMissingCandidates,
  selectedLanguage
}: {
  project: Project
  onGlossaryExtract: () => void
  onFreq: () => void
  sourceArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
  onTranslateMissingCandidates: (batchId: string) => void
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  const [expanded, setExpanded] = useState(false)
  const backfill = latestRun?.kind === 'glossary' ? latestRun.metadata?.glossary_backfill as Record<string, unknown> | undefined : undefined
  const activeBatch = glossaryBatches[0] || null
  const pendingCandidates = glossaryCandidates.filter((candidate) => candidate.status === 'pending')
  const needsTranslation = pendingCandidates.filter((candidate) => !candidate.target?.trim())
  const readyCandidates = pendingCandidates.filter((candidate) => candidate.target?.trim())
  const reviewPreview = expanded ? pendingCandidates : pendingCandidates.slice(0, 12)
  const candidates = Number(backfill?.candidates ?? 0)
  const uniqueCandidates = Number(backfill?.unique_candidates ?? candidates)
  const existing = Number(backfill?.skipped_existing ?? 0)
  const accepted = activeBatch?.counts?.accepted ?? glossaryCandidates.filter((candidate) => candidate.status === 'accepted').length
  const rejected = activeBatch?.counts?.rejected ?? glossaryCandidates.filter((candidate) => candidate.status === 'rejected').length
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 5</span>高频词扫描 & 术语候选审核</div>
      <div className="panel-desc">先扫描语言表中的高频中文词；缺少 {lang.short} 的候选需要显式补译或人工填写，审核加入后才进入项目术语库。</div>
      <div className="row-actions action-card">
        <span className="asset-meta">语言表：{sourceArtifact?.label || '未选择'}</span>
        <span className="asset-meta">参考素材：{assetArtifacts.length} 个</span>
        <button className="btn btn-primary" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>🔎 开始扫描</button>
        <button className="btn btn-ghost" disabled={!activeBatch || !needsTranslation.length || busy} onClick={() => activeBatch && onTranslateMissingCandidates(activeBatch.id)}>补齐缺失译文</button>
        <button className="btn btn-ghost" onClick={onFreq}>💡 查看补充策略</button>
      </div>
      {backfill ? (
        <>
          <div className="scan-explain">
            <strong>本次扫描结果</strong>
            <span>扫描 {candidates} 个候选，按中文去重后 {uniqueCandidates} 个；已在库 {existing} 个；待补译 {needsTranslation.length} 个；待审核 {readyCandidates.length} 个。</span>
          </div>
          <div className="workflow-note-grid compact-grid">
            <div><strong>待补译</strong><span>{needsTranslation.length}</span></div>
            <div><strong>待审核</strong><span>{readyCandidates.length}</span></div>
            <div><strong>已加入</strong><span>{accepted}</span></div>
            <div><strong>已跳过</strong><span>{rejected}</span></div>
          </div>
          <div className="confirm-panel">
            <div className="confirm-head">
              <div>
                <strong>候选批次审核</strong>
                <span>{activeBatch ? `批次：${activeBatch.label}` : '暂无扫描批次'}。空 {lang.targetHeader} 不能加入；可先补译或手工编辑，再加入项目术语库。</span>
              </div>
              <div className="confirm-actions">
                <button className="btn btn-ghost btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'reject')}>全部跳过</button>
                <button className="btn btn-primary btn-sm" disabled={!activeBatch || !readyCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, readyCandidates, 'accept')}>全部加入已完成项</button>
              </div>
            </div>
            {reviewPreview.length ? (
              <div className="table-scroll">
                <table className="pending-term-table">
                  <thead><tr><th>状态</th><th>ID</th><th>CN</th><th>{lang.targetHeader}</th><th>{lang.altHeader}</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
                  <tbody>
                    {reviewPreview.map((term) => (
                      <PendingTermReviewRowV2
                        key={term.id}
                        candidate={term}
                        batchId={activeBatch?.id || ''}
                        busy={busy}
                        onUpdateCandidate={onUpdateCandidate}
                        onResolveCandidates={onResolveCandidates}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-inline">暂无待审核词条，可以继续下一步。</div>
            )}
            {pendingCandidates.length > 12 ? (
              <div className="review-table-foot">
                <span>{expanded ? `已展开全部 ${pendingCandidates.length} 条。` : `当前展示前 ${reviewPreview.length} 条，展开后可查看并编辑全部 ${pendingCandidates.length} 条。`}</span>
                <button className="btn btn-ghost btn-sm" disabled={!pendingCandidates.length} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起' : `展开全部 ${pendingCandidates.length} 条`}</button>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  )
}

function PendingTermReviewRowV2({
  candidate,
  batchId,
  busy,
  onUpdateCandidate,
  onResolveCandidates
}: {
  candidate: GlossaryCandidate
  batchId: string
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: candidate.term_key || '',
    source: candidate.source || '',
    target: candidate.target || '',
    target_alt: candidate.target_alt || '',
    category: candidate.category || '',
    note: normalizeGlossaryNote(candidate.note)
  })

  useEffect(() => {
    setDraft({
      term_key: candidate.term_key || '',
      source: candidate.source || '',
      target: candidate.target || '',
      target_alt: candidate.target_alt || '',
      category: candidate.category || '',
      note: normalizeGlossaryNote(candidate.note)
    })
    setEditing(false)
  }, [candidate.id, candidate.term_key, candidate.source, candidate.target, candidate.target_alt, candidate.category, candidate.note])

  const canAcceptDraft = Boolean(draft.target.trim())
  const canAcceptCandidate = Boolean(candidate.target?.trim())

  async function save(confirmAfter = false) {
    await onUpdateCandidate(candidate, draft)
    setEditing(false)
    if (confirmAfter && canAcceptDraft) onResolveCandidates(batchId, [candidate], 'accept')
  }

  function cell(key: keyof typeof draft) {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  const statusLabel = canAcceptCandidate ? '待审核' : '待补译'
  return (
    <tr>
      <td><span className={`term-kind ${canAcceptCandidate ? 'filled' : 'new'}`}>{statusLabel}</span></td>
      <td>{cell('term_key')}</td>
      <td>{cell('source')}</td>
      <td>{cell('target')}</td>
      <td>{cell('target_alt')}</td>
      <td>{cell('category')}</td>
      <td>{cell('note')}</td>
      <td>
        <div className="term-review-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => save(false)}>保存</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId || !canAcceptDraft} onClick={() => save(true)}>保存并加入</button>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(false)}>取消</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(true)}>编辑</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId || !canAcceptCandidate} onClick={() => onResolveCandidates(batchId, [candidate], 'accept')}>加入</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId} onClick={() => onResolveCandidates(batchId, [candidate], 'reject')}>跳过</button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

function StepFreq({
  project,
  onGlossaryExtract,
  onFreq,
  sourceArtifact,
  assetArtifacts,
  latestRun,
  glossaryBatches,
  glossaryCandidates,
  busy,
  onUpdateCandidate,
  onResolveCandidates
}: {
  project: Project
  onGlossaryExtract: () => void
  onFreq: () => void
  sourceArtifact: Artifact | null
  assetArtifacts: Artifact[]
  latestRun: Run | null
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
}) {
  const [expanded, setExpanded] = useState(false)
  const backfill = latestRun?.kind === 'glossary' ? latestRun.metadata?.glossary_backfill as Record<string, unknown> | undefined : undefined
  const activeBatch = glossaryBatches[0] || null
  const pendingCandidates = glossaryCandidates.filter((candidate) => candidate.status === 'pending')
  const newCandidates = pendingCandidates.filter((candidate) => candidate.action === 'new')
  const reviewPreview = expanded ? pendingCandidates : pendingCandidates.slice(0, 12)
  const reviewCount = pendingCandidates.length
  const inserted = Number(backfill?.inserted ?? newCandidates.length)
  const existing = Number(backfill?.skipped_existing ?? 0)
  const candidates = Number(backfill?.candidates ?? 0)
  const uniqueCandidates = Number(backfill?.unique_candidates ?? candidates)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 5</span>高频词扫描 & 术语候选审核</div>
      <div className="panel-desc">先从语言表筛选高频中文词，再和项目术语库按中文去重；已存在词条直接跳过，不跨语言自动补译。新增候选需人工确认译文后才会加入项目术语库。</div>
      <div className="row-actions action-card">
        <span className="asset-meta">语言表：{sourceArtifact?.label || '未选择'}</span>
        <span className="asset-meta">参考素材：{assetArtifacts.length} 个</span>
        <button className="btn btn-primary" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>🔍 开始扫描</button>
        <button className="btn btn-ghost" onClick={onFreq}>💡 查看补充策略</button>
      </div>
      {backfill ? (
        <>
          <div className="scan-explain">
            <strong>本次扫描结果</strong>
            <span>扫描到 {candidates} 个候选，按中文去重后 {uniqueCandidates} 个；其中 {existing} 个已在项目术语库并跳过，下方仅保留 {reviewCount} 条新增候选，需编辑/确认后才能加入项目术语库。</span>
          </div>
          <div className="workflow-note-grid compact-grid">
            <div><strong>待复核</strong><span>{reviewCount}</span></div>
            <div><strong>新增候选</strong><span>{inserted}</span></div>
            <div><strong>自动补全</strong><span>0</span></div>
            <div><strong>已在库中</strong><span>{existing}</span></div>
          </div>
          <div className="confirm-panel">
            <div className="confirm-head">
              <div>
                <strong>待复核词条</strong>
                <span>{activeBatch ? `批次：${activeBatch.label}` : '暂无扫描批次'}。这些词条尚未进入项目术语库；可先编辑目标译文 / 备选译文 / 分类 / 备注，再单条加入或跳过。</span>
              </div>
              <div className="confirm-actions">
                <button className="btn btn-ghost btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'reject')}>全部跳过</button>
                <button className="btn btn-primary btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'accept')}>全部加入术语库</button>
              </div>
            </div>
            {reviewPreview.length ? (
              <div className="table-scroll">
                <table className="pending-term-table">
                  <thead><tr><th>类型</th><th>ID</th><th>CN</th><th>目标译文</th><th>备选译文</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
                  <tbody>
                    {reviewPreview.map((term) => (
                      <PendingTermReviewRow
                        key={term.id}
                        candidate={term}
                        batchId={activeBatch?.id || ''}
                        busy={busy}
                        onUpdateCandidate={onUpdateCandidate}
                        onResolveCandidates={onResolveCandidates}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-inline">暂无待复核词条，可以继续下一步。</div>
            )}
            {pendingCandidates.length > 12 ? (
              <div className="review-table-foot">
                <span>{expanded ? `已展开全部 ${pendingCandidates.length} 条。` : `当前仅展示前 ${reviewPreview.length} 条；可查看并编辑全部 ${pendingCandidates.length} 条。`}</span>
                <button className="btn btn-ghost btn-sm" disabled={!pendingCandidates.length} onClick={() => setExpanded((value) => !value)}>{expanded ? '▲ 收起' : `▼ 展开全部 ${pendingCandidates.length} 条`}</button>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </>
  )
}

function PendingTermReviewRow({
  candidate,
  batchId,
  busy,
  onUpdateCandidate,
  onResolveCandidates
}: {
  candidate: GlossaryCandidate
  batchId: string
  busy: boolean
  onUpdateCandidate: (candidate: GlossaryCandidate, updates: Partial<GlossaryCandidate>) => Promise<void>
  onResolveCandidates: (batchId: string, candidates: GlossaryCandidate[], action: 'accept' | 'reject') => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: candidate.term_key || '',
    source: candidate.source || '',
    target: candidate.target || '',
    target_alt: candidate.target_alt || '',
    category: candidate.category || '',
    note: normalizeGlossaryNote(candidate.note)
  })

  useEffect(() => {
    setDraft({
      term_key: candidate.term_key || '',
      source: candidate.source || '',
      target: candidate.target || '',
      target_alt: candidate.target_alt || '',
      category: candidate.category || '',
      note: normalizeGlossaryNote(candidate.note)
    })
    setEditing(false)
  }, [candidate.id, candidate.term_key, candidate.source, candidate.target, candidate.target_alt, candidate.category, candidate.note])

  async function save(confirmAfter = false) {
    await onUpdateCandidate(candidate, draft)
    setEditing(false)
    if (confirmAfter) onResolveCandidates(batchId, [candidate], 'accept')
  }

  function cell(key: keyof typeof draft) {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  const kind = candidate.action === 'new' ? '新增' : '候选'
  return (
    <tr>
      <td><span className={`term-kind ${candidate.action === 'new' ? 'new' : 'filled'}`}>{kind}</span></td>
      <td>{cell('term_key')}</td>
      <td>{cell('source')}</td>
      <td>{cell('target')}</td>
      <td>{cell('target_alt')}</td>
      <td>{cell('category')}</td>
      <td>{cell('note')}</td>
      <td>
        <div className="term-review-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => save(false)}>保存</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId} onClick={() => save(true)}>保存并加入</button>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(false)}>取消</button>
            </>
          ) : (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setEditing(true)}>编辑</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId} onClick={() => onResolveCandidates(batchId, [candidate], 'accept')}>加入</button>
              <button type="button" className="btn btn-sm" disabled={busy || !batchId} onClick={() => onResolveCandidates(batchId, [candidate], 'reject')}>跳过</button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

function LanguageSelector({ selectedLanguage, setSelectedLanguage }: { selectedLanguage: LanguageCode; setSelectedLanguage: (language: LanguageCode) => void }) {
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

function StepLang({ selectedLanguage, setSelectedLanguage }: { selectedLanguage: LanguageCode; setSelectedLanguage: (language: LanguageCode) => void }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 6</span>选择目标语言</div>
      <div className="panel-desc">选择本次任务的目标语言；每次 run 仍按单语言执行，多语言任务会拆成多个单语言流程。</div>
      <div className="lang-grid">
        {supportedLanguages.map((lang) => (
          <button
            key={lang.code}
            className={`lang-chip ${selectedLanguage === lang.code ? 'selected' : ''}`}
            onClick={() => setSelectedLanguage(lang.code)}
          >
            {lang.label}
          </button>
        ))}
        {unsupportedLanguages.map((lang) => (
          <button key={lang} className="lang-chip disabled" disabled title="暂未支持">{lang} · 未支持</button>
        ))}
      </div>
    </>
  )
}

function StepTranslate({
  project,
  settings,
  status,
  onTranslate,
  onCancelTranslate,
  busy,
  latestRun,
  qualityIssues,
  translationReadiness,
  sourceArtifact,
  termArtifact,
  setSourceArtifact,
  setTermArtifact,
  setQaArtifact,
  setStep,
  selectedLanguage
}: {
  project: Project
  settings: AppSettings | null
  status: string
  onTranslate: () => void
  onCancelTranslate: () => void
  busy: boolean
  latestRun: Run | null
  qualityIssues: QualityIssue[]
  translationReadiness: TranslationReadiness | null
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
  selectedLanguage: LanguageCode
}) {
  const lang = languageSpec(selectedLanguage)
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const batchSize = effectiveBatchSize(settings)
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === batchSize ? translationReadiness : null
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project, readiness)
  const alreadyTranslated = canSkipModelTranslation(readiness)
  const estimatedBatches = estimateBatches(readiness?.source_rows, batchSize)
  const progress = getTranslationProgress(latestRun)
  const activeTranslation = Boolean(latestRun?.kind === 'translation' && ['queued', 'running'].includes(latestRun.status) && latestRun.language === selectedLanguage && latestRun.metadata?.input_artifact_id === sourceArtifact?.id)
  const resumable = Boolean(latestRun?.kind === 'translation' && ['failed', 'needs_input', 'canceled'].includes(latestRun.status) && latestRun.language === selectedLanguage && latestRun.metadata?.input_artifact_id === sourceArtifact?.id)
  const invalidIdText = readiness?.invalid_id_rows ? ` / 空 ID ${readiness.invalid_id_rows}` : ''
  const readinessText = readiness
    ? `${readiness.source_rows} 行原文 / ${readiness.translated_rows} 行已有译文 / 空译文 ${readiness.empty_target_rows} / 中文残留 ${readiness.cjk_target_rows}${invalidIdText} / 预计 ${readiness.estimated_batches} 批`
    : '选择语言表后自动检查'
  const readinessState = !sourceArtifact
    ? { label: '未选择语言表', tone: 'idle' }
    : !readiness
      ? { label: '正在检查', tone: 'checking' }
      : translationReadinessBlockReason(readiness)
        ? { label: '需要修正表结构', tone: 'todo' }
      : alreadyTranslated
        ? { label: '可直接校对', tone: 'ready' }
        : { label: '需要翻译', tone: 'todo' }
  const showTranslateStatus = busy
    || Boolean(progress)
    || /翻译|provider|API|mock|workpack|批|QA/i.test(status)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 7</span>{lang.short} 模型翻译</div>
      <div className="panel-desc">先检查语言表是否已有目标译文；已有译文则跳过模型翻译并进入校对，空译文或中文残留才生成 workpack 分批调用 GPT / Claude。</div>
      <div className="action-card">
        <AssetSelect label="语言表输入" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} />
        <div className={`translation-readiness-box ${readinessState.tone}`}>
          <div className="readiness-head">
            <strong>译文检查</strong>
            <span>{readinessState.label}</span>
          </div>
          <p>{readinessText}</p>
        </div>
        <div className="translation-batch-panel compact">
          <div className="batch-control-head">
            <div>
              <strong>后台编排</strong>
              <span>系统按预设自动拆批、限流、重试和断点续跑。</span>
            </div>
            <em>{batchSize} 行/批 · 预计 {estimatedBatches || '-'} 批</em>
          </div>
        </div>
        <div className="translation-actions">
          {alreadyTranslated ? (
            <>
              <div className="ok-line">检测到这份表已有可校对译文，不需要重新走整表翻译；残留问题交给 QA 处理。</div>
              <button className="btn btn-primary" disabled={busy} onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>跳到校对</button>
            </>
          ) : (
            <>
              <button className="btn btn-primary" disabled={busy || activeTranslation || Boolean(blockReason)} onClick={onTranslate}>{resumable ? '↻ 继续后台翻译' : `⚡ 开始 ${lang.short} 正式翻译`}</button>
              {activeTranslation ? <button className="btn btn-ghost" disabled={busy} onClick={onCancelTranslate}>暂停/取消后台任务</button> : null}
            </>
          )}
          {blockReason && !alreadyTranslated ? <div className="warn-line inline-warning">{blockReason}</div> : null}
        </div>
        {showTranslateStatus ? <ActionStatus status={status} busy={busy} /> : null}
        {progress ? <TranslationProgressBar progress={progress} /> : null}
        {latestRun?.metadata?.reason === 'api_budget_confirmation_required' ? (
          <div className="warn-line">预计 API token 超过提醒阈值；点击“继续后台翻译”会二次确认预算，并从已完成批次继续。</div>
        ) : null}
        {latestRun?.metadata?.reason === 'background_job_interrupted' ? (
          <div className="warn-line">上次后台任务被中断；点击“继续后台翻译”可从已落盘批次恢复。</div>
        ) : null}
        {progress?.failed_batch && latestRun ? <BatchDebugLinks runId={latestRun.id} batchIndex={progress.failed_batch} /> : null}
      </div>
      <div className="translation-guard-strip">
        <span>项目术语库 <strong>{glossaryCount} 条</strong></span>
        <span>{lang.short} 提示词 <strong>{projectPromptForLanguage(project, selectedLanguage) ? '已生成' : '未生成'}</strong></span>
        <span>校对门槛 <strong>QA 通过后交付</strong></span>
      </div>
      {latestRun && latestRun.kind === 'translation' ? <TaskRunSummary run={latestRun} issues={qualityIssues} /> : null}
    </>
  )
}

function BatchDebugLinks({ runId, batchIndex }: { runId: string; batchIndex: number }) {
  return (
    <div className="row-actions wrap">
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/request`}>下载失败批次输入</a>
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/error`}>下载错误报告</a>
      <a className="btn btn-ghost btn-sm" href={`/api/runs/${runId}/translate/batches/${batchIndex}/raw-response`}>下载原始响应</a>
    </div>
  )
}

function TranslationProgressBar({ progress }: { progress: TranslationProgress }) {
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

function StepQA({
  project,
  latestRun,
  sourceArtifact,
  translationReadiness,
  qualityIssues,
  qaArtifact,
  setQaArtifact,
  onDirectQA,
  onManualFixes,
  onModelFixes,
  onUploadTranslation,
  busy,
  status,
  selectedLanguage,
  setSelectedLanguage
}: {
  project: Project
  latestRun: Run | null
  sourceArtifact: Artifact | null
  translationReadiness: TranslationReadiness | null
  qualityIssues: QualityIssue[]
  qaArtifact: Artifact | null
  setQaArtifact: (artifact: Artifact | null) => void
  onDirectQA: () => void
  onManualFixes: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
  onModelFixes: () => void
  onUploadTranslation: (file: File) => void
  busy: boolean
  status: string
  selectedLanguage: LanguageCode
  setSelectedLanguage: (language: LanguageCode) => void
}) {
  const latestQaRun = latestRun?.kind === 'qa' ? latestRun : latestRunOfKind(project, 'qa')
  const projectQuality = latestQaRun?.metadata?.project_harness_quality as { hard_errors?: number; soft_warnings?: number } | undefined
  const projectHardErrors = projectQuality?.hard_errors ?? 0
  const qaIssues = latestRun?.id === latestQaRun?.id ? qualityIssues.filter((issue) => issue.severity === 'hard' || issue.severity === 'soft') : []
  const previousTranslationRun = latestRunOfKind(project, 'translation')
  const previousTranslationArtifact = previousTranslationRun
    ? newestArtifact(runArtifacts(project, previousTranslationRun.id), ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
    : null
  const qaRole = qaArtifact ? artifactRole(qaArtifact) : ''
  const selectedReadiness = qaArtifact && translationReadiness?.artifact_id === qaArtifact.id ? translationReadiness : null
  const originText = qaArtifact?.run_id && previousTranslationRun?.id === qaArtifact.run_id
    ? `上一翻译结果：${previousTranslationRun.id.slice(0, 8)}`
    : qaRole === 'language_source'
      ? selectedReadiness
        ? `此前导入的语言表：${selectedReadiness.translated_rows}/${selectedReadiness.source_rows} 行已有译文`
        : '此前导入的语言表；运行前会按译文表检查'
      : qaArtifact
        ? '直接导入的译文 workbook'
        : sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && canSkipModelTranslation(translationReadiness)
          ? '已检测到当前语言表可进入校对，可直接选择运行'
          : '请选择要校对的译文表'
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const qaStatus = latestQaRun ? latestQaRun.status : '未运行'
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 8</span>校对任务</div>
      <div className="panel-desc">这里是校对入口：可以接上一步翻译结果，也可以选择之前导入且已有译文的语言表，或上传一份新的译文 workbook。</div>
      <div className="action-card">
        <div className="language-inline-select">
          <span>校对目标语言：</span>
          <LanguageSelector selectedLanguage={selectedLanguage} setSelectedLanguage={setSelectedLanguage} />
        </div>
        <div className="qa-entry-row">
          <button className="btn btn-ghost" disabled={!previousTranslationArtifact || busy} onClick={() => setQaArtifact(previousTranslationArtifact)}>使用上一翻译结果</button>
          <button className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={() => sourceArtifact && setQaArtifact(sourceArtifact)}>使用当前语言表</button>
        </div>
        <AssetSelect label="选择已译表 / 翻译结果" project={project} role={['translation_workbook', 'language_source']} value={qaArtifact} onChange={setQaArtifact} allowEmpty />
        <FileBox label="上传新的译文 workbook" onFile={onUploadTranslation} />
        <button className="btn btn-primary" data-testid="run-qa" disabled={!qaArtifact || busy} onClick={onDirectQA}>运行 QA</button>
        {!qaArtifact ? <div className="warn-line">请选择“上一翻译结果”、此前导入的已译语言表，或上传新的译文 workbook 后再运行 QA。</div> : null}
        <ActionStatus status={status} busy={busy} />
      </div>
      <div className="check-list">
        <CheckItem ok={Boolean(qaArtifact)} title="处理文件" detail={qaArtifact ? qaArtifact.label : '未选择'} />
        <CheckItem ok={Boolean(qaArtifact)} title="来源说明" detail={originText} />
        <CheckItem ok={glossaryCount > 0} title="项目术语库" detail={`${glossaryCount} 条，运行时生成快照`} />
        <CheckItem ok={!latestQaRun || latestQaRun.status === 'passed'} title="最近 QA" detail={qaStatus} />
        <CheckItem ok={qaIssues.length === 0} title="待处理问题" detail={qaIssues.length ? `${qaIssues.length} 条` : '无'} />
      </div>
      <TaskHistoryTable project={project} kind="qa" title="🕒 校对历史记录" />
      {latestQaRun ? <TaskRunSummary run={latestQaRun} issues={qaIssues} projectHardErrors={projectHardErrors} /> : null}
      {qaIssues.length ? <FailedRowEditor issues={qaIssues} busy={busy} onModelFix={onModelFixes} onApply={onManualFixes} /> : null}
    </>
  )
}

function FailedRowEditor({
  issues,
  busy,
  onModelFix,
  onApply
}: {
  issues: QualityIssue[]
  busy: boolean
  onModelFix: () => void
  onApply: (fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) => void
}) {
  const editable = issues.filter((issue) => issue.sheet && issue.row > 1)
  const visibleIssues = editable.slice(0, 50)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const issue of editable) next[issue.id] = drafts[issue.id] ?? issue.current_translation
    setDrafts(next)
  }, [issues.map((issue) => issue.id).join('|')])

  const fixes = editable
    .map((issue) => ({
      issue_id: issue.id,
      sheet: issue.sheet,
      row: issue.row,
      translation: (drafts[issue.id] ?? '').trim(),
      note: `${issue.source}:${issue.check_type}`
    }))
    .filter((fix) => fix.translation)

  if (!editable.length) {
    return <IssueSummary issues={issues} />
  }

  return (
    <div className="issue-summary">
      <div className="card-title"><div className="left">QA 问题摘要</div></div>
      <IssueGuide issues={issues} editableCount={editable.length} />
      <IssueChips issues={issues} />
      <div className="model-fix-bar">
        <div>
          <strong>推荐处理顺序</strong>
          <span>先用模型批量修复并重跑 QA；仍失败的行再人工逐条改。</span>
        </div>
        <button className="btn btn-primary btn-sm" disabled={busy || editable.length === 0} onClick={onModelFix}>🤖 模型修复并重跑 QA</button>
      </div>
      <details className="repair-panel" data-testid="failed-row-editor">
        <summary>展开可编辑问题（显示前 {visibleIssues.length} / {editable.length} 条）</summary>
        <div className="failed-editor">
          <div className="card-title">
            <div className="left">逐行修复</div>
            <button className="btn btn-primary btn-sm" data-testid="manual-fix-rerun" disabled={busy || fixes.length === 0} onClick={() => onApply(fixes)}>保存修复并重新 QA</button>
          </div>
          <div className="failed-rows">
            {visibleIssues.map((issue, index) => (
              <div key={`${issue.id}-${issue.sheet}-${issue.row}-${issue.check_type}-${issue.source}-${index}`} className="failed-row">
                <div className="failed-meta">
                  <span>{severityLabel(issue.severity)}</span>
                  <span>{issueTypeLabel(issue.check_type)}</span>
                  <span>{issue.sheet} 第 {issue.row} 行</span>
                  <span>{issueSourceLabel(issue.source)}</span>
                </div>
                <div className="failed-message">{issueHumanMessage(issue)}</div>
                <div className="failed-field">
                  <span>当前译文</span>
                  <div className="failed-current">{issue.current_translation || '-'}</div>
                </div>
                <label className="failed-edit">
                  <span>修改为</span>
                  <textarea
                    data-testid={`manual-fix-input-${issue.row}`}
                    value={drafts[issue.id] ?? issue.current_translation}
                    onChange={(event) => setDrafts((prev) => ({ ...prev, [issue.id]: event.target.value }))}
                  />
                </label>
              </div>
            ))}
          </div>
        </div>
      </details>
    </div>
  )
}

function StepDone({ project, latestRun }: { project: Project; latestRun: Run | null }) {
  const artifacts = pickerArtifacts(latestRun?.artifacts?.length ? latestRun.artifacts : runArtifacts(project, latestRun?.id))
    .filter((artifact) => artifact.kind === 'qa_final_workbook' || artifact.kind === 'qa_changes')
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 9</span>最终交付</div>
      {latestRun ? <TaskRunSummary run={latestRun} /> : <div className="muted-left">暂无可交付任务。先完成翻译或校对。</div>}
      <div className="artifact-grid">
        {artifacts.map((artifact) => <a key={artifact.id} className="artifact" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}<span>{artifactKindLabel(artifact)}</span></a>)}
      </div>
      <div className="muted-left">正式交付请回到“交付”页生成最终 workbook 和 QA 修改表。</div>
    </>
  )
}

type HistoryKind = 'translation' | 'qa' | 'all'

function TaskHistoryTable({ project, kind, title }: { project: Project; kind: HistoryKind; title: string }) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const runs = kind === 'all' ? (project.runs || []) : (project.runs || []).filter((run) => run.kind === kind)
  const selectedRun = runs.find((run) => run.id === selectedRunId) || null
  return (
    <div className="card history-card">
      <div className="card-title">
        <div className="left">{title}</div>
      </div>
      <table className="history-table">
        <thead>
          <tr><th>日期</th><th>任务名称</th><th>目标语言</th><th>处理量</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const artifacts = runArtifacts(project, run.id)
            const download = downloadableArtifact(artifacts, kind)
            const task = runTaskSummary(project, run)
            return (
              <tr key={run.id}>
                <td>{formatDate(run.created_at)}</td>
                <td>{task.taskType} · {task.taskLabel}</td>
                <td>{run.language ? languageSpec(normalizeLanguageCode(run.language) || 'en').short : '-'}</td>
                <td>{runProcessedLabel(run)}</td>
                <td><span className={`tag ${run.status === 'passed' ? 'tag-done' : run.status === 'failed' ? 'tag-warn' : 'tag-doing'}`}>{run.status}</span></td>
                <td>
                  <div className="link-actions">
                    <button className="link-button" onClick={() => setSelectedRunId(selectedRunId === run.id ? null : run.id)}>查看</button>
                    {download ? <a href={`/api/artifacts/${download.id}/download`}>下载</a> : <span className="muted-inline" title="该任务暂无可下载交付产物">下载</span>}
                  </div>
                </td>
              </tr>
            )
          })}
          {!runs.length ? <tr><td colSpan={6} className="muted">暂无历史记录。</td></tr> : null}
        </tbody>
      </table>
      {selectedRun ? <RunDetail project={project} run={selectedRun} kind={kind} /> : null}
    </div>
  )
}

function downloadableArtifact(artifacts: Artifact[], kind: HistoryKind): Artifact | null {
  const accepted = kind === 'translation'
    ? ['qa_final_workbook']
    : ['qa_changes', 'qa_final_workbook']
  return artifacts.find((artifact) => accepted.includes(artifact.role || '') || accepted.includes(artifact.kind)) || null
}

function RunDetail({ project, run, kind }: { project: Project; run: Run; kind: HistoryKind }) {
  const artifacts = runArtifacts(project, run.id)
  const visibleArtifacts = pickerArtifacts(artifacts.filter((artifact) => downloadableArtifact([artifact], kind)))
  const inputs = (run.metadata?.input_artifacts || {}) as Record<string, string>
  const artifactById = new Map((project.artifacts || []).map((artifact) => [artifact.id, artifact]))
  const task = runTaskSummary(project, run)
  const quality = (run.metadata?.quality_summary || {}) as Record<string, unknown>
  const archiveCount = runArchiveCount(run)
  const inputItems = [
    ['源/译文', inputs.source_workbook || inputs.translation_workbook],
    ['术语快照', inputs.glossary_snapshot],
    ['提示词快照', inputs.prompt_snapshot],
    ['规则快照', inputs.harness_snapshot],
    ['临时参考快照', inputs.quick_reference_snapshot],
  ].filter(([, id]) => Boolean(id))
  return (
    <div className="history-detail">
      <div className="history-detail-head">
        <strong>{run.kind === 'qa' ? '校对任务详情' : '翻译任务详情'}</strong>
        <span>{run.id}</span>
      </div>
      <div className="history-detail-grid">
        <div><strong>任务类型</strong><span>{task.taskType}</span></div>
        <div><strong>任务ID</strong><span>{task.taskLabel}</span></div>
        <div><strong>状态</strong><span>{run.status}</span></div>
        <div><strong>语言</strong><span>{run.language ? languageSpec(normalizeLanguageCode(run.language) || 'en').short : '-'}</span></div>
        <div><strong>创建时间</strong><span>{new Date(run.created_at).toLocaleString()}</span></div>
        <div><strong>更新时间</strong><span>{new Date(run.updated_at).toLocaleString()}</span></div>
        <div><strong>来源文件</strong><span>{inputArtifactName(project, run) || '-'}</span></div>
        <div><strong>QA 结果</strong><span>必须修复 {Number(quality.hard_errors || 0)}</span></div>
        <div><strong>翻译处理</strong><span>{runTranslationProgressText(run)}</span></div>
        <div><strong>校对处理</strong><span>{runQaRowsText(run)}</span></div>
        <div><strong>本次归档</strong><span>{archiveCount > 0 ? `${archiveCount} 条` : '未归档'}</span></div>
        <div><strong>累计归档</strong><span>{project.stats.archived_rows || 0} 条</span></div>
        <div><strong>交付状态</strong><span>{runDeliveryState(run, visibleArtifacts)}</span></div>
      </div>
      <div className="artifact-links">
        {visibleArtifacts.map((artifact) => (
          <a key={artifact.id} className="btn btn-ghost btn-sm" href={`/api/artifacts/${artifact.id}/download`}>{artifactPickerLabel(artifact)}</a>
        ))}
        {!visibleArtifacts.length ? <span className="muted-left">暂无可下载交付产物。</span> : null}
      </div>
      {inputItems.length ? (
        <div className="run-inputs">
          {inputItems.map(([label, id]) => {
            const artifact = artifactById.get(String(id))
            return <span key={`${label}-${id}`}>{label}: {artifact ? artifactPickerLabel(artifact) : id}</span>
          })}
        </div>
      ) : null}
    </div>
  )
}

function runTaskSummary(project: Project, run: Run, seen: Set<string> = new Set()): { taskCode: string; taskType: string; taskLabel: string } {
  if (seen.has(run.id)) {
    const code = run.kind === 'qa' ? 'QA' : run.kind === 'translation' ? 'T' : run.kind.toUpperCase()
    return { taskCode: code, taskType: code, taskLabel: `${code}-${shortRunId(run.id)}` }
  }
  seen.add(run.id)
  const sourceId = String(run.metadata?.manual_fix_source_run_id || run.metadata?.source_run_id || '')
  if (sourceId) {
    const sourceRun = (project.runs || []).find((item) => item.id === sourceId)
    if (sourceRun && (run.kind === 'qa' || run.metadata?.task_origin === 'translation_continuation')) {
      return runTaskSummary(project, sourceRun, seen)
    }
  }
  const code = String(run.metadata?.task_code || (run.kind === 'qa' ? 'QA' : run.kind === 'translation' ? 'T' : run.kind.toUpperCase())).toUpperCase()
  const label = `${code}-${shortRunId(run.id)}`
  const quick = run.metadata?.task_origin === 'quick_task'
  const type = quick
    ? (run.kind === 'qa' ? '快速校对' : '快速翻译')
    : code === 'A' ? '完整工作流' : code === 'QA' ? '校对任务' : code === 'T' ? '翻译任务' : code
  return { taskCode: code, taskType: type, taskLabel: label }
}

function inputArtifactName(project: Project, run: Run): string {
  const inputs = (run.metadata?.input_artifacts || {}) as Record<string, string>
  const artifactId = inputs.source_workbook || inputs.translation_workbook || String(run.metadata?.input_artifact_id || '')
  if (!artifactId) return ''
  const artifact = (project.artifacts || []).find((item) => item.id === artifactId)
  return artifact ? artifactPickerLabel(artifact) : artifactId
}

function runArchiveCount(run: Run): number {
  const archive = run.metadata?.translation_archive as { imported_count?: number } | undefined
  return Number(archive?.imported_count || 0)
}

function runProcessedLabel(run: Run): string {
  const archiveCount = runArchiveCount(run)
  if (archiveCount > 0) return `${archiveCount} 条归档`
  const progress = run.metadata?.translation_progress as TranslationProgress | undefined
  if (progress?.total_rows) return `${progress.completed_rows || 0}/${progress.total_rows} 行`
  const readiness = run.metadata?.translation_readiness as TranslationReadiness | undefined
  if (readiness?.source_rows) {
    if (readiness.ready_for_qa) return `${readiness.translated_rows}/${readiness.source_rows} 行已译`
    return `${readiness.source_rows} 行待译`
  }
  const qualityRows = qualityRowsScanned(run)
  if (qualityRows > 0) return `${qualityRows} 行校对`
  return '-'
}

function runTranslationProgressText(run: Run): string {
  const progress = run.metadata?.translation_progress as TranslationProgress | undefined
  if (progress?.total_rows) {
    const percent = typeof progress.percent === 'number' ? `，${progress.percent}%` : ''
    return `${progress.completed_rows || 0}/${progress.total_rows} 行${percent}`
  }
  const readiness = run.metadata?.translation_readiness as TranslationReadiness | undefined
  if (readiness?.source_rows) {
    return readiness.ready_for_qa
      ? `输入已含译文 ${readiness.translated_rows}/${readiness.source_rows} 行，跳过模型翻译`
      : `${readiness.source_rows} 行待翻译，预计 ${readiness.estimated_batches || 0} 批`
  }
  return run.kind === 'translation' ? '未开始' : '不涉及'
}

function runQaRowsText(run: Run): string {
  const rows = qualityRowsScanned(run)
  if (rows > 0) return `${rows} 行`
  const archiveCount = runArchiveCount(run)
  if (archiveCount > 0) return `${archiveCount} 行`
  return run.kind === 'qa' || run.metadata?.quality_summary ? '已运行，未返回行数' : '未运行'
}

function qualityRowsScanned(run: Run): number {
  const quality = (run.metadata?.quality_summary || {}) as Record<string, unknown>
  const globalQuality = quality.global_harness_quality as { rows_scanned?: number } | undefined
  const projectQuality = quality.project_harness_quality as { rows_scanned?: number } | undefined
  return Number(globalQuality?.rows_scanned || projectQuality?.rows_scanned || 0)
}

function runDeliveryState(run: Run, visibleArtifacts: Artifact[]): string {
  if (visibleArtifacts.some((artifact) => artifact.kind === 'qa_final_workbook' || artifact.role === 'translation_workbook')) return '可生成最终交付'
  if (run.status === 'passed') return '已通过，等待生成交付文件'
  if (run.status === 'needs_input') return '需要补充输入'
  if (run.status === 'failed') return 'QA 未通过'
  return '处理中'
}

function SelectedInput({ label, artifact }: { label: string; artifact: Artifact | null }) {
  return (
    <div className="selected-input">
      <strong>{label}</strong>
      <span>{artifact ? artifactPickerLabel(artifact) : '未选择'}</span>
    </div>
  )
}

function TaskRunSummary({
  run,
  issues = [],
  projectHardErrors
}: {
  run: Run
  issues?: QualityIssue[]
  projectHardErrors?: number
}) {
  const title = run.kind === 'qa' ? '最近校对任务' : run.kind === 'translation' ? '最近翻译任务' : '最近任务'
  const summary = run.metadata?.quality_summary as { hard_errors?: number } | undefined
  const metadataHardErrors = Number(summary?.hard_errors ?? 0)
  const issueCount = issues.length || metadataHardErrors
  const issueText = issueCount ? `待处理问题 ${issueCount} 条` : '无待处理问题'
  const projectGate = typeof projectHardErrors === 'number' ? `，项目规则必须修复 ${projectHardErrors}` : ''
  return (
    <div className="task-summary">
      <div>
        <strong>{title}</strong>
        <span>{new Date(run.created_at).toLocaleString()}</span>
      </div>
      <div>
        <span className={`tag ${run.status === 'passed' ? 'tag-done' : 'tag-doing'}`}>{run.status}</span>
        <span>{issueText}{projectGate}</span>
      </div>
    </div>
  )
}

function IssueSummary({ issues }: { issues: QualityIssue[] }) {
  return (
    <div className="issue-summary">
      <div className="card-title"><div className="left">QA 问题摘要</div></div>
      <IssueGuide issues={issues} editableCount={0} />
      <IssueChips issues={issues} />
      <div className="muted-left">这些问题缺少可直接编辑的 workbook 行定位；请查看 QA 报告，或重新生成带行号的问题列表后再批量修复。</div>
    </div>
  )
}

function IssueChips({ issues }: { issues: QualityIssue[] }) {
  const counts = issues.reduce<Record<string, number>>((acc, issue) => {
    const key = issueTypeLabel(issue.check_type || issue.source)
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 6)
  return (
    <div className="issue-chips">
      {top.map(([name, count]) => <span key={name}>{name}: {count}</span>)}
    </div>
  )
}

function IssueGuide({ issues, editableCount }: { issues: QualityIssue[]; editableCount: number }) {
  const hard = issues.filter((issue) => issue.severity === 'hard').length
  const soft = issues.filter((issue) => issue.severity !== 'hard').length
  return (
    <div className="issue-guide">
      <div>
        <strong>当前不能作为最终交付</strong>
        <span>{hard} 个必须修复，{soft} 个建议修复；其中 {editableCount} 个可在网页直接改后重跑 QA。</span>
      </div>
      <p>这些是规则 QA 抓到的问题。模拟翻译通常会产生大量术语缺失；正式接入 GPT / Claude 后会按提示词和术语快照翻译，问题量会下降，但不会承诺自动清零，最终仍以“必须修复问题 = 0”作为交付标准。</p>
    </div>
  )
}

function issueTypeLabel(value: string): string {
  const key = String(value || '').toLowerCase()
  const labels: Record<string, string> = {
    term_missing: '术语未命中',
    term_partial_hit: '术语只命中一部分',
    ui_length_overflow: '界面长度超限',
    title_case_overuse: '大小写风格异常',
    placeholder_mismatch: '变量占位符错误',
    tag_mismatch: '标签不一致',
    newline_mismatch: '换行不一致',
    raw_cn: '译文残留中文',
    global_harness: '通用 QA 规则',
    project_harness: '项目规则',
    semantic_qa: '模型语义校对'
  }
  return labels[key] || value || '质量问题'
}

function severityLabel(value: string): string {
  return String(value).toLowerCase() === 'hard' ? '必须修复' : '建议修复'
}

function issueSourceLabel(value: string): string {
  const key = String(value || '').toLowerCase()
  if (key === 'global_harness') return '通用规则'
  if (key === 'project_harness') return '项目规则'
  if (key === 'semantic_qa') return '模型校对'
  return value || 'QA'
}

function issueHumanMessage(issue: QualityIssue): string {
  const sourceTerm = issue.message.match(/for ['"](.+?)['"]/)?.[1]
  const expected = issue.message.match(/expected one of \[(.+?)\]/)?.[1]?.replace(/['"]/g, '').trim()
  if (issue.check_type === 'term_missing' && sourceTerm && expected) {
    return `原文术语「${sourceTerm}」未按项目术语表翻译，建议使用：${expected}。`
  }
  if (issue.check_type === 'term_partial_hit' && sourceTerm && expected) {
    return `原文术语「${sourceTerm}」只翻出了一部分，建议完整使用：${expected}。`
  }
  if (issue.check_type === 'ui_length_overflow') return '译文可能超出按钮、弹窗或移动端 UI 宽度，需要缩短。'
  if (issue.check_type === 'title_case_overuse') return '译文大小写风格可能过度标题化，需要改成更自然的界面文案。'
  return issue.message || issueTypeLabel(issue.check_type)
}

function CheckItem({ ok, title, detail }: { ok: boolean; title: string; detail: string }) {
  return (
    <div className="check-item">
      <div className={`check-icon ${ok ? 'check-pass' : 'check-warn'}`}>{ok ? '✓' : '!'}</div>
      <div className="check-info"><div className="name">{title}</div><div className="detail">{detail}</div></div>
    </div>
  )
}

function ActionStatus({ status, busy }: { status: string; busy: boolean }) {
  if (!status) return null
  return (
    <div className={`inline-status ${busy ? 'running' : ''}`} role="status" aria-live="polite">
      {busy ? <span className="loading" /> : null}
      <span>{busy ? '正在执行：' : '当前状态：'}{status}</span>
    </div>
  )
}

function AssetSelect({
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

function GlossaryPreview({ rows, selectedLanguage = 'en' }: { rows: GlossaryPreviewRow[]; selectedLanguage?: LanguageCode }) {
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

function FileBox({ label, onFile, testId }: { label: string; onFile: (file: File) => void; testId?: string }) {
  return (
    <label className="upload-box" data-testid={testId}>
      <div className="icon">📄</div>
      <div className="label">{label}</div>
      <input type="file" hidden onChange={(event) => event.target.files?.[0] ? onFile(event.target.files[0]) : null} />
    </label>
  )
}

function ArtifactNote({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  return (
    <div className={`ai-card ${compact ? 'compact-note' : ''}`}>
      <div className="ai-header">{artifactPickerLabel(artifact)}</div>
      {!compact ? <div className="muted-left">{artifactFileName(artifact)}</div> : null}
    </div>
  )
}

function DeleteProjectModal({ project, busy, onClose, onDelete }: { project: Project; busy: boolean; onClose: () => void; onDelete: (project: Project) => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal delete-project-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-project-title">
        <h3 id="delete-project-title">⚠️ 删除项目</h3>
        <p>你正在删除 <strong>{project.icon ? `${project.icon} ` : ''}{project.name}</strong>。</p>
        <div className="delete-warning">
          <strong>此操作不可撤销</strong>
          <span>会删除该项目的任务、术语、译文归档、公告任务、产物记录和本地项目文件。</span>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>取消</button>
          <button type="button" className="btn btn-danger" disabled={busy} onClick={() => onDelete(project)}>确认删除</button>
        </div>
      </div>
    </div>
  )
}

function CancelAnnouncementTaskModal({ task, busy, onClose, onCancelTask }: { task: AnnouncementTask; busy: boolean; onClose: () => void; onCancelTask: (task: AnnouncementTask) => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal delete-project-modal" role="alertdialog" aria-modal="true" aria-labelledby="cancel-announcement-title">
        <h3 id="cancel-announcement-title">⚠️ 取消公告任务</h3>
        <p>你正在取消 <strong>{task.title || task.id}</strong>。</p>
        <div className="delete-warning">
          <strong>取消后不再显示在活跃公告任务里</strong>
          <span>已生成的过程产物和审计记录会保留；如果要重新处理，请新建公告任务。</span>
        </div>
        <div className="modal-foot">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>返回</button>
          <button type="button" className="btn btn-danger" disabled={busy} onClick={() => onCancelTask(task)}>确认取消</button>
        </div>
      </div>
    </div>
  )
}

function NewProjectModal({ onClose, onCreate }: { onClose: () => void; onCreate: (form: FormData) => void }) {
  const [typeMode, setTypeMode] = useState('科幻 SLG')
  return (
    <div className="modal-mask show">
      <form className="modal" onSubmit={(event) => { event.preventDefault(); onCreate(new FormData(event.currentTarget)) }}>
        <h3>🆕 新建本地化项目</h3>
        <p>填写基本信息即可创建，后续可在项目里完善提示词和术语表。</p>
        <label className="field-label">项目名称</label>
        <input name="name" placeholder="例如：星际边境 / 机甲纪元" required />
        <label className="field-label">项目类型</label>
        <select value={typeMode} onChange={(event) => setTypeMode(event.target.value)}>
          <option>科幻 SLG</option>
          <option>女性向恋爱</option>
          <option>休闲合成</option>
          <option>武侠 RPG</option>
          <option>其他</option>
        </select>
        {typeMode === '其他' ? (
          <input name="type" placeholder="手动填写项目类型 / 标签" required autoFocus />
        ) : (
          <input name="type" type="hidden" value={typeMode} />
        )}
        <label className="field-label">图标</label>
        <input name="icon" placeholder="🎮" />
        <label className="field-label">描述</label>
        <input name="description" placeholder="目标用户、题材、语气要求" />
        <div className="modal-foot"><button type="button" className="btn btn-ghost" onClick={onClose}>取消</button><button className="btn btn-primary">创建</button></div>
      </form>
    </div>
  )
}

function SettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null)
  const [provider, setProvider] = useState('openai')
  const [preset, setPreset] = useState('balanced')
  const apiKeyPlaceholder = settings?.api_key === 'configured' ? '已配置；留空不修改' : '写入私有 settings.local.json'
  useEffect(() => {
    api<Record<string, unknown>>('/api/settings').then((loaded) => {
      setSettings(loaded)
      setProvider(String(loaded.provider) === 'anthropic' ? 'anthropic' : 'openai')
      setPreset(['fast', 'balanced', 'deep'].includes(String(loaded.preset)) ? String(loaded.preset) : 'balanced')
    })
  }, [])
  async function submit(form: FormData) {
    const saved = await api<Record<string, unknown>>('/api/settings', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.get('provider'),
        preset: form.get('preset'),
        api_key: form.get('api_key')
      })
    })
    setSettings(saved)
    onClose()
  }
  return (
    <div className="modal-mask show">
      <form className="modal settings-modal" onSubmit={(event) => { event.preventDefault(); submit(new FormData(event.currentTarget)) }}>
        <div className="settings-head">
          <h3>⚙ 设置</h3>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>关闭</button>
        </div>
        <div className="settings-grid">
          <label>
            <span>Provider</span>
            <select name="provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="openai">GPT</option>
              <option value="anthropic">Claude</option>
            </select>
          </label>
          <label>
            <span>预设</span>
            <select name="preset" value={preset} onChange={(event) => setPreset(event.target.value)}>
              <option value="fast">快速响应</option>
              <option value="balanced">平衡</option>
              <option value="deep">深度思考</option>
            </select>
          </label>
          <label className="settings-wide">
            <span>API key</span>
            <input name="api_key" type="password" placeholder={apiKeyPlaceholder} />
          </label>
          <p className="settings-wide settings-note">长文本拆批、限流、重试和预算提醒由系统按预设自动管理。</p>
        </div>
        <div className="settings-actions"><button className="btn btn-primary">保存设置</button></div>
      </form>
    </div>
  )
}

function FrequencyModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal">
        <h3>💡 高频词补充策略</h3>
        <p>系统会从完整语言表中提取高频、易混淆和需要统一维护的中文术语，生成候选批次、project brief 和 prompt。</p>
        <ul className="strategy-list">
          <li>筛选：先按中文提取候选，再按项目术语库中文去重。</li>
          <li>跳过：项目术语表已存在的中文不会进入候选，也不会跨语言自动补译。</li>
          <li>审核：新增候选必须在表格里确认当前语言译文 / 备选译文 / 分类 / 备注后，点加入才会进入项目术语库。</li>
          <li>审计：每次扫描会在 run 日志里记录候选数、去重数、新增数和跳过数。</li>
        </ul>
        <div className="modal-foot"><button className="btn btn-primary" onClick={onClose}>知道了</button></div>
      </div>
    </div>
  )
}

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Missing root element')
}
window.__lwsRoot = window.__lwsRoot ?? createRoot(rootElement)
window.__lwsRoot.render(<App />)
