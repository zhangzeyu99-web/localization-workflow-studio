export type LanguageCode = 'en' | 'ko' | 'ja' | 'fr' | 'de' | 'ru' | 'it' | 'es' | 'pt' | 'tr' | 'idn' | 'th' | 'ar'

export type LanguageOption = {
  code: LanguageCode
  label: string
  short: string
  targetHeader: string
  altHeader: string
}

type ApiLanguage = {
  code: string
  visible_code?: string
  label?: string
  target_header?: string
  alt_header?: string
}

const defaultLanguages: LanguageOption[] = [
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

const hiddenUiLanguages = new Set<LanguageCode>(['ar'])
const visibleLanguages = (languages: LanguageOption[]) => languages.filter((language) => !hiddenUiLanguages.has(language.code))

export const allLanguageOptions: LanguageOption[] = [...defaultLanguages]
export const supportedLanguages: LanguageOption[] = visibleLanguages(defaultLanguages)
export const announcementLanguages = supportedLanguages
export const unsupportedLanguages: string[] = []

export async function refreshLanguageOptions(apiBase = ''): Promise<LanguageOption[]> {
  const response = await fetch(`${apiBase}/api/languages`)
  if (!response.ok) return supportedLanguages
  const payload = (await response.json()) as { languages?: ApiLanguage[] }
  const next = (payload.languages || [])
    .map((item) => {
      const code = item.code as LanguageCode
      if (!defaultLanguages.some((lang) => lang.code === code)) return null
      const targetHeader = item.target_header || item.visible_code || code.toUpperCase()
      return {
        code,
        label: item.label || `${targetHeader} ${targetHeader}`,
        short: item.visible_code || targetHeader,
        targetHeader,
        altHeader: item.alt_header || ''
      }
    })
    .filter((item): item is LanguageOption => Boolean(item))
  if (next.length) {
    allLanguageOptions.splice(0, allLanguageOptions.length, ...next)
    supportedLanguages.splice(0, supportedLanguages.length, ...visibleLanguages(next))
  }
  return supportedLanguages
}

// Shared language helpers
export function languageSpec(code: string): LanguageOption {
  return allLanguageOptions.find((item) => item.code === code) || supportedLanguages[0]
}

export function languageChipTitle(lang: LanguageOption): string {
  return lang.label
}

export function languageQuery(code: LanguageCode): string {
  return `language=${encodeURIComponent(code)}`
}

export function isLanguageCode(value: string): value is LanguageCode {
  return allLanguageOptions.some((lang) => lang.code === value)
}

export function normalizeLanguageCode(value: unknown): LanguageCode | null {
  const raw = String(value || '').trim().toLowerCase().replace('_', '-')
  const compact = raw.replace(/[\s-]/g, '')
  const aliases: Record<string, LanguageCode> = {
    kr: 'ko', jp: 'ja', fre: 'fr', ger: 'de', rus: 'ru', ita: 'it', spa: 'es', por: 'pt', ptbr: 'pt', 'pt-br': 'pt', tk: 'tr', tur: 'tr', id: 'idn', ind: 'idn', tha: 'th', ara: 'ar'
  }
  const code = aliases[raw] || aliases[compact] || raw
  return isLanguageCode(code) ? code : null
}

export function normalizeLanguageArray(value: unknown): LanguageCode[] {
  if (!Array.isArray(value)) return []
  const normalized: LanguageCode[] = []
  for (const item of value) {
    const code = normalizeLanguageCode(item)
    if (code && !normalized.includes(code)) normalized.push(code)
  }
  return allLanguageOptions.map((lang) => lang.code).filter((code) => normalized.includes(code))
}
