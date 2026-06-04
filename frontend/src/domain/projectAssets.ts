import { wideRowMatches } from '../assetTableState'
import { allLanguageOptions, supportedLanguages, normalizeLanguageCode, isLanguageCode, type LanguageCode } from '../languages'
import type { GlossaryTerm, Project, ProjectHarness, TranslationEntry, WideConflict, WideGlossaryRow, WideLanguageValue, WideTranslationRow } from '../types'

export function getProjectHarness(project: Project): ProjectHarness {
  return project.harness || {}
}

export function normalizeSourceKey(value: unknown): string {
  return String(value || '').trim().replace(/\s+/g, '').toLowerCase()
}

export function termHasTranslation(term: GlossaryTerm): boolean {
  return Boolean(String(term.target || '').trim() || String(term.target_alt || '').trim())
}

export function entryHasTranslation(entry: TranslationEntry): boolean {
  return Boolean(String(entry.target || '').trim() || String(entry.target_alt || '').trim())
}

export function languageFromValue(value: unknown): LanguageCode | null {
  return normalizeLanguageCode(value || 'en')
}

export function pickSharedValue<T extends Record<string, unknown>>(rows: T[], field: keyof T): string {
  for (const row of rows) {
    const value = String(row[field] || '').trim()
    if (value && value !== '-') return value
  }
  return ''
}

export function sharedConflicts<T extends Record<string, unknown>>(rows: T[], fields: (keyof T)[]): WideConflict[] {
  return fields.flatMap((field) => {
    const values: string[] = []
    for (const row of rows) {
      const value = String(row[field] || '').trim()
      if (value && value !== '-' && !values.includes(value)) values.push(value)
    }
    return values.length > 1 ? [{ field: String(field), values }] : []
  })
}

export function newestByUpdatedAt<T>(rows: T[]): T {
  return [...rows].sort((a, b) => String((b as { updated_at?: string }).updated_at || '').localeCompare(String((a as { updated_at?: string }).updated_at || '')))[0]
}

export function glossaryWideRows(project: Project): WideGlossaryRow[] {
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

export function translationWideRows(project: Project): WideTranslationRow[] {
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

export function visibleLanguagesFromRows(rows: { languages: LanguageCode[] }[]): LanguageCode[] {
  const found = new Set<LanguageCode>()
  for (const row of rows) row.languages.forEach((lang) => found.add(lang))
  return supportedLanguages.map((item) => item.code).filter((lang) => found.has(lang))
}

export function translationValuesForSearch(row: { translations: Partial<Record<LanguageCode, WideLanguageValue<GlossaryTerm | TranslationEntry>>> }): string[] {
  return supportedLanguages.flatMap((lang) => {
    const value = row.translations[lang.code]
    return value ? [value.target, value.target_alt || ''] : []
  })
}

export function glossaryWideRowMatches(row: WideGlossaryRow, query: string): boolean {
  return wideRowMatches([row.term_key, row.source, row.category, row.note, ...translationValuesForSearch(row)], query)
}

export function translationWideRowMatches(row: WideTranslationRow, query: string): boolean {
  return wideRowMatches([row.entry_key, row.source, row.note, ...translationValuesForSearch(row)], query)
}

export function displayLanguagesForWideRows(rows: { languages: LanguageCode[] }[], selectedLanguages: LanguageCode[]): LanguageCode[] {
  const available = new Set(visibleLanguagesFromRows(rows))
  const selected = new Set(selectedLanguages)
  return supportedLanguages
    .map((lang) => lang.code)
    .filter((code) => code === 'en' || (available.has(code) && selected.has(code)))
}

export function rowRecords<T>(row: { translations: Partial<Record<LanguageCode, WideLanguageValue<T>>>; languages: LanguageCode[] }): T[] {
  return row.languages.map((code) => row.translations[code]?.record).filter(Boolean) as T[]
}

export function glossaryCoverage(project: Project): Record<LanguageCode, number> {
  const rows = glossaryWideRows(project)
  return supportedLanguages.reduce((acc, lang) => {
    acc[lang.code] = rows.filter((row) => Boolean(row.translations[lang.code])).length
    return acc
  }, {} as Record<LanguageCode, number>)
}

export function archiveCoverage(project: Project): Record<LanguageCode, number> {
  const rows = translationWideRows(project)
  return supportedLanguages.reduce((acc, lang) => {
    acc[lang.code] = rows.filter((row) => Boolean(row.translations[lang.code])).length
    return acc
  }, {} as Record<LanguageCode, number>)
}

export function coverageSummary(coverage: Record<LanguageCode, number>): string {
  const entries = supportedLanguages
    .map((lang) => ({ lang, count: coverage[lang.code] || 0 }))
    .filter((item) => item.count > 0)
  if (!entries.length) return '暂无覆盖'
  const visible = entries.slice(0, 2).map((item) => `${item.lang.short} ${item.count}`).join(' / ')
  return entries.length > 2 ? `${visible} / +${entries.length - 2}` : visible
}

export function altColumnVisible(lang: LanguageCode): boolean {
  return lang === 'en'
}

export function scopeProjectToLanguage(project: Project, code: LanguageCode): Project {
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

export function availableLookupLanguages(project: Project): LanguageCode[] {
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

export function projectPromptForLanguage(project: Project, code: LanguageCode): string {
  const prompts = project.profile?.prompts_by_language
  if (prompts && typeof prompts === 'object' && code in prompts) {
    return String((prompts as Record<string, unknown>)[code] || '')
  }
  return project.prompt_text || ''
}

export function listToLines(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).join('\n') : ''
}

export function linesToList(value: string): string[] {
  return value.split('\n').map((line) => line.trim()).filter(Boolean)
}

export function rulesToLines(rules: ProjectHarness['hard_rules']): string {
  return (rules || [])
    .map((rule) => [rule.label, rule.description, rule.pattern].filter(Boolean).join(' | '))
    .join('\n')
}

export function linesToRules(value: string): ProjectHarness['hard_rules'] {
  return linesToList(value).map((line) => {
    const [label, description, pattern] = line.split('|').map((part) => part.trim())
    return { label: label || line, description: description || label || line, pattern: pattern || '', enabled: true }
  })
}

export function fixedTermsToLines(terms: ProjectHarness['fixed_terms']): string {
  return (terms || [])
    .map((term) => `${term.source || ''} => ${term.target || ''}${term.note ? ` | ${term.note}` : ''}`.trim())
    .filter(Boolean)
    .join('\n')
}

export function linesToFixedTerms(value: string): ProjectHarness['fixed_terms'] {
  return linesToList(value).map((line) => {
    const [pair, note] = line.split('|').map((part) => part.trim())
    const [source, target] = pair.split('=>').map((part) => part.trim())
    return { source: source || pair, target: target || '', note: note || '', severity: 'hard' }
  })
}

export function normalizeGlossaryNote(value: string | undefined): string {
  const note = String(value || '')
  if (/高频词扫描补全 (EN|JP|JA|KR|KO)\/(EN2|JP2|JA2|KR2|KO2)\?+/.test(note)) return '高频词候选，需人工确认'
  return note
}

export function fieldText(value: unknown, fallback = '未生成'): string {
  if (Array.isArray(value)) {
    const items = value.map((item) => String(item).trim()).filter(Boolean)
    return items.length ? items.join('、') : fallback
  }
  if (value === null || value === undefined) return fallback
  const text = String(value).trim()
  return text || fallback
}

export function profileText(project: Project, key: string, fallback = '未生成'): string {
  return fieldText(project.profile?.[key], fallback)
}

export function fixedTermsSummary(project: Project): string {
  const terms = getProjectHarness(project).fixed_terms || []
  if (!terms.length) return '未设置'
  return terms
    .slice(0, 5)
    .map((term) => [term.source, term.target].filter(Boolean).join(' => '))
    .filter(Boolean)
    .join('；') || '未设置'
}

export function ruleSummary(project: Project): string {
  const harness = getProjectHarness(project)
  const hard = (harness.hard_rules || []).length
  const soft = (harness.soft_rules || []).length
  if (!hard && !soft) return '未设置'
  return `必须规则 ${hard} 条，建议规则 ${soft} 条`
}
