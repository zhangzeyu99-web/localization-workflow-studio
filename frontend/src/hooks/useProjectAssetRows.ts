import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../apiClient'
import { errorText } from '../appText'
import { isLanguageCode, type LanguageCode } from '../languages'
import type {
  GlossaryTerm,
  ProjectAssetKind,
  ProjectAssetWidePage,
  TranslationEntry,
  WideGlossaryRow,
  WideLanguageValue,
  WideTranslationRow,
} from '../types'

type AssetWideRow = WideGlossaryRow | WideTranslationRow
type AssetWidePage = ProjectAssetWidePage<AssetWideRow>

type BackendLanguageValue = {
  id?: string
  language?: string
  target?: string
  target_alt?: string
  source_type?: string
  review_status?: string
  record?: GlossaryTerm | TranslationEntry
}

type BackendWideRow = Omit<AssetWideRow, 'translations' | 'languages'> & {
  translations?: Record<string, BackendLanguageValue>
  languages?: string[]
}

type BackendWidePage = Omit<AssetWidePage, 'rows' | 'languages' | 'record_languages' | 'coverage'> & {
  rows?: BackendWideRow[]
  languages?: string[]
  record_languages?: string[]
  coverage?: Record<string, number>
}

type AssetRowsState = AssetWidePage & {
  projectId: string
  kind: ProjectAssetKind
}

const emptyPage = (projectId: string, kind: ProjectAssetKind, page: number, pageSize: number): AssetRowsState => ({
  projectId,
  kind,
  rows: [],
  total_rows: 0,
  page,
  page_size: pageSize,
  total_pages: 1,
  languages: [],
  record_languages: [],
  coverage: {},
  revision: '',
})

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

function languageCodes(values: string[] | undefined): LanguageCode[] {
  return (values || []).filter((value): value is LanguageCode => isLanguageCode(value))
}

function glossaryRecord(row: BackendWideRow, language: LanguageCode, value: BackendLanguageValue): GlossaryTerm {
  return {
    id: value.id || '',
    term_key: 'term_key' in row ? String(row.term_key || '') : '',
    source: String(row.source || ''),
    target: String(value.target || ''),
    target_alt: '',
    language,
    category: 'category' in row ? String(row.category || '') : '',
    note: String(row.note || ''),
    source_type: String(value.source_type || 'archive'),
    review_status: String(value.review_status || ''),
    confirmed: true,
  }
}

function translationRecord(row: BackendWideRow, language: LanguageCode, value: BackendLanguageValue): TranslationEntry {
  return {
    id: value.id || '',
    entry_key: 'entry_key' in row ? String(row.entry_key || '') : '',
    source: String(row.source || ''),
    target: String(value.target || ''),
    target_alt: '',
    language,
    sheet: '',
    row_number: 0,
    note: String(row.note || ''),
    source_type: String(value.source_type || 'archive'),
    review_status: String(value.review_status || ''),
    source_artifact_id: '',
  }
}

function normalizeRow(row: BackendWideRow, kind: ProjectAssetKind): AssetWideRow {
  const translations: Partial<Record<LanguageCode, WideLanguageValue<GlossaryTerm | TranslationEntry>>> = {}
  for (const [rawLanguage, value] of Object.entries(row.translations || {})) {
    if (!isLanguageCode(rawLanguage)) continue
    const target = String(value.target || '')
    translations[rawLanguage] = {
      record: value.record || (kind === 'glossary'
        ? glossaryRecord(row, rawLanguage, value)
        : translationRecord(row, rawLanguage, value)),
      target,
      target_alt: '',
    }
  }
  const languages = languageCodes(row.languages).filter((language) => Boolean(translations[language]))
  if (kind === 'glossary') {
    return {
      source_key: String(row.source_key || ''),
      source: String(row.source || ''),
      term_key: 'term_key' in row ? String(row.term_key || '') : '',
      category: 'category' in row ? String(row.category || '') : '',
      note: String(row.note || ''),
      translations: translations as WideGlossaryRow['translations'],
      languages,
      conflicts: Array.isArray(row.conflicts) ? row.conflicts : [],
    }
  }
  return {
    source_key: String(row.source_key || ''),
    source: String(row.source || ''),
    entry_key: 'entry_key' in row ? String(row.entry_key || '') : '',
    note: String(row.note || ''),
    translations: translations as WideTranslationRow['translations'],
    languages,
    conflicts: Array.isArray(row.conflicts) ? row.conflicts : [],
  }
}

function normalizePage(payload: BackendWidePage, projectId: string, kind: ProjectAssetKind): AssetRowsState {
  const coverage: Partial<Record<LanguageCode, number>> = {}
  for (const [rawLanguage, count] of Object.entries(payload.coverage || {})) {
    if (isLanguageCode(rawLanguage)) coverage[rawLanguage] = Number(count || 0)
  }
  return {
    projectId,
    kind,
    rows: (payload.rows || []).map((row) => normalizeRow(row, kind)),
    total_rows: Number(payload.total_rows || 0),
    page: Number(payload.page || 1),
    page_size: Number(payload.page_size || 100),
    total_pages: Math.max(1, Number(payload.total_pages || 1)),
    languages: languageCodes(payload.languages),
    record_languages: languageCodes(payload.record_languages || payload.languages),
    coverage,
    revision: String(payload.revision || ''),
  }
}

export function useProjectAssetRows(
  projectId: string,
  kind: ProjectAssetKind,
  active: boolean,
  page: number,
  pageSize: number,
  q: string,
  languages: LanguageCode[],
  revisionHint: string | number = '',
) {
  const [debouncedQuery, setDebouncedQuery] = useState(q.trim())
  const [state, setState] = useState<AssetRowsState>(() => emptyPage(projectId, kind, page, pageSize))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [reloadGeneration, setReloadGeneration] = useState(0)
  const requestGenerationRef = useRef(0)
  const requestRef = useRef<AbortController | null>(null)
  const normalizedLanguages = useMemo(() => [...new Set(languages)].sort().join(','), [languages])

  useEffect(() => {
    requestRef.current?.abort()
    requestGenerationRef.current += 1
    const timer = window.setTimeout(() => setDebouncedQuery(q.trim()), 250)
    return () => window.clearTimeout(timer)
  }, [q])

  useEffect(() => {
    setDebouncedQuery(q.trim())
  }, [kind, projectId])

  useEffect(() => {
    requestGenerationRef.current += 1
    const generation = requestGenerationRef.current
    if (!active || !projectId) {
      setLoading(false)
      setError('')
      return undefined
    }
    const controller = new AbortController()
    requestRef.current = controller
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      q: debouncedQuery,
      sort: 'source',
    })
    if (normalizedLanguages) params.set('languages', normalizedLanguages)
    setLoading(true)
    setError('')
    api<BackendWidePage>(
      `/api/projects/${projectId}/${kind}/wide?${params.toString()}`,
      { signal: controller.signal },
      kind === 'glossary' ? '读取项目术语' : '读取译文归档',
    ).then((payload) => {
      if (controller.signal.aborted || requestGenerationRef.current !== generation) return
      setState(normalizePage(payload, projectId, kind))
    }).catch((caught) => {
      if (isAbort(caught) || requestGenerationRef.current !== generation) return
      setError(errorText(caught))
    }).finally(() => {
      if (requestRef.current === controller) requestRef.current = null
      if (!controller.signal.aborted && requestGenerationRef.current === generation) setLoading(false)
    })
    return () => {
      controller.abort()
      if (requestRef.current === controller) requestRef.current = null
    }
  }, [active, debouncedQuery, kind, normalizedLanguages, page, pageSize, projectId, reloadGeneration, revisionHint])

  useEffect(() => () => {
    requestRef.current?.abort()
    requestGenerationRef.current += 1
  }, [])

  const refresh = useCallback(() => setReloadGeneration((value) => value + 1), [])
  const scoped = active && state.projectId === projectId && state.kind === kind
    ? state
    : emptyPage(projectId, kind, page, pageSize)

  return {
    rows: scoped.rows,
    totalRows: scoped.total_rows,
    page: scoped.page,
    pageSize: scoped.page_size,
    totalPages: scoped.total_pages,
    languages: scoped.languages,
    recordLanguages: scoped.record_languages,
    coverage: scoped.coverage,
    revision: scoped.revision,
    loading,
    error,
    refresh,
  }
}
