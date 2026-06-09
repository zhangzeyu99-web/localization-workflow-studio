import { wideRowMatches } from '../assetTableState'
import { supportedLanguages, normalizeLanguageCode, isLanguageCode, languageSpec, type LanguageCode } from '../languages'
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

function recordValue(record: unknown, key: string): unknown {
  return record && typeof record === 'object' ? (record as Record<string, unknown>)[key] : undefined
}

function profileForLanguage(project: Project, code: LanguageCode): Record<string, unknown> {
  const profile = project.profile || {}
  const profiles = recordValue(profile, 'profiles_by_language')
  const scoped = recordValue(profiles, code)
  return scoped && typeof scoped === 'object' ? scoped as Record<string, unknown> : profile
}

function textField(record: Record<string, unknown>, key: string, fallback = ''): string {
  const value = record[key]
  return String(value === undefined || value === null || value === '' ? fallback : value)
}

function compactText(value: unknown): string {
  return String(value === undefined || value === null ? '' : value).replace(/\s+/g, ' ').trim()
}

function profileSourceText(profile: Record<string, unknown>): string {
  const notes = profile.asset_notes
  if (!Array.isArray(notes)) return ''
  return notes.map((item) => compactText(item)).join(' ')
}

function profileTableValue(source: string, labels: string[]): string {
  for (const label of labels) {
    const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const match = source.match(new RegExp(`\\|\\s*${escaped}(?:（[^|]*）)?\\s*\\|\\s*([^|]+?)\\s*\\|`))
    if (match?.[1]?.trim()) return match[1].trim()
  }
  return ''
}

function firstProfileText(...values: unknown[]): string {
  for (const value of values) {
    const text = compactText(value)
    if (text) return text
  }
  return ''
}

function promptSentence(label: string, value: string): string {
  const text = value.trim().replace(/[。；;]+$/g, '')
  return text ? `${label}：${text}。` : ''
}

function generatedChinesePrompt(project: Project, code: LanguageCode): string {
  const profile = profileForLanguage(project, code)
  const lang = languageSpec(code)
  const projectName = textField(profile, 'project_name', project.name || '\u5f53\u524d\u9879\u76ee')
  const source = profileSourceText(profile)
  const termMatch = source.match(/术语保持一致[：:]\s*([^；;。]+)/)
  const gameType = firstProfileText(profile.display_game_type, profileTableValue(source, ['游戏类型']), profile.game_type)
  const targetAudience = firstProfileText(profile.display_target_audience, profileTableValue(source, ['目标用户']), profile.target_audience)
  const contentScope = firstProfileText(profile.display_content_scope, profileTableValue(source, ['内容构成', '内容范围']), profile.content_scope)
  const worldview = firstProfileText(profile.display_worldview, profileTableValue(source, ['视觉与世界观', '世界观']), profile.tone)
  const style = firstProfileText(profile.display_translation_style, profileTableValue(source, ['翻译风格', '风格要求']), profile.translation_style)
  const focus = firstProfileText(profile.display_focus, profileTableValue(source, ['重点注意', '注意事项']))
  const keyTerms = firstProfileText(profile.display_key_terms, termMatch?.[1] || '')
  const termRule = lang.altHeader
    ? `\u9879\u76ee\u672f\u8bed\u4ee5\u672f\u8bed\u8868\u4e3a\u51c6\uff1a${lang.targetHeader} \u662f\u6807\u51c6\u8bd1\u6cd5\uff0c${lang.altHeader} \u662f\u7a33\u5b9a\u51fa\u73b0\u7684\u624b\u52a8\u9002\u914d\u8bd1\u6cd5\u3002`
    : `\u9879\u76ee\u672f\u8bed\u4ee5\u672f\u8bed\u8868\u4e3a\u51c6\uff1a${lang.targetHeader} \u662f\u6807\u51c6\u8bd1\u6cd5\u3002`
  return [
    `\u4f60\u6b63\u5728\u5904\u7406\u300a${projectName}\u300b\u7684\u6e38\u620f\u672c\u5730\u5316\uff0c\u76ee\u6807\u8bed\u8a00\uff1a${lang.label}\u3002`,
    promptSentence('项目定位', gameType),
    promptSentence('目标用户', targetAudience),
    promptSentence('内容范围', contentScope),
    promptSentence('世界观/语气', worldview),
    promptSentence('风格要求', style),
    promptSentence('重点注意', focus),
    promptSentence('核心术语', keyTerms),
    termRule,
    `\u5df2\u6709${lang.label}\u8bd1\u6587\u4ee3\u8868\u9879\u76ee\u5386\u53f2\u7528\u6cd5\uff1b\u5982\u9700\u4f18\u5316\uff0c\u4e0d\u80fd\u7834\u574f\u5df2\u56fa\u5b9a\u7684\u7cfb\u7edf\u672f\u8bed\u3002`,
    '\u5fc5\u987b\u4fdd\u7559\u53d8\u91cf\u3001\u6570\u5b57\u3001\u6362\u884c\u3001\u989c\u8272\u6807\u7b7e\u3001HTML/\u5bcc\u6587\u672c\u6807\u7b7e\u548c\u5360\u4f4d\u7b26\uff0c\u4f8b\u5982 {0}\u3001%s\u3001<color>\u3002',
    '\u65e0\u6cd5\u786e\u8ba4\u7684\u4e13\u6709\u540d\u8bcd\u6216\u4fe1\u606f\u7f3a\u53e3\u7528 [TBD] \u6807\u8bb0\uff0c\u4e0d\u8981\u81ea\u884c\u7f16\u9020\u8bbe\u5b9a\u3002',
  ].filter(Boolean).join('\n')
}

function looksLikeExecutionPrompt(value: string): boolean {
  if (!value.trim()) return false
  if (/JSONL|Project Harness|Translate into|Translate accurately|output protocol/i.test(value)) return true
  const latinLetters = (value.match(/[A-Za-z]/g) || []).length
  const cjkChars = (value.match(/[\u4e00-\u9fff]/g) || []).length
  return latinLetters > Math.max(80, cjkChars * 0.6)
}

export function projectPromptForLanguage(project: Project, code: LanguageCode): string {
  const displayPrompts = project.profile?.display_prompts_by_language
  if (displayPrompts && typeof displayPrompts === 'object' && code in displayPrompts) {
    const displayPrompt = String((displayPrompts as Record<string, unknown>)[code] || '')
    return looksLikeExecutionPrompt(displayPrompt) ? generatedChinesePrompt(project, code) : displayPrompt
  }
  if (project.profile && (recordValue(project.profile, 'profiles_by_language') || recordValue(project.profile, 'project_name'))) {
    return generatedChinesePrompt(project, code)
  }
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

function looksEnglishHeavy(value: unknown): boolean {
  const text = compactText(value)
  if (!text) return false
  const latinLetters = (text.match(/[A-Za-z]/g) || []).length
  const cjkChars = (text.match(/[\u4e00-\u9fff]/g) || []).length
  return latinLetters > Math.max(30, cjkChars * 1.5)
}

export function profileText(project: Project, key: string, fallback = '未生成'): string {
  const displayKeyBySource: Record<string, string> = {
    game_type: 'display_game_type',
    target_audience: 'display_target_audience',
    content_scope: 'display_content_scope',
    translation_style: 'display_translation_style'
  }
  const tableLabelsBySource: Record<string, string[]> = {
    game_type: ['游戏类型'],
    target_audience: ['目标用户', '目标用户（推断）'],
    content_scope: ['内容构成', '内容范围'],
    translation_style: ['翻译风格', '风格要求']
  }
  const profile = profileForLanguage(project, 'en')
  const topProfile = project.profile || {}
  const displayKey = displayKeyBySource[key]
  const source = [profileSourceText(profile), profileSourceText(topProfile)].filter(Boolean).join(' ')
  const tableValue = tableLabelsBySource[key] ? profileTableValue(source, tableLabelsBySource[key]) : ''
  const displayValue = displayKey ? firstProfileText(profile[displayKey], topProfile[displayKey]) : ''
  const rawValue = firstProfileText(profile[key], topProfile[key])
  const preferred = firstProfileText(
    looksEnglishHeavy(displayValue) ? '' : displayValue,
    tableValue,
    looksEnglishHeavy(rawValue) && tableValue ? '' : rawValue
  )
  if (looksEnglishHeavy(preferred) && displayKey) {
    if (key === 'game_type' && project.type) return `${project.type}（请重新运行 AI 分析更新详细信息）`
    return '请重新运行 AI 分析生成中文信息'
  }
  return fieldText(preferred, fallback)
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
