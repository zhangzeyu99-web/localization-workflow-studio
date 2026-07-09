import type { LanguageCode } from './languages'

export type Project = {
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
    execution_runs?: number
    language_tasks?: number
    deliverables?: number
    announcement_tasks?: number
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

export type ProjectHarness = {
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

export type Artifact = {
  id: string
  project_id?: string
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
  exists?: boolean
}

export type Run = {
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

export type GlossaryTerm = {
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

export type TranslationEntry = {
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

export type GlossaryPreviewRow = {
  term_key?: string
  source: string
  target: string
  target_alt?: string
  category: string
  note: string
  language?: string
}

export type WideLanguageValue<T> = {
  record: T
  target: string
  target_alt?: string
}

export type WideConflict = {
  field: string
  values: string[]
}

export type WideGlossaryRow = {
  source_key: string
  source: string
  term_key: string
  category: string
  note: string
  translations: Partial<Record<LanguageCode, WideLanguageValue<GlossaryTerm>>>
  languages: LanguageCode[]
  conflicts: WideConflict[]
}

export type WideTranslationRow = {
  source_key: string
  source: string
  entry_key: string
  note: string
  translations: Partial<Record<LanguageCode, WideLanguageValue<TranslationEntry>>>
  languages: LanguageCode[]
  conflicts: WideConflict[]
}

export type GlossaryBatch = {
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

export type GlossaryCandidate = {
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

export type QualityIssue = {
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

export type AppRuntimeVersion = {
  version: string
  git_sha?: string
  deployment_mode?: 'local' | 'cloud' | string
  data_root?: string
  frontend_assets?: string[]
}

export type AppSettings = {
  provider?: string
  preset?: string
  api_key?: string
  base_url?: string
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

export type TranslationReadiness = {
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
  ready_for_translation?: boolean
  ready_for_qa: boolean
  reason: string
  batch_size: number
  estimated_batches: number
  input_mode?: 'needs_translation' | 'ready_for_qa' | 'invalid' | string
  next_step?: number
  format_errors?: string[]
  user_message?: string
}

export type TranslationTargets = {
  artifact_id: string
  label: string
  supported_file: boolean
  source_detected: boolean
  detected_languages: LanguageCode[]
  suggested_language?: LanguageCode | null
  reason?: string
}

export type TranslationProgress = {
  total_rows: number
  completed_rows: number
  total_batches: number
  completed_batches: number
  remaining_batches: number
  current_batch?: number | null
  failed_batch?: number | null
  current_batch_status?: string | null
  current_batch_rows?: number | null
  current_attempt?: number | null
  max_attempts?: number | null
  provider_timeout_seconds?: number | null
  current_batch_started_at?: string | null
  message?: string
  term_audit?: {
    language?: LanguageCode | string
    term_count?: number
    project_term_count?: number
    extra_term_count?: number
    extra_term_artifact_id?: string
    term_hit_rows?: number
    term_hits?: number
    total_rows?: number
    pending_candidate_count?: number
    ready_candidate_count?: number
    needs_confirmation?: boolean
    warning?: string
  }
  batch_size: number
  max_concurrent_batches?: number
  estimated_total_input_tokens?: number
  rate_limit_wait_seconds?: number
  percent: number
  elapsed_seconds?: number | null
  average_batch_seconds?: number | null
  eta_seconds?: number | null
}

export type DeliveryFile = {
  kind: string
  filename: string
  path: string
  download_url?: string
  artifact_id?: string
}

export type LargeTextPreflight = {
  workflow?: string
  unique_items?: number
  source_rows?: number
  target_languages?: string[]
  target_language_count?: number
  estimated_target_cells?: number
  long_text_items?: number
  workbook_count?: number
  large_pack?: boolean
  large_pack_reasons?: string[]
  recommended_translation_shards?: number
}

export type LargeTextGateStatus = {
  status?: 'passed' | 'failed' | 'skipped' | 'waived' | string
  hard_blockers?: number
  reason?: string
  artifact_id?: string
}

export type LargeTextRunState = {
  mode?: 'auto' | 'strict' | 'off' | string
  preflight?: LargeTextPreflight
  preflight_artifact_id?: string
  cache_lint?: LargeTextGateStatus
  readback_gate?: LargeTextGateStatus
  retro_artifact_id?: string
}

export type LineProofreadState = {
  status?: string
  provider?: string
  model?: string
  reviewed_rows?: number
  batches?: number
  suggested?: number
  rejected_by_audit?: number
  applied?: number
  suggestions_artifact_id?: string
}

export type MultilingualQueueLanguage = {
  language: LanguageCode
  visible_language: string
  run_id?: string | null
  translation_run_id?: string | null
  qa_run_id?: string | null
  status: string
  step: 'pending' | 'translation' | 'qa' | 'delivery' | string
  can_continue?: boolean
  error?: string
  progress?: Partial<TranslationProgress>
  quality_summary?: Record<string, unknown>
  large_text?: LargeTextRunState
}

export type MultilingualQueueStatus = {
  project_id: string
  input_artifact_id: string
  overall_status: string
  active_job_id?: string | null
  languages: MultilingualQueueLanguage[]
  created_run_ids?: string[]
  queue_started?: boolean
  active_conflict?: string
}

export type ProjectMaterialAnalysis = {
  source?: string
  warning?: string
  summary?: {
    total?: number
    parsed?: number
    unsupported?: number
    images?: number
    language_table_candidates?: number
    warnings?: number
  }
  materials?: {
    artifact_id?: string
    label?: string
    filename?: string
    material_type?: string
    status?: string
    warning?: string
    excerpt?: string
    included_in_ai?: boolean
    readable?: boolean
    readable_reason?: string
    language_table_candidate?: boolean
    detected_languages?: string[]
    chars?: number
    rows?: number
    pages?: number
    truncated?: boolean
  }[]
  language_table_candidates?: {
    artifact_id: string
    label?: string
    languages?: string[]
    rows?: number
  }[]
}

export type ProjectAnalysisResponse = {
  project: Project
  artifacts: Artifact[]
  prompt: string
  analysis?: ProjectMaterialAnalysis
}

export type AnnouncementLookupSummary = {
  language: string
  text_chars: number
  materials: number
  matched_terms: number
  matched_translations: number
  constraint_status: string
}

export type AnnouncementLookupResult = {
  run: Run
  summary: AnnouncementLookupSummary
  artifacts: Artifact[]
  manifest: Record<string, unknown>
}

export type AnnouncementTaskLanguage = {
  id: string
  task_id: string
  project_id: string
  language: LanguageCode
  status: string
  current_step: number
  metadata?: Record<string, unknown>
}

export type AnnouncementTask = {
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

export type AnnouncementTaskResult = {
  task: AnnouncementTask
  run?: Run
  summary?: Record<string, unknown>
  artifacts?: Artifact[]
  manifest?: Record<string, unknown>
  detected_languages?: LanguageCode[]
  selected_languages?: LanguageCode[]
  constraints?: Record<string, unknown>
}

export type AnnouncementTermRow = {
  id?: string
  source?: string
  translations?: Record<string, string>
  hit_count?: number
  first_position?: number
}

export type AnnouncementLookupOptions = {
  includeGlossary: boolean
  includeTranslationArchive: boolean
}

export type DeliverableTask = {
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
  delivered_with_issues?: boolean
  files: {
    final?: DeliveryFile
    changes?: DeliveryFile
    package?: DeliveryFile
    qa_summary?: DeliveryFile | null
    outputs?: DeliveryFile[]
  }
}

export type ProjectTab = 'meta' | 'glossary' | 'translation' | 'qa' | 'archive' | 'delivery'

export type AppView = 'overview' | 'wizard' | 'announcement' | 'quick'

export type QuickObjective = 'translate' | 'qa'

export type HistoryKind = 'translation' | 'qa' | 'all'

// Mirrors GET /api/system/active-jobs (backend/app/routers/system.py); one
// entry per currently-held per-project lease (backend/app/jobs.py).
export type ActiveJob = {
  lease_name: string
  job_id: string
  job_kind: string
  project_id: string
  project_name: string
  started_at: string | null
}
