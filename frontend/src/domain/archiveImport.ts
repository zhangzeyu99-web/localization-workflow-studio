import type { LanguageCode } from '../languages'
import type { Artifact } from '../types'

export type ArchiveImportKind = 'translations' | 'glossary'
export type ArchiveImportStage = 'source' | 'settings' | 'preview' | 'success'
export type ArchiveImportMode = 'merge' | 'snapshot'
export type ArchiveImportReadbackOptions = { readbackOnly?: boolean }

export type ArchiveImportSettings = {
  mode: ArchiveImportMode
  languages: LanguageCode[]
  sheet: string
  datasetKey: string
  idColumn: string
  sourceColumn: string
  targetColumn: string
  categoryColumn: string
  noteColumn: string
  overrideProtected: boolean
}

export type ArchiveImportSummary = {
  source_rows?: number
  insert?: number
  update?: number
  unchanged?: number
  skip?: number
  clear?: number
  deactivate?: number
  protected?: number
  conflict?: number
}

export type ArchiveImportConflict = {
  code?: string
  message?: string
  language?: string
  entry_key?: string
  term_key?: string
  source?: string
  row_number?: number
}

export type ArchiveImportChange = {
  ordinal?: number
  action?: string
  language?: string
  entry_key?: string
  term_key?: string
  source?: string
  target?: string
  explicit_empty?: boolean
}

export type ArchiveImportPreview = {
  batch_id: string
  token: string
  artifact: { id: string; label?: string; kind?: string; checksum?: string }
  sheet: string
  mode: ArchiveImportMode
  dataset_key: string
  languages: LanguageCode[]
  columns?: Record<string, unknown>
  summary: ArchiveImportSummary
  changes: ArchiveImportChange[]
  conflicts: ArchiveImportConflict[]
  can_commit: boolean
}

export type ArchiveImportCommitResult = {
  project_id?: string
  kind?: ArchiveImportKind | string
  batch_id: string
  token?: string
  status: string
  summary: ArchiveImportSummary
  changed_count?: number
  imported_count?: number
  languages?: LanguageCode[]
  language_summary?: Record<string, ArchiveImportSummary>
  entries?: Array<{ language?: string }>
  terms?: Array<{ language?: string }>
  dataset_key?: string
  sheet?: string
  state_version?: number
}

export type ArchiveImportErrorDetail = {
  code?: string
  message?: string
  sheets?: string[]
  candidates?: string[]
  batch_id?: string
  [key: string]: unknown
}

export type ArchiveImportState = {
  stage: ArchiveImportStage
  artifact: Artifact | null
  settings: ArchiveImportSettings
  preview: ArchiveImportPreview | null
  result: ArchiveImportCommitResult | null
  availableSheets: string[]
  busy: 'upload' | 'analyze' | 'commit' | null
  message: string
  error: string
  errorDetail: ArchiveImportErrorDetail | null
  readbackWarning: string
}

export type ArchiveImportAction =
  | { type: 'reset'; artifact: Artifact | null; language: LanguageCode }
  | { type: 'select_artifact'; artifact: Artifact | null; settings?: ArchiveImportSettings }
  | { type: 'show_source' }
  | { type: 'show_settings' }
  | { type: 'update_settings'; settings: ArchiveImportSettings }
  | { type: 'upload_start'; filename: string }
  | { type: 'analyze_start' }
  | { type: 'analyze_success'; preview: ArchiveImportPreview }
  | { type: 'sheet_required'; detail: ArchiveImportErrorDetail; message: string }
  | { type: 'commit_start' }
  | { type: 'commit_success'; result: ArchiveImportCommitResult; readbackWarning?: string }
  | { type: 'readback_start' }
  | { type: 'readback_success' }
  | { type: 'readback_failure'; message: string }
  | { type: 'failure'; message: string; detail?: ArchiveImportErrorDetail | null }

export function initialArchiveImportSettings(language: LanguageCode): ArchiveImportSettings {
  return {
    mode: 'merge',
    languages: [language],
    sheet: '',
    datasetKey: '',
    idColumn: '',
    sourceColumn: '',
    targetColumn: '',
  categoryColumn: '',
    noteColumn: '',
    overrideProtected: false,
  }
}

export function createArchiveImportState(artifact: Artifact | null, language: LanguageCode): ArchiveImportState {
  return {
    stage: artifact ? 'settings' : 'source',
    artifact,
    settings: initialArchiveImportSettings(language),
    preview: null,
    result: null,
    availableSheets: [],
    busy: null,
    message: artifact ? '已选择来源文件，请确认导入设置。' : '请选择项目内文件，或上传新文件。',
    error: '',
    errorDetail: null,
    readbackWarning: '',
  }
}

export function archiveImportReducer(state: ArchiveImportState, action: ArchiveImportAction): ArchiveImportState {
  switch (action.type) {
    case 'reset':
      return createArchiveImportState(action.artifact, action.language)
    case 'select_artifact':
      return {
        ...state,
        artifact: action.artifact,
        settings: action.settings || state.settings,
        stage: action.artifact ? 'settings' : 'source',
        preview: null,
        result: null,
        availableSheets: [],
        busy: null,
        error: '',
        errorDetail: null,
        readbackWarning: '',
        message: action.artifact ? '文件已就绪；上传不会自动分析或写入。' : '请选择项目内文件，或上传新文件。',
      }
    case 'show_source':
      return { ...state, stage: 'source', error: '', errorDetail: null }
    case 'show_settings':
      return { ...state, stage: 'settings', error: '', errorDetail: null }
    case 'update_settings':
      return {
        ...state,
        settings: action.settings,
        stage: 'settings',
        preview: null,
        result: null,
        busy: null,
        error: '',
        errorDetail: null,
        readbackWarning: '',
        message: '设置已变更；请重新分析差异后再提交。',
      }
    case 'upload_start':
      return { ...state, busy: 'upload', error: '', errorDetail: null, message: `正在上传：${action.filename}` }
    case 'analyze_start':
      return { ...state, busy: 'analyze', error: '', errorDetail: null, message: '正在分析差异，不会写入归档。' }
    case 'analyze_success':
      return {
        ...state,
        stage: 'preview',
        preview: action.preview,
        result: null,
        busy: null,
        error: '',
        errorDetail: null,
        message: action.preview.can_commit ? '差异分析完成；确认后才会写入。' : '差异分析完成，但当前冲突阻止提交。',
      }
    case 'sheet_required': {
      const sheets = action.detail.sheets || action.detail.candidates || []
      return {
        ...state,
        stage: 'settings',
        preview: null,
        busy: null,
        availableSheets: sheets.map(String),
        error: action.message,
        errorDetail: action.detail,
        message: '需要补充工作表设置后重新分析。',
      }
    }
    case 'commit_start':
      return { ...state, busy: 'commit', error: '', errorDetail: null, message: '正在提交并读回真实归档结果。' }
    case 'commit_success':
      return {
        ...state,
        stage: 'success',
        result: action.result,
        busy: null,
        error: '',
        errorDetail: null,
        readbackWarning: action.readbackWarning || '',
        message: action.readbackWarning ? '提交成功，但自动读回尚未确认。' : '提交成功，批次结果与当前项目归档已读回。',
      }
    case 'readback_start':
      return { ...state, busy: 'commit', message: '正在重新读回批次与项目归档。' }
    case 'readback_success':
      return { ...state, busy: null, readbackWarning: '', message: '批次结果与当前项目归档已读回。' }
    case 'readback_failure':
      return { ...state, busy: null, readbackWarning: action.message, message: '提交成功，但自动读回尚未确认。' }
    case 'failure':
      return {
        ...state,
        busy: null,
        error: action.message,
        errorDetail: action.detail || null,
        message: '操作未完成，归档未因本次失败继续写入。',
      }
    default:
      return state
  }
}

export function archiveImportConfigKey(settings: ArchiveImportSettings): string {
  return JSON.stringify({
    ...settings,
    languages: [...settings.languages].sort(),
  })
}

export function archiveImportSummaryValue(summary: ArchiveImportSummary | null | undefined, key: keyof ArchiveImportSummary): number {
  const value = Number(summary?.[key] || 0)
  return Number.isFinite(value) ? value : 0
}

export function archiveImportEndpoint(kind: ArchiveImportKind): 'translations' | 'glossary' {
  return kind === 'translations' ? 'translations' : 'glossary'
}

export function artifactCanBeImported(kind: ArchiveImportKind, artifact: Artifact): boolean {
  const artifactKind = String(artifact.kind || '').toLowerCase()
  const role = String(artifact.role || '').toLowerCase()
  if (kind === 'glossary') {
    return ['term_base', 'glossary_final', 'glossary_export'].includes(artifactKind)
      || ['glossary_source', 'glossary_curated'].includes(role)
  }
  return ['language_table', 'final_workbook', 'manual_fixed_workbook', 'qa_final_workbook', 'raw_translated_workbook'].includes(artifactKind)
    || ['language_source', 'translation_workbook', 'translation_draft'].includes(role)
}
