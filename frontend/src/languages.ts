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

export const supportedLanguages: LanguageOption[] = [...defaultLanguages]
export const announcementLanguages = supportedLanguages
export const allLanguageOptions = supportedLanguages
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
    supportedLanguages.splice(0, supportedLanguages.length, ...next)
  }
  return supportedLanguages
}
