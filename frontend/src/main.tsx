import React, { useEffect, useMemo, useState } from 'react'
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
}

type GlossaryBatch = {
  id: string
  project_id: string
  run_id?: string
  source_artifact_id?: string
  label: string
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
}

type TranslationReadiness = {
  artifact_id: string
  label: string
  target_language: string
  source_rows: number
  translated_rows: number
  empty_target_rows: number
  cjk_target_rows: number
  needs_translation: boolean
  ready_for_qa: boolean
  reason: string
  batch_size: number
  estimated_batches: number
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
const langOptions = ['🇺🇸 英语 EN', '🇫🇷 法语 FR', '🇩🇪 德语 DE', '🇧🇷 巴葡 PT-BR', '🇷🇺 俄语 RU', '🇯🇵 日语 JA', '🇰🇷 韩语 KO', '🇪🇸 西语 ES', '🇸🇦 阿语 AR']
const batchPresets = [
  { key: 'safe', label: '稳妥', size: 40, desc: '失败成本低，适合长文本/术语多' },
  { key: 'balanced', label: '平衡', size: 90, desc: '推荐默认，速度和稳定性折中' },
  { key: 'fast', label: '高速', size: 160, desc: '批次数少，适合短 UI 文案' }
]
type ProjectTab = 'meta' | 'glossary' | 'translation' | 'qa' | 'archive' | 'delivery'

function getProjectHarness(project: Project): ProjectHarness {
  return project.harness || {}
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

function runArtifacts(project: Project, runId: string | undefined): Artifact[] {
  if (!runId) return []
  return (project.artifacts || []).filter((artifact) => artifact.run_id === runId)
}

function artifactRole(artifact: Artifact): string {
  if (artifact.role) return artifact.role
  const map: Record<string, string> = {
    language_table: 'language_source',
    term_base: 'glossary_source',
    glossary_final: 'glossary_curated',
    final_workbook: 'translation_workbook',
    qa_final_workbook: 'translation_workbook',
    raw_translated_workbook: 'translation_draft',
    qa_report: 'qa_report',
    qa_result: 'qa_report',
    quality_summary: 'qa_report',
    glossary_snapshot: 'run_snapshot',
    prompt_snapshot: 'run_snapshot',
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

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  return String(error)
}

function clampBatchSize(value: number): number {
  if (!Number.isFinite(value)) return 90
  return Math.max(1, Math.min(200, Math.round(value)))
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
  if (/高频词扫描补全 EN\/EN2\?+/.test(note)) return '高频词候选，需人工确认'
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
    throw new Error(text || response.statusText)
  }
  return response.json()
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [currentId, setCurrentId] = useState<string>('')
  const [view, setView] = useState<'overview' | 'wizard'>('overview')
  const [tab, setTab] = useState<ProjectTab>('meta')
  const [step, setStep] = useState(1)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
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
  const [selectedLangs, setSelectedLangs] = useState<string[]>(['🇺🇸 英语 EN'])
  const [glossaryPreview, setGlossaryPreview] = useState<GlossaryPreviewRow[]>([])
  const [glossaryBatches, setGlossaryBatches] = useState<GlossaryBatch[]>([])
  const [glossaryCandidates, setGlossaryCandidates] = useState<GlossaryCandidate[]>([])
  const [qualityIssues, setQualityIssues] = useState<QualityIssue[]>([])
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [deliverables, setDeliverables] = useState<DeliverableTask[]>([])
  const [translationReadiness, setTranslationReadiness] = useState<TranslationReadiness | null>(null)
  const [translationBatchSize, setTranslationBatchSize] = useState(90)

  useEffect(() => {
    refreshProjects()
    refreshSettings()
  }, [])

  const current = useMemo(() => projects.find((p) => p.id === currentId), [projects, currentId])

  useEffect(() => {
    if (currentId) refreshCurrent()
  }, [currentId])

  useEffect(() => {
    if (!current) return
    setIntro(current.description || '')
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
  }, [current?.id, latestRun?.id])

  useEffect(() => {
    if (current?.id && tab === 'delivery') {
      refreshDeliverables()
    }
  }, [current?.id, current?.runs?.length, tab])

  useEffect(() => {
    if (!sourceArtifact?.id) {
      setTranslationReadiness(null)
      return
    }
    refreshTranslationReadiness(sourceArtifact.id)
  }, [sourceArtifact?.id, translationBatchSize])

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
    const loaded = await api<{ batches: GlossaryBatch[]; active_batch: GlossaryBatch | null; candidates: GlossaryCandidate[] }>(`/api/projects/${projectId}/glossary/batches`)
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
        setStatus(`已存在，已复用：${artifact.label}`)
      } else {
        setStatus(`已上传：${artifact.label}`)
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
          asset_artifact_ids: assetArtifacts.map((artifact) => artifact.id)
        })
      })
      await refreshCurrent()
      setStatus('项目提示词已生成')
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
          target_column: 'en',
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
      const result = await api<{ rows: GlossaryPreviewRow[] }>(`/api/projects/${current.id}/glossary/import-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: termArtifact.id })
      })
      setGlossaryPreview(result.rows)
      setStatus(`术语表预览完成：${result.rows.length} 条`)
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
      const result = await api<{ imported_count: number }>(`/api/projects/${current.id}/glossary/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: termArtifact.id })
      })
      await refreshCurrent()
      setStatus(`术语表已导入：${result.imported_count} 条`)
    } catch (error) {
      setStatus(`术语表导入失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function refreshTranslationReadiness(artifactId: string) {
    const batchSize = clampBatchSize(translationBatchSize)
    try {
      const result = await api<TranslationReadiness>(`/api/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}`)
      setTranslationReadiness(result)
      return result
    } catch {
      setTranslationReadiness(null)
      return null
    }
  }

  async function runTranslate(taskCode: 'A' | 'T' = 'T') {
    if (!current || !sourceArtifact) return
    const selectedBatchSize = clampBatchSize(translationBatchSize)
    const readiness = translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === selectedBatchSize
      ? translationReadiness
      : await refreshTranslationReadiness(sourceArtifact.id)
    if (readiness && canSkipModelTranslation(readiness)) {
      setQaArtifact(sourceArtifact)
      setStep(8)
      setStatus(`已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文，无需模型翻译，请直接运行 QA。`)
      return
    }
    const blockReason = formalTranslationBlockReason(settings, sourceArtifact, current)
    if (blockReason) {
      setStatus(`无法开始翻译：${blockReason}`)
      return
    }
    if (!selectedLangs.some((item) => item.includes('EN'))) {
      setStatus('v1 只支持英语真闭环；其他语言保留为后续 provider 能力')
      return
    }
    setBusy(true)
    setStatus(`翻译前检查通过，准备分批翻译：${readiness?.source_rows || 0} 行，预计 ${readiness?.estimated_batches || '-'} 批。`)
    try {
      const batchSize = selectedBatchSize
      const resumableRun = latestRun?.kind === 'translation'
        && latestRun.status === 'failed'
        && latestRun.metadata?.input_artifact_id === sourceArtifact.id
        ? latestRun
        : null
      const run = resumableRun || await api<Run>('/api/runs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: current.id,
            kind: 'translation',
            language: 'en',
            input_artifact_id: sourceArtifact.id,
            term_artifact_id: termArtifact?.id || null,
            batch_size: batchSize,
            task_code: taskCode
          })
        })
      setLatestRun(run)
      if (resumableRun) setStatus(`继续失败翻译任务：复用已落盘批次，按 ${batchSize} 行/批续跑。`)
      const translatePromise = api<{ run: Run; artifacts: Artifact[]; quality?: Record<string, unknown>; translation_readiness?: TranslationReadiness }>(`/api/runs/${run.id}/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      })
      const poller = window.setInterval(async () => {
        try {
          const updated = await api<Run>(`/api/runs/${run.id}`)
          setLatestRun(updated)
          const latestEvent = updated.events?.[updated.events.length - 1]
          if (latestEvent?.message) setStatus(`翻译任务${updated.status === 'running' ? '运行中' : updated.status}：${latestEvent.message}`)
        } catch {
          // Keep the in-flight translation request as the source of truth.
        }
      }, 2000)
      const result = await translatePromise.finally(() => window.clearInterval(poller))
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      await refreshCurrent()
      if (tab === 'delivery') await refreshDeliverables()
      if (result.run.metadata?.reason === 'input already contains target translations; run QA instead') {
        setQaArtifact(sourceArtifact)
        setStep(8)
        setStatus('已跳过模型翻译：输入表已有目标译文，请继续运行 QA。')
      } else {
        setStatus(result.run.status === 'passed' ? 'EN 翻译和 QA 已通过，最终产物已归档。' : `翻译任务结束：${result.run.status}`)
      }
    } catch (error) {
      setStatus(`翻译失败：${errorText(error)}`)
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
          language: 'en',
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
      setStatus(artifact.duplicate ? `参考素材已存在，已复用：${artifact.label}` : `参考素材已归档：${artifact.label}`)
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
    setStatus('正在补齐缺失 EN 译文...')
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
      const result = await api<{ imported_count: number }>(`/api/projects/${current.id}/translations/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: archiveArtifact.id, language: 'en' })
      })
      await refreshCurrent()
      setStatus(`译文归档已导入：${result.imported_count} 条`)
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
      setStatus(`已有译文已登记：${artifact.label}`)
    }
  }

  async function refreshDeliverables() {
    if (!current) {
      setDeliverables([])
      return
    }
    try {
      const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${current.id}/deliverables`)
      setDeliverables(result.deliverables || [])
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
                <button key={project.id} className={`project-item ${project.id === currentId ? 'active' : ''}`} onClick={() => { setCurrentId(project.id); setView('overview') }}>
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
              />
            ) : (
              <Wizard
                project={current}
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
                translationBatchSize={translationBatchSize}
                setTranslationBatchSize={setTranslationBatchSize}
                glossaryBatches={glossaryBatches}
                glossaryCandidates={glossaryCandidates}
                qualityIssues={qualityIssues}
                selectedLangs={selectedLangs}
                setSelectedLangs={setSelectedLangs}
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
  onStartTask
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
}) {
  return (
    <>
      <div className="proj-head">
        <div>
          <h2>{project.icon ? <span className="project-icon">{project.icon}</span> : null}{project.name}</h2>
          {project.description ? <div className="desc">{project.description}</div> : null}
        </div>
        <button className="btn btn-primary" onClick={onStartTask}>🚀 启动新翻译任务</button>
      </div>
      <div className="stat-grid">
        <div className="stat-card"><div className="num">{project.stats.tasks}</div><div className="lbl">累计任务</div></div>
        <div className="stat-card"><div className="num">{project.stats.words}</div><div className="lbl">归档译文字数</div></div>
        <div className="stat-card"><div className="num">{project.stats.archived_rows || 0}</div><div className="lbl">累计归档条数</div></div>
        <div className="stat-card"><div className="num">{project.stats.glossary}</div><div className="lbl">术语表词条</div></div>
      </div>
      <div className="view-tabs">
        <button className={`view-tab ${tab === 'meta' ? 'active' : ''}`} onClick={() => setTab('meta')}>📝 元信息</button>
        <button className={`view-tab ${tab === 'glossary' ? 'active' : ''}`} onClick={() => setTab('glossary')}>📚 术语表</button>
        <button className={`view-tab ${tab === 'translation' ? 'active' : ''}`} onClick={() => setTab('translation')}>⚡ 翻译</button>
        <button className={`view-tab ${tab === 'qa' ? 'active' : ''}`} onClick={() => setTab('qa')}>🔧 校对</button>
        <button className={`view-tab ${tab === 'archive' ? 'active' : ''}`} onClick={() => setTab('archive')}>🗄️ 译文归档</button>
        <button className={`view-tab ${tab === 'delivery' ? 'active' : ''}`} onClick={() => setTab('delivery')}>📥 交付</button>
      </div>
      {tab === 'meta' ? <MetaTab project={project} intro={intro} setIntro={setIntro} busy={busy} onSaveMeta={onSaveMeta} onAnalyze={onAnalyze} onSaveHarness={onSaveHarness} /> : null}
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
          setSourceArtifact={setSourceArtifact}
          setTermArtifact={setTermArtifact}
          onUploadSource={onUploadSource}
          onTranslate={onTranslate}
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
  onSaveMeta,
  onAnalyze,
  onSaveHarness
}: {
  project: Project
  intro: string
  setIntro: (value: string) => void
  busy: boolean
  onSaveMeta: (updates: Partial<Project>) => Promise<void>
  onAnalyze: () => void
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
}) {
  const [name, setName] = useState(project.name)
  const [type, setType] = useState(project.type || '')
  const [description, setDescription] = useState(project.description || '')
  const [promptDraft, setPromptDraft] = useState(project.prompt_text || '')
  const [editingPrompt, setEditingPrompt] = useState(false)

  useEffect(() => {
    setName(project.name)
    setType(project.type || '')
    setDescription(project.description || '')
    setPromptDraft(project.prompt_text || '')
    setEditingPrompt(false)
  }, [project.id, project.name, project.type, project.description, project.prompt_text])

  async function submit() {
    await onSaveMeta({ name: name.trim() || project.name, type, description })
    setIntro(description)
  }

  async function savePrompt() {
    await onSaveMeta({ prompt_text: promptDraft })
    setEditingPrompt(false)
  }

  async function copyPrompt() {
    await navigator.clipboard.writeText(project.prompt_text || '')
  }

  return (
    <>
      <div className="card reference-card">
        <div className="card-title">
          <div className="left">🤖 AI 生成的专属翻译提示词</div>
          <div className="card-actions">
            <button className="btn btn-ghost btn-sm" disabled={!project.prompt_text} onClick={copyPrompt}>📋 复制</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditingPrompt((value) => !value)}>✏️ 编辑</button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onAnalyze}>🔄 重新生成</button>
          </div>
        </div>
        {editingPrompt ? (
          <>
            <textarea className="prompt-editor" value={promptDraft} onChange={(event) => setPromptDraft(event.target.value)} placeholder="输入当前项目专属翻译提示词" />
            <div className="row-actions align-right">
              <button className="btn btn-ghost btn-sm" onClick={() => { setPromptDraft(project.prompt_text || ''); setEditingPrompt(false) }}>取消</button>
              <button className="btn btn-primary btn-sm" onClick={savePrompt}>保存提示词</button>
            </div>
          </>
        ) : (
          <pre>{project.prompt_text || '尚未生成。点击“重新生成”后会自动保存到当前项目。'}</pre>
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
              <label className="wide"><span>来源标注、目标语言、风格要求、素材来源</span><textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="来源：战机英语5.18翻译需求.xlsx、战机术语表.xlsx、战机英语语言表校对.xlsx&#10;目标语言：英语 EN&#10;风格：短句准确，按钮和任务文案清晰，战机/装备/资源术语统一" /></label>
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
  onDeleteTerm
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
}) {
  const [toolsOpen, setToolsOpen] = useState(false)
  return (
    <>
      <div className="card">
        <div className="card-title">
          <div className="left">项目术语表（{project.glossary?.length || 0} 条）</div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToolsOpen((value) => !value)}>{toolsOpen ? '收起导入/导出' : '导入 / 生成 / 导出'}</button>
        </div>
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
          />
        ) : null}
        <ActionStatus status={status} busy={busy} />
        {toolsOpen && glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} /> : null}
        <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); onAddTerm(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
          <input name="term_key" placeholder="ID" />
          <input name="source" placeholder="CN" required />
          <input name="target" placeholder="EN" />
          <input name="target_alt" placeholder="EN2" />
          <input name="category" placeholder="分类" />
          <input name="note" placeholder="备注" />
          <button className="btn btn-primary btn-sm">+ 新增</button>
        </form>
        <div className="table-scroll">
          <table className="glossary-table">
            <thead><tr><th>ID</th><th>CN</th><th>EN</th><th>EN2</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
            <tbody>
              {(project.glossary || []).map((row) => (
                <GlossaryTermRow key={row.id} row={row} onUpdateTerm={onUpdateTerm} onDeleteTerm={onDeleteTerm} />
              ))}
              {!project.glossary?.length ? <tr><td colSpan={7} className="muted">暂无术语。可上传已有术语表、从语言表生成，或手工新增。</td></tr> : null}
            </tbody>
          </table>
        </div>
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
  onGlossaryExtract
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
}) {
  return (
    <div className="glossary-tools-panel">
      <div className="action-card">
        <AssetSelect label="使用已有术语资产" project={project} role={['glossary_source', 'glossary_curated']} value={termArtifact} onChange={setTermArtifact} allowEmpty />
        <FileBox label="上传术语表 xlsx/csv/json" onFile={onUploadTerm} />
        <div className="row-actions">
          <button type="button" className="btn btn-ghost" disabled={!termArtifact || busy} onClick={onGlossaryPreview}>预览导入</button>
          <button type="button" className="btn btn-primary" disabled={!termArtifact || busy} onClick={onGlossaryImport}>导入到项目术语</button>
          <button type="button" className="btn btn-ghost" disabled={!sourceArtifact || busy} onClick={onGlossaryExtract}>从语言表生成</button>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx`}>导出 XLSX</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=csv`}>导出 CSV</a>
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=json`}>导出 JSON</a>
        </div>
        {!sourceArtifact ? <div className="warn-line">需要从语言表生成术语时，先在“翻译”页上传待翻译表。</div> : null}
      </div>
    </div>
  )
}

function GlossaryTermRow({
  row,
  onUpdateTerm,
  onDeleteTerm
}: {
  row: GlossaryTerm
  onUpdateTerm: (term: GlossaryTerm, updates: Partial<GlossaryTerm>) => Promise<void>
  onDeleteTerm: (term: GlossaryTerm) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    term_key: row.term_key || '',
    source: row.source || '',
    target: row.target || '',
    target_alt: row.target_alt || '',
    category: row.category || '',
    note: normalizeGlossaryNote(row.note)
  })

  useEffect(() => {
    setDraft({
      term_key: row.term_key || '',
      source: row.source || '',
      target: row.target || '',
      target_alt: row.target_alt || '',
      category: row.category || '',
      note: normalizeGlossaryNote(row.note)
    })
    setEditing(false)
  }, [row.id, row.term_key, row.source, row.target, row.target_alt, row.category, row.note])

  async function save() {
    await onUpdateTerm(row, draft)
    setEditing(false)
  }

  async function remove() {
    await onDeleteTerm(row)
  }

  function cell(key: keyof typeof draft) {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  return (
    <tr>
      <td>{cell('term_key')}</td>
      <td>{cell('source')}</td>
      <td>{cell('target')}</td>
      <td>{cell('target_alt')}</td>
      <td>{cell('category')}</td>
      <td>{cell('note')}</td>
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
  onDeleteTranslation
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
}) {
  const [toolsOpen, setToolsOpen] = useState(false)
  const entries = project.translations || []
  return (
    <div className="card">
      <div className="card-title">
        <div className="left">项目译文归档（{entries.length} 条）</div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setToolsOpen((value) => !value)}>{toolsOpen ? '收起导入/导出' : '导入 / 导出'}</button>
      </div>
      {toolsOpen ? (
        <div className="glossary-tools-panel">
          <div className="action-card">
            <AssetSelect label="使用已有译文资产" project={project} role={['translation_workbook', 'language_source']} value={archiveArtifact} onChange={setArchiveArtifact} allowEmpty />
            <FileBox label="上传译文 workbook/csv/json" onFile={onUploadArchive} />
            <div className="row-actions">
              <button type="button" className="btn btn-primary" disabled={!archiveArtifact || busy} onClick={onImportArchive}>导入到项目译文归档</button>
              <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=xlsx`}>导出 XLSX</a>
              <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=csv`}>导出 CSV</a>
              <a className="btn btn-ghost" href={`/api/projects/${project.id}/translations/export?format=json`}>导出 JSON</a>
            </div>
          </div>
        </div>
      ) : null}
      <ActionStatus status={status} busy={busy} />
      <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); onAddTranslation(new FormData(event.currentTarget)); event.currentTarget.reset() }}>
        <input name="entry_key" placeholder="ID" />
        <input name="source" placeholder="CN" required />
        <input name="target" placeholder="EN" />
        <input name="target_alt" placeholder="EN2" />
        <input name="note" placeholder="备注" />
        <button className="btn btn-primary btn-sm">+ 新增</button>
      </form>
      <div className="table-scroll">
        <table className="glossary-table translation-archive-table">
          <thead><tr><th>ID</th><th>CN</th><th>EN</th><th>EN2</th><th>备注</th><th>操作</th></tr></thead>
          <tbody>
            {entries.map((entry) => (
              <TranslationEntryRow key={entry.id} entry={entry} onUpdate={onUpdateTranslation} onDelete={onDeleteTranslation} />
            ))}
            {!entries.length ? <tr><td colSpan={6} className="muted">暂无译文归档。QA 通过后会自动写入，也可以从已有译文表导入。</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TranslationEntryRow({
  entry,
  onUpdate,
  onDelete
}: {
  entry: TranslationEntry
  onUpdate: (entry: TranslationEntry, updates: Partial<TranslationEntry>) => Promise<void>
  onDelete: (entry: TranslationEntry) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    entry_key: entry.entry_key || '',
    source: entry.source || '',
    target: entry.target || '',
    target_alt: entry.target_alt || '',
    note: entry.note || ''
  })

  useEffect(() => {
    setDraft({
      entry_key: entry.entry_key || '',
      source: entry.source || '',
      target: entry.target || '',
      target_alt: entry.target_alt || '',
      note: entry.note || ''
    })
    setEditing(false)
  }, [entry.id, entry.entry_key, entry.source, entry.target, entry.target_alt, entry.note])

  async function save() {
    await onUpdate(entry, draft)
    setEditing(false)
  }

  function cell(key: keyof typeof draft) {
    if (!editing) return <span className="readonly-cell">{draft[key] || '-'}</span>
    return <input className="cell-input" value={draft[key]} onChange={(event) => setDraft((value) => ({ ...value, [key]: event.target.value }))} />
  }

  return (
    <tr>
      <td>{cell('entry_key')}</td>
      <td>{cell('source')}</td>
      <td>{cell('target')}</td>
      <td>{cell('target_alt')}</td>
      <td>{cell('note')}</td>
      <td>
        <div className="table-actions">
          {editing ? (
            <>
              <button type="button" className="btn btn-primary btn-sm" onClick={save}>保存</button>
              <button type="button" className="btn btn-sm btn-danger" onClick={() => onDelete(entry)}>删除</button>
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
  setSourceArtifact,
  setTermArtifact,
  onUploadSource,
  onTranslate
}: {
  project: Project
  settings: AppSettings | null
  busy: boolean
  status: string
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  latestRun: Run | null
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  onUploadSource: (file: File) => void
  onTranslate: () => void
}) {
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project)
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  return (
    <>
      <div className="card">
        <div className="card-title"><div className="left">翻译任务</div></div>
        <div className="action-card">
          <AssetSelect label="待翻译语言表" project={project} role="language_source" value={sourceArtifact} onChange={setSourceArtifact} allowEmpty />
          <FileBox label="上传待翻译 workbook" onFile={onUploadSource} />
          <button className="btn btn-primary" data-testid="formal-translate" disabled={busy || Boolean(blockReason)} onClick={onTranslate}>开始正式翻译</button>
          {blockReason ? <div className="warn-line">{blockReason}</div> : null}
          <ActionStatus status={status} busy={busy} />
        </div>
        <SelectedInput label="语言表" artifact={sourceArtifact} />
        <div className="workflow-note-grid">
          <div><strong>提示词</strong><span>{project.prompt_text ? '已在元信息页生成' : '未生成'}</span></div>
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
                {finalFile?.download_url ? <a className="btn btn-ghost btn-sm" href={finalFile.download_url}>下载最终表</a> : <span className="muted-inline">最终表未生成</span>}
                {changesFile?.download_url ? <a className="btn btn-ghost btn-sm" href={changesFile.download_url}>下载修改表</a> : <span className="muted-inline">修改表未生成</span>}
              </div>
              <div className="delivery-files">
                <span>{finalFile?.filename || '-'}</span>
                <span>{changesFile?.filename || '-'}</span>
              </div>
            </div>
          )
        })}
      </div>
      <div className="muted-left">翻译和校对的基础交付一致：最终 workbook + QA 修改表。术语表在“术语表”页单独导出；元信息和提示词只在“元信息”页查看。</div>
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

function formalTranslationBlockReason(settings: AppSettings | null, sourceArtifact: Artifact | null, project?: Project): string {
  if (!sourceArtifact) return '请先上传或选择待翻译语言表。'
  if (!settings) return '模型配置尚未加载。'
  if (settings.provider === 'mock' && project?.name.startsWith('E2E ')) return ''
  if (settings.provider === 'mock') return '当前是 mock provider。真实项目禁止用 mock 假装完成，请先配置 GPT API key。'
  if ((settings.provider === 'openai' || settings.provider === 'anthropic') && !settings.api_key) return `${providerName(settings)} API key 未配置，正式翻译已阻断。`
  return ''
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
  translationBatchSize: number
  setTranslationBatchSize: (value: number) => void
  glossaryBatches: GlossaryBatch[]
  glossaryCandidates: GlossaryCandidate[]
  qualityIssues: QualityIssue[]
  settings: AppSettings | null
  status: string
  selectedLangs: string[]
  setSelectedLangs: (langs: string[]) => void
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
  assetArtifacts
}: {
  onAnalyze: () => void
  project: Project
  busy: boolean
  assetArtifacts: Artifact[]
}) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 2</span>AI 分析与专属提示词生成</div>
      <div className="panel-desc">基于文字资料、已归档素材和项目资产生成提示词、项目规则与元信息。生成后会自动保存到当前项目。当前素材：{assetArtifacts.length} 个。</div>
      <button className="btn btn-primary" disabled={busy} onClick={onAnalyze}>🤖 启动 AI 分析</button>
      <div className="ai-card"><div className="ai-header">当前提示词</div><pre>{project.prompt_text || '尚未生成'}</pre></div>
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
  busy
}: {
  project: Project
  onUploadTerm: (file: File) => void
  termArtifact: Artifact | null
  setTermArtifact: (artifact: Artifact | null) => void
  glossaryPreview: GlossaryPreviewRow[]
  onGlossaryPreview: () => void
  onGlossaryImport: () => void
  busy: boolean
}) {
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
          <a className="btn btn-ghost" href={`/api/projects/${project.id}/glossary/export?format=xlsx`}>导出术语</a>
        </div>
      </div>
      {termArtifact ? <ArtifactNote artifact={termArtifact} /> : null}
      {glossaryPreview.length ? <GlossaryPreview rows={glossaryPreview} /> : null}
    </>
  )
}

function StepSource({
  project,
  onUploadSource,
  sourceArtifact,
  setSourceArtifact
}: {
  project: Project
  onUploadSource: (file: File) => void
  sourceArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
}) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 4</span>导入待翻译内容</div>
      <div className="panel-desc">可选择已有语言表，也可上传新的 Excel 语言表；默认字段：ID | cn | en。</div>
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
  onTranslateMissingCandidates
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
}) {
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
      <div className="panel-desc">先扫描语言表中的高频中文词；缺少 EN 的候选需要显式补译或人工填写，审核加入后才进入项目术语库。</div>
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
                <span>{activeBatch ? `批次：${activeBatch.label}` : '暂无扫描批次'}。空 EN 不能加入；可先补译或手工编辑，再加入项目术语库。</span>
              </div>
              <div className="confirm-actions">
                <button className="btn btn-ghost btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'reject')}>全部跳过</button>
                <button className="btn btn-primary btn-sm" disabled={!activeBatch || !readyCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, readyCandidates, 'accept')}>全部加入已完成项</button>
              </div>
            </div>
            {reviewPreview.length ? (
              <div className="table-scroll">
                <table className="pending-term-table">
                  <thead><tr><th>状态</th><th>ID</th><th>CN</th><th>EN</th><th>EN2</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
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
      <div className="panel-desc">先从语言表筛选高频中文词，再和项目术语库按中文去重；已存在词条直接跳过，不自动补 EN/EN2。新增候选需人工确认译文后才会加入项目术语库。</div>
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
                <span>{activeBatch ? `批次：${activeBatch.label}` : '暂无扫描批次'}。这些词条尚未进入项目术语库；可先编辑 EN / EN2 / 分类 / 备注，再单条加入或跳过。</span>
              </div>
              <div className="confirm-actions">
                <button className="btn btn-ghost btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'reject')}>全部跳过</button>
                <button className="btn btn-primary btn-sm" disabled={!activeBatch || !pendingCandidates.length || busy} onClick={() => activeBatch && onResolveCandidates(activeBatch.id, pendingCandidates, 'accept')}>全部加入术语库</button>
              </div>
            </div>
            {reviewPreview.length ? (
              <div className="table-scroll">
                <table className="pending-term-table">
                  <thead><tr><th>类型</th><th>ID</th><th>CN</th><th>EN</th><th>EN2</th><th>分类</th><th>备注</th><th>操作</th></tr></thead>
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

function StepLang({ selectedLangs, setSelectedLangs }: { selectedLangs: string[]; setSelectedLangs: (langs: string[]) => void }) {
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 6</span>选择目标语言</div>
      <div className="panel-desc">v1 只有英语进入真实翻译闭环；其他语言保留配置入口。</div>
      <div className="lang-grid">
        {langOptions.map((lang) => (
          <button key={lang} className={`lang-chip ${selectedLangs.includes(lang) ? 'selected' : ''} ${lang.includes('EN') ? '' : 'disabled'}`} onClick={() => {
            if (lang.includes('EN')) setSelectedLangs(selectedLangs.includes(lang) ? [] : [lang])
          }}>{lang}</button>
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
  busy,
  latestRun,
  translationReadiness,
  translationBatchSize,
  setTranslationBatchSize,
  sourceArtifact,
  termArtifact,
  setSourceArtifact,
  setTermArtifact,
  setQaArtifact,
  setStep
}: {
  project: Project
  settings: AppSettings | null
  status: string
  onTranslate: () => void
  busy: boolean
  latestRun: Run | null
  translationReadiness: TranslationReadiness | null
  translationBatchSize: number
  setTranslationBatchSize: (value: number) => void
  sourceArtifact: Artifact | null
  termArtifact: Artifact | null
  setSourceArtifact: (artifact: Artifact | null) => void
  setTermArtifact: (artifact: Artifact | null) => void
  setQaArtifact: (artifact: Artifact | null) => void
  setStep: (step: number) => void
}) {
  const blockReason = formalTranslationBlockReason(settings, sourceArtifact, project)
  const glossaryCount = project.glossary?.length ?? project.stats.glossary ?? 0
  const batchSize = clampBatchSize(translationBatchSize)
  const readiness = sourceArtifact && translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === batchSize ? translationReadiness : null
  const alreadyTranslated = canSkipModelTranslation(readiness)
  const estimatedBatches = estimateBatches(readiness?.source_rows, batchSize)
  const progress = getTranslationProgress(latestRun)
  const resumable = Boolean(latestRun?.kind === 'translation' && latestRun.status === 'failed' && latestRun.metadata?.input_artifact_id === sourceArtifact?.id)
  const selectedBatchPreset = batchPresets.find((preset) => preset.size === batchSize)
  const readinessText = readiness
    ? `${readiness.source_rows} 行原文 / ${readiness.translated_rows} 行已有译文 / 空译文 ${readiness.empty_target_rows} / 中文残留 ${readiness.cjk_target_rows} / 预计 ${readiness.estimated_batches} 批`
    : '选择语言表后自动检查'
  const readinessState = !sourceArtifact
    ? { label: '未选择语言表', tone: 'idle' }
    : !readiness
      ? { label: '正在检查', tone: 'checking' }
      : alreadyTranslated
        ? { label: '可直接校对', tone: 'ready' }
        : { label: '需要翻译', tone: 'todo' }
  const showTranslateStatus = busy
    || Boolean(progress)
    || /翻译|provider|API|mock|workpack|批|QA/i.test(status)
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 7</span>模型翻译</div>
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
        <div className="translation-batch-panel">
          <div className="batch-control-head">
            <div>
              <strong>批处理</strong>
              <span>每批落盘、失败批次重试、可断点续跑。</span>
            </div>
            <em>当前 {batchSize} 行/批 · 预计 {estimatedBatches || '-'} 批</em>
          </div>
          <div className="batch-button-row" role="group" aria-label="批次大小">
            {batchPresets.map((preset) => (
              <button
                key={preset.key}
                type="button"
                className={`batch-size-button ${batchSize === preset.size ? 'selected' : ''}`}
                disabled={busy}
                onClick={() => setTranslationBatchSize(preset.size)}
                title={preset.desc}
              >
                <strong>{preset.label}</strong>
                <span>{preset.size} 行/批</span>
              </button>
            ))}
            <label className={`batch-custom-button ${selectedBatchPreset ? '' : 'selected'}`}>
              <span>自定义</span>
              <input
                type="number"
                min={1}
                max={200}
                value={batchSize}
                disabled={busy}
                onChange={(event) => setTranslationBatchSize(clampBatchSize(Number(event.target.value)))}
              />
            </label>
          </div>
        </div>
        <div className="translation-actions">
          {alreadyTranslated ? (
            <>
              <div className="ok-line">检测到这份表已有可校对译文，不需要重新走整表翻译；残留问题交给 QA 处理。</div>
              <button className="btn btn-primary" disabled={busy} onClick={() => { setQaArtifact(sourceArtifact); setStep(8) }}>跳到校对</button>
            </>
          ) : (
            <button className="btn btn-primary" disabled={busy || Boolean(blockReason)} onClick={onTranslate}>⚡ 开始正式翻译</button>
          )}
          {blockReason && !alreadyTranslated ? <div className="warn-line inline-warning">{blockReason}</div> : null}
        </div>
        {showTranslateStatus ? <ActionStatus status={status} busy={busy} /> : null}
        {progress ? <TranslationProgressBar progress={progress} /> : null}
      </div>
      <div className="translation-guard-strip">
        <span>项目术语库 <strong>{glossaryCount} 条</strong></span>
        <span>提示词 <strong>{project.prompt_text ? '已生成' : '未生成'}</strong></span>
        <span>校对门槛 <strong>QA 通过后交付</strong></span>
      </div>
      {latestRun && latestRun.kind === 'translation' ? <TaskRunSummary run={latestRun} /> : null}
    </>
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
  status
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
  const artifacts = (latestRun?.artifacts?.length ? latestRun.artifacts : runArtifacts(project, latestRun?.id))
    .filter((artifact) => artifact.kind === 'qa_final_workbook' || artifact.kind === 'qa_changes')
  return (
    <>
      <div className="panel-title"><span className="badge">STEP 9</span>最终交付</div>
      {latestRun ? <TaskRunSummary run={latestRun} /> : <div className="muted-left">暂无可交付任务。先完成翻译或校对。</div>}
      <div className="artifact-grid">
        {artifacts.map((artifact) => <a key={artifact.id} className="artifact" href={`/api/artifacts/${artifact.id}/download`}>{artifact.label}<span>{artifact.kind}</span></a>)}
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
                <td>{run.language?.toUpperCase() || '-'}</td>
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
  const visibleArtifacts = artifacts.filter((artifact) => downloadableArtifact([artifact], kind))
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
        <div><strong>语言</strong><span>{run.language?.toUpperCase() || '-'}</span></div>
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
          <a key={artifact.id} className="btn btn-ghost btn-sm" href={`/api/artifacts/${artifact.id}/download`}>{artifact.label}</a>
        ))}
        {!visibleArtifacts.length ? <span className="muted-left">暂无可下载交付产物。</span> : null}
      </div>
      {inputItems.length ? (
        <div className="run-inputs">
          {inputItems.map(([label, id]) => {
            const artifact = artifactById.get(String(id))
            return <span key={`${label}-${id}`}>{label}: {artifact ? artifact.label : id}</span>
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
  const type = code === 'A' ? '完整工作流' : code === 'QA' ? '校对任务' : code === 'T' ? '翻译任务' : code
  return { taskCode: code, taskType: type, taskLabel: label }
}

function inputArtifactName(project: Project, run: Run): string {
  const inputs = (run.metadata?.input_artifacts || {}) as Record<string, string>
  const artifactId = inputs.source_workbook || inputs.translation_workbook || String(run.metadata?.input_artifact_id || '')
  if (!artifactId) return ''
  return (project.artifacts || []).find((artifact) => artifact.id === artifactId)?.label || artifactId
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
      <span>{artifact ? artifact.label : '未选择'}</span>
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
  const issueText = issues.length ? `待处理问题 ${issues.length} 条` : '无待处理问题'
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
  const assets = artifactsByRoles(project, role)
  return (
    <label className="asset-select">
      <span>{label}</span>
      <select value={value?.id || ''} onChange={(event) => onChange(assets.find((artifact) => artifact.id === event.target.value) || null)}>
        {allowEmpty ? <option value="">不使用</option> : null}
        {!allowEmpty && !assets.length ? <option value="">暂无可用资产</option> : null}
        {assets.map((artifact) => (
          <option key={artifact.id} value={artifact.id}>{artifact.label} · {artifact.origin || 'generated'}</option>
        ))}
      </select>
    </label>
  )
}

function GlossaryPreview({ rows }: { rows: GlossaryPreviewRow[] }) {
  return (
    <div className="card tight">
      <div className="card-title"><div className="left">术语预览（{rows.length} 条）</div></div>
      <table>
        <thead><tr><th>ID</th><th>CN</th><th>EN</th><th>EN2</th><th>分类</th><th>备注</th></tr></thead>
        <tbody>
          {rows.slice(0, 20).map((row, index) => (
            <tr key={`${row.source}-${index}`}>
              <td>{row.term_key}</td>
              <td>{row.source}</td>
              <td>{row.target}</td>
              <td>{row.target_alt}</td>
              <td>{row.category}</td>
              <td>{row.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FileBox({ label, onFile }: { label: string; onFile: (file: File) => void }) {
  return (
    <label className="upload-box">
      <div className="icon">📄</div>
      <div className="label">{label}</div>
      <input type="file" hidden onChange={(event) => event.target.files?.[0] ? onFile(event.target.files[0]) : null} />
    </label>
  )
}

function ArtifactNote({ artifact, compact = false }: { artifact: Artifact; compact?: boolean }) {
  return <div className={`ai-card ${compact ? 'compact-note' : ''}`}><div className="ai-header">已上传：{artifact.label}</div><pre>{artifact.path}</pre></div>
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
        api_key: form.get('api_key'),
        batch_size: Number(form.get('batch_size') || 90)
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
            <input name="api_key" type="password" placeholder="完整版写入私有 settings.local.json" />
          </label>
        </div>
        <input name="batch_size" type="hidden" value={Number(settings?.batch_size || 90)} />
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
          <li>跳过：项目术语表已存在的中文不会进入候选，也不会自动补 EN/EN2。</li>
          <li>审核：新增候选必须在表格里确认 EN / EN2 / 分类 / 备注后，点加入才会进入项目术语库。</li>
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
