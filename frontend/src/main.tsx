import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { API, api, apiErrorText, sanitizeUserFacingError } from './apiClient'
import { WIDE_TABLE_PAGE_SIZE, pagedRows } from './assetTableState'
import { announcementLanguages, refreshLanguageOptions, supportedLanguages, unsupportedLanguages, languageSpec, languageChipTitle, languageQuery, normalizeLanguageCode, normalizeLanguageArray, type LanguageCode, type LanguageOption } from './languages'
import { SettingsModal } from './SettingsModal'
import { ActionStatus, ArtifactNote, AssetSelect, CheckItem, FileBox, GlossaryPreview, LanguageSelector, SelectedInput, TranslationProgressBar } from './components/shared/WorkflowPrimitives'
import { GlossaryTab, TranslationArchiveTab } from './components/assets/ProjectAssetTabs'
import { QuickTaskWizard } from './components/quickTask/QuickTaskWizard'
import { activeAnnouncementTasks, AnnouncementProjectPanel, AnnouncementWizard } from './components/announcement/AnnouncementWorkflow'
import { MetaTab } from './components/project/ProjectMeta'
import { DeliveryTab, StepQA, TranslationTab, Wizard, formalTranslationBlockReason } from './components/translationWizard/TranslationWizard'
import { artifactFileName, artifactKindLabel, artifactPickerLabel, artifactRole, artifactsByRole, artifactsByRoles, isAnnouncementSourceDocument, isGeneratedAnnouncementTermsArtifact, newestArtifact, pickerArtifacts, runArtifacts, uniqueArtifactsByContent } from './domain/artifacts'
import { compactSummary, formatDate, formatDateTime, shortRunId } from './domain/format'
import { clampBatchSize, effectiveBatchSize, estimateBatches, getTranslationProgress, canSkipModelTranslation, latestRunOfKind, findResumableTranslationRun, isTranslationRunResumable, matchesTranslationRun, translationInputMode, translationReadinessUserMessage } from './domain/translationFlow'
import { altColumnVisible, availableLookupLanguages, displayLanguagesForWideRows, fieldText, fixedTermsSummary, fixedTermsToLines, getProjectHarness, glossaryWideRowMatches, glossaryWideRows, languageFromValue, linesToFixedTerms, linesToList, linesToRules, listToLines, normalizeGlossaryNote, projectPromptForLanguage, profileText, rowRecords, ruleSummary, rulesToLines, scopeProjectToLanguage, translationWideRowMatches, translationWideRows, visibleLanguagesFromRows } from './domain/projectAssets'

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

import type { AnnouncementLookupOptions, AnnouncementLookupResult, AnnouncementTask, AnnouncementTaskResult, AnnouncementTermRow, AppSettings, Artifact, DeliverableTask, DeliveryFile, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, GlossaryTerm, HistoryKind, Project, ProjectAnalysisResponse, ProjectHarness, ProjectTab, QualityIssue, QuickObjective, Run, TranslationEntry, TranslationProgress, TranslationReadiness, TranslationTargets, WideConflict, WideGlossaryRow, WideLanguageValue, WideTranslationRow, AppView } from './types'


const CHUNKED_UPLOAD_THRESHOLD_BYTES = 768 * 1024
const UPLOAD_CHUNK_BYTES = 512 * 1024

async function uploadProjectFile(
  projectId: string,
  file: File,
  kind: string,
  purpose: string,
  onProgress: (done: number, total: number) => void
): Promise<Artifact> {
  if (file.size <= CHUNKED_UPLOAD_THRESHOLD_BYTES) {
    const data = new FormData()
    data.append('file', file)
    const query = new URLSearchParams({ kind })
    if (purpose) query.set('purpose', purpose)
    return api<Artifact>(`/api/projects/${projectId}/files?${query.toString()}`, {
      method: 'POST',
      body: data
    })
  }
  const total = Math.ceil(file.size / UPLOAD_CHUNK_BYTES)
  const uploadId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  for (let index = 0; index < total; index += 1) {
    const start = index * UPLOAD_CHUNK_BYTES
    const chunk = file.slice(start, Math.min(file.size, start + UPLOAD_CHUNK_BYTES))
    const data = new FormData()
    data.append('file', chunk, file.name)
    data.append('upload_id', uploadId)
    data.append('filename', file.name)
    data.append('kind', kind)
    data.append('purpose', purpose)
    data.append('index', String(index))
    data.append('total', String(total))
    const response = await fetch(`${API}/api/projects/${projectId}/files/chunk`, {
      method: 'POST',
      body: data
    })
    if (!response.ok) {
      const text = await response.text()
      throw new Error(apiErrorText(text, response.statusText))
    }
    const payload = await response.json() as { complete?: boolean; artifact?: Artifact; received?: number; total?: number }
    onProgress(index + 1, total)
    if (payload.complete && payload.artifact) return payload.artifact
  }
  throw new Error('分片上传已完成，但后端没有返回文件记录。')
}






















































function errorText(error: unknown): string {
  if (error instanceof Error) return apiErrorText(error.message, error.message)
  return sanitizeUserFacingError(String(error))
}

function eventStatusText(message: unknown): string {
  if (!message) return '处理中...'
  if (typeof message === 'string') return message
  if (typeof message === 'object') {
    const payload = message as Record<string, unknown>
    if (payload.passed === true) return 'QA 已完成，正在归档产物。'
    if (payload.status) return String(payload.status)
    if (payload.summary) return String(payload.summary)
  }
  return '处理中...'
}

function humanTaskStatus(status: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'queued') return '排队中'
  if (value === 'running') return '处理中'
  if (value === 'passed') return '已完成'
  if (value === 'failed') return '失败'
  if (value === 'needs_input') return '已暂停，等待继续'
  if (value === 'canceled') return '已取消'
  return status || '处理中'
}

function humanBackendEvent(message: unknown): string {
  if (!message) return '处理中...'
  if (typeof message !== 'string') return eventStatusText(message)
  const text = message.trim()
  const sanitized = sanitizeUserFacingError(text, '')
  if (sanitized && sanitized !== text) return sanitized
  if (text.startsWith('{')) {
    try {
      const payload = JSON.parse(text) as { passed?: boolean; total_cases?: number; issues?: unknown[]; issue_counts?: Record<string, unknown> }
      if (payload.passed === false) {
        const issueCount = Array.isArray(payload.issues) ? payload.issues.length : Object.values(payload.issue_counts || {}).reduce((sum: number, value) => sum + Number(value || 0), 0)
        return `QA 未通过：发现 ${issueCount || payload.total_cases || 0} 个问题，请进入校对步骤处理。`
      }
      if (payload.passed === true) return 'QA 已通过，正在整理交付文件。'
    } catch {
      // Fall through to the normal message mapping.
    }
  }
  let match = text.match(/^translating batch (\d+)\/(\d+): rows=(\d+), attempt=(\d+)\/(\d+)/i)
  if (match) return `正在翻译：第 ${match[1]}/${match[2]} 批，本批 ${match[3]} 行，第 ${match[4]} 次尝试。`
  match = text.match(/^translation preflight: source_rows=(\d+), translated_rows=(\d+), empty_target_rows=(\d+), .*estimated_batches=(\d+)/i)
  if (match) return `\u7ffb\u8bd1\u524d\u68c0\u67e5\u5b8c\u6210\uff1a${match[1]} \u884c\u6e90\u6587\uff0c\u7a7a\u8bd1\u6587 ${match[3]} \u884c\uff0c\u9884\u8ba1 ${match[4]} \u6279\u3002`
  match = text.match(/^batch (\d+)\/(\d+) completed and persisted: rows=(\d+)/i)
  if (match) return `已完成第 ${match[1]}/${match[2]} 批，已保存 ${match[3]} 行。`
  match = text.match(/^resume: batch (\d+)\/(\d+) already completed; rows=(\d+)/i)
  if (match) return `正在续跑：已跳过第 ${match[1]}/${match[2]} 批，之前已保存 ${match[3]} 行。`
  match = text.match(/^rate limit wait before batch (\d+): ([\d.]+)s/i)
  if (match) return `接口限流等待中：约 ${Math.ceil(Number(match[2]))} 秒后继续第 ${match[1]} 批。`
  if (/background translation job was interrupted/i.test(text)) return '后台翻译被中断，已保留进度，可点击继续翻译。'
  if (/translation run finished: status=failed/i.test(text)) return '翻译已完成，但 QA 未通过，需要进入校对修复。'
  if (/translation run finished: status=passed/i.test(text)) return '翻译和 QA 已通过，正在归档产物。'
  if (/running localization QA gate/i.test(text)) return '正在运行本地 QA 检查。'
  if (/applying translation response/i.test(text)) return '正在回填译文并校验格式。'
  if (/^running:\s/i.test(text)) return '正在执行本地校验流程。'
  if (/^final_workbook=/i.test(text)) return '译文已回填，正在进入 QA。'
  return eventStatusText(text)
}

function announcementActionLabel(endpoint: string): string {
  const labels: Record<string, string> = {
    'inspect-constraints': '\u7ea6\u675f\u8bc6\u522b',
    'extract-terms': '\u672f\u8bed\u63d0\u53d6',
    'import-terms': '\u672f\u8bed\u5bfc\u5165',
    'lookup-translations': '\u8bd1\u6587\u53cd\u67e5',
    prepare: '\u7ffb\u8bd1\u51c6\u5907',
    translate: 'AI \u7ffb\u8bd1',
    'translate/start': 'AI \u7ffb\u8bd1',
    'translate/resume': '\u7ee7\u7eed AI \u7ffb\u8bd1',
    'import-ai': '\u5bfc\u5165\u5916\u90e8 AI \u7ed3\u679c',
    apply: '\u6821\u5bf9\u56de\u586b',
    'fix-hard-blockers': '\u81ea\u52a8\u4fee\u590d\u95ee\u9898',
    deliver: '\u4ea4\u4ed8'
  }
  return labels[endpoint] || endpoint
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [, setLanguageVersion] = useState(0)
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
  const currentIdRef = useRef('')
  const [intro, setIntro] = useState('')
  const [sourceArtifact, setSourceArtifact] = useState<Artifact | null>(null)
  const [termArtifact, setTermArtifact] = useState<Artifact | null>(null)
  const [qaArtifact, setQaArtifact] = useState<Artifact | null>(null)
  const [archiveArtifact, setArchiveArtifact] = useState<Artifact | null>(null)
  const [assetArtifacts, setAssetArtifacts] = useState<Artifact[]>([])
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [selectedLanguage, setSelectedLanguage] = useState<LanguageCode>('en')
  const [selectedLanguages, setSelectedLanguages] = useState<LanguageCode[]>(['en'])
  const [glossaryPreview, setGlossaryPreview] = useState<GlossaryPreviewRow[]>([])
  const [glossaryBatches, setGlossaryBatches] = useState<GlossaryBatch[]>([])
  const [glossaryCandidates, setGlossaryCandidates] = useState<GlossaryCandidate[]>([])
  const [qualityIssues, setQualityIssues] = useState<QualityIssue[]>([])
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [deliverables, setDeliverables] = useState<DeliverableTask[]>([])
  const [translationReadiness, setTranslationReadiness] = useState<TranslationReadiness | null>(null)
  const [sourceInputNotice, setSourceInputNotice] = useState<TranslationReadiness | null>(null)
  const [invalidSourceArtifactIds, setInvalidSourceArtifactIds] = useState<string[]>([])
  const translationBatchSize = 90
  const [announcementText, setAnnouncementText] = useState('')
  const [announcementLookupResult, setAnnouncementLookupResult] = useState<AnnouncementLookupResult | null>(null)

  useEffect(() => {
    refreshProjects()
    refreshSettings()
    refreshLanguageOptions(API)
      .then(() => setLanguageVersion((value) => value + 1))
      .catch(() => undefined)
  }, [])

  const current = useMemo(() => projects.find((p) => p.id === currentId), [projects, currentId])
  const currentScoped = useMemo(() => current ? scopeProjectToLanguage(current, selectedLanguage) : undefined, [current, selectedLanguage])
  const currentLang = languageSpec(selectedLanguage)

  function setPrimaryLanguage(language: LanguageCode) {
    setSelectedLanguage(language)
    setSelectedLanguages((prev) => prev.includes(language) ? prev : [...prev, language])
  }

  function setPrimaryLanguages(languages: LanguageCode[], primary?: LanguageCode | null) {
    const normalized = languages.length ? languages : [primary || selectedLanguage]
    const nextPrimary = primary && normalized.includes(primary) ? primary : normalized[0]
    setSelectedLanguages(normalized)
    setSelectedLanguage(nextPrimary)
  }

  function toggleTargetLanguage(language: LanguageCode) {
    setSelectedLanguages((prev) => {
      const wasSelected = prev.includes(language)
      const next = wasSelected
        ? prev.filter((item) => item !== language)
        : [...prev, language]
      const normalized = next.length ? next : [language]
      if (wasSelected && selectedLanguage === language) setSelectedLanguage(normalized[0])
      if (!wasSelected) setSelectedLanguage(language)
      return normalized
    })
  }

  function isCurrentProject(projectId?: string | null): boolean {
    return Boolean(projectId) && currentIdRef.current === projectId
  }

  function setStatusForProject(projectId: string, message: string) {
    if (isCurrentProject(projectId)) setStatus(message)
  }

  function setBusyForProject(projectId: string, value: boolean) {
    if (isCurrentProject(projectId)) setBusy(value)
  }

  function resetProjectTransientState(message = '准备就绪') {
    setBusy(false)
    setStatus(message)
    setSourceArtifact(null)
    setTermArtifact(null)
    setQaArtifact(null)
    setArchiveArtifact(null)
    setAssetArtifacts([])
    setLatestRun(null)
    setSelectedLanguage('en')
    setSelectedLanguages(['en'])
    setGlossaryPreview([])
    setGlossaryBatches([])
    setGlossaryCandidates([])
    setQualityIssues([])
    setDeliverables([])
    setTranslationReadiness(null)
    setAnnouncementText('')
    setAnnouncementLookupResult(null)
  }

  useEffect(() => {
    currentIdRef.current = currentId
    resetProjectTransientState('准备就绪')
    return () => {
      if (deleteHoldTimer.current !== null) window.clearTimeout(deleteHoldTimer.current)
      if (announcementCancelHoldTimer.current !== null) window.clearTimeout(announcementCancelHoldTimer.current)
    }
  }, [currentId])

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
      setSelectedLanguage('en')
      setSelectedLanguages(['en'])
      setGlossaryPreview([])
      setGlossaryBatches([])
      setGlossaryCandidates([])
      setQualityIssues([])
      setDeliverables([])
      setSourceInputNotice(null)
      setInvalidSourceArtifactIds([])
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
    setSourceInputNotice(null)
    setInvalidSourceArtifactIds([])
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
    const runProjectId = latestRun.project_id
    const poller = window.setInterval(async () => {
      try {
        const updated = await api<Run>(`/api/runs/${latestRun.id}`)
        if (!isCurrentProject(runProjectId)) return
        setLatestRun(updated)
        const latestEvent = updated.events?.[updated.events.length - 1]
        if (updated.kind === 'translation' && updated.status === 'passed') {
          setStatus(`${languageSpec(normalizeLanguageCode(updated.language) || selectedLanguage).short} 翻译和 QA 已通过，最终产物已归档。`)
        } else if (latestEvent?.message) {
          setStatus(`后台任务${humanTaskStatus(updated.status)}：${humanBackendEvent(latestEvent.message)}`)
        }
        if (!['queued', 'running'].includes(updated.status)) {
          await refreshCurrent()
          if (tab === 'delivery') await refreshDeliverables()
        }
      } catch (error) {
        setStatusForProject(runProjectId, `后台任务进度刷新失败：${errorText(error)}`)
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
    if (project.id !== currentId) resetProjectTransientState()
    currentIdRef.current = project.id
    setCurrentId(project.id)
    setView('overview')
    setTab('meta')
  }

  async function deleteProject(project: Project) {
    setBusy(true)
    setStatus(`正在删除项目“${project.name}”...`)
    try {
      await api(`/api/projects/${project.id}`, { method: 'DELETE' })
      const loaded = await api<Project[]>('/api/projects')
      const nextId = loaded.some((item) => item.id === currentId) ? currentId : loaded[0]?.id || ''
      setProjects(loaded)
      currentIdRef.current = nextId
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
    const nextId = selectId || currentIdRef.current || loaded[0]?.id || ''
    setProjects(loaded)
    currentIdRef.current = nextId
    setCurrentId(nextId)
  }

  async function refreshCurrent() {
    if (!currentId) return
    const projectId = currentId
    const loaded = await api<Project>(`/api/projects/${projectId}`)
    if (!isCurrentProject(projectId)) return
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

  async function loadQualityIssues(runId: string, projectId = currentIdRef.current): Promise<QualityIssue[]> {
    try {
      const result = await api<{ issues: QualityIssue[] }>(`/api/runs/${runId}/quality-issues`)
      if (isCurrentProject(projectId)) setQualityIssues(result.issues)
      return result.issues
    } catch (error) {
      setStatusForProject(projectId, `QA 问题加载失败：${errorText(error)}`)
      return []
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

  async function upload(file: File, kind: string, purpose = '') {
    if (!current) return null
    setBusy(true)
    setStatus(`正在上传：${file.name}`)
    try {
      const artifact = await uploadProjectFile(current.id, file, kind, purpose, (done, total) => {
        if (total > 1) setStatus(`正在上传：${file.name}（分片 ${done}/${total}）`)
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
    setStatus('正在读取项目资料并调用 AI 分析...')
    try {
      const result = await api<ProjectAnalysisResponse>(`/api/projects/${current.id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          intro: intro.trim() || current.description || `${current.name} ${current.type}`,
          asset_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
          target_language: selectedLanguage
        })
      })
      await refreshCurrent()
      const summary = result.analysis?.summary || {}
      const warning = result.analysis?.warning
      setStatus(`${currentLang.short} 项目分析完成：已读取 ${summary.parsed ?? 0}/${summary.total ?? 0} 个资料${warning ? `；${warning}` : ''}`)
      const candidates = result.analysis?.language_table_candidates || []
      if (candidates.length) {
        const confirmScan = window.confirm(`识别到 ${candidates.length} 个完整语言表。是否现在扫描术语候选？候选不会直接进入项目术语库。`)
        if (confirmScan) {
          const candidate = candidates[0]
          const artifacts = result.project.artifacts || []
          const artifact = artifacts.find((item) => item.id === candidate.artifact_id) || assetArtifacts.find((item) => item.id === candidate.artifact_id) || null
          if (artifact) {
            setSourceArtifact(artifact)
            await runGlossaryExtract(artifact)
          }
        }
      }
    } catch (error) {
      setStatus(`项目分析失败：${errorText(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function runGlossaryExtract(inputArtifact?: Artifact | null) {
    const artifact = inputArtifact || sourceArtifact
    if (!current) return
    if (!artifact) {
      setStatus('请先在 STEP 4 选择或上传语言表，再扫描术语候选。')
      return
    }
    if (!sourceArtifact || sourceArtifact.id !== artifact.id) {
      setSourceArtifact(artifact)
    }
    setBusy(true)
    setStatus('正在从待翻译语言表扫描术语候选...')
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
          input_artifact_id: artifact.id,
          project_name: current.name,
          source_only: false,
          id_column: 'ID',
          source_column: 'cn',
          target_column: currentLang.targetHeader,
          language: selectedLanguage,
          project_material_artifact_ids: assetArtifacts.map((artifact) => artifact.id),
          project_notes: [intro.trim() || current.description || `${current.name} ${current.type}`].filter(Boolean),
          include_empty_final_terms: true,
          ai_candidate_supplement: true
        })
      })
      setTermArtifact(result.artifacts.find((a) => a.kind === 'glossary_final') || null)
      setLatestRun(result.run)
      await refreshCurrent()
      await refreshGlossaryBatches(current.id)
      const backfill = result.glossary_backfill || {}
      const pendingConfirmation = backfill.pending_confirmation ?? backfill.inserted ?? 0
      setStatus(`术语候选已生成：候选 ${backfill.candidates ?? 0}，按中文去重后 ${backfill.unique_candidates ?? 0}，已在库中跳过 ${backfill.skipped_existing ?? 0}，待人工确认 ${pendingConfirmation}，重复跳过 ${backfill.skipped_duplicate ?? 0}`)
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

  async function refreshTranslationReadiness(artifactId: string, projectId = currentIdRef.current, language: LanguageCode = selectedLanguage) {
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    try {
      const result = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      if (isCurrentProject(projectId)) setTranslationReadiness(result)
      return result
    } catch {
      if (isCurrentProject(projectId)) setTranslationReadiness(null)
      return null
    }
  }

  function selectSourceArtifact(artifact: Artifact | null) {
    if (!artifact) {
      setSourceArtifact(null)
      setSourceInputNotice(null)
      setTranslationReadiness(null)
      return
    }
    if (artifactRole(artifact) === 'language_source') {
      void classifySourceArtifact(artifact)
    } else {
      setSourceArtifact(artifact)
    }
  }

  function selectQaArtifact(artifact: Artifact | null) {
    setQaArtifact(artifact)
    if (artifact && artifactRole(artifact) === 'language_source') {
      void refreshTranslationReadiness(artifact.id)
    }
  }

  async function syncLanguageFromArtifact(artifact: Artifact): Promise<LanguageCode> {
    const projectId = currentIdRef.current
    const targets = await inspectTranslationTargets(artifact.id, projectId)
    if (!isCurrentProject(projectId)) return selectedLanguage
    const suggested = targets?.suggested_language
    const detected = targets?.detected_languages || []
    if (detected.length) {
      setPrimaryLanguages(detected, suggested || detected[0])
      setStatus(`已识别语言表目标语言：${detected.map((item) => languageSpec(item).short).join(' / ')}`)
      return suggested || detected[0]
    }
    if (suggested && suggested !== selectedLanguage) {
      setPrimaryLanguage(suggested)
      setStatus(`\u5df2\u8bc6\u522b\u8bed\u8a00\u8868\u76ee\u6807\u8bed\u8a00\uff1a${languageSpec(suggested).short}`)
      return suggested
    }
    return suggested || selectedLanguage
  }

  async function classifySourceArtifact(artifact: Artifact) {
    const projectId = currentIdRef.current
    const language = await syncLanguageFromArtifact(artifact)
    const readiness = await refreshTranslationReadiness(artifact.id, projectId, language)
    if (!isCurrentProject(projectId) || !readiness) return
    const mode = translationInputMode(readiness)
    if (mode === 'invalid') {
      setInvalidSourceArtifactIds((prev) => prev.includes(artifact.id) ? prev : [...prev, artifact.id])
      setSourceInputNotice(readiness)
      setTranslationReadiness(readiness)
      setSourceArtifact(null)
      setStatus(`语言表格式需要修正：${translationReadinessUserMessage(readiness)}`)
      return
    }
    setInvalidSourceArtifactIds((prev) => prev.filter((id) => id !== artifact.id))
    setSourceArtifact(artifact)
    setSourceInputNotice(null)
    if (mode === 'ready_for_qa') {
      setQaArtifact(artifact)
      setStatus(`检测到已有完整译文：${readiness.translated_rows}/${readiness.source_rows} 行，可直接进入校对。`)
    } else {
      setQaArtifact((currentQa) => currentQa && artifactRole(currentQa) === 'language_source' ? null : currentQa)
      setStatus(`检测到待翻译语言表：${readiness.source_rows} 行，下一步扫描术语候选。`)
    }
  }

  async function inspectTranslationTargets(artifactId: string, projectId = currentIdRef.current): Promise<TranslationTargets | null> {
    try {
      const result = await api<TranslationTargets>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-targets`)
      const languages = normalizeLanguageArray(result.detected_languages)
      return { ...result, detected_languages: languages, suggested_language: normalizeLanguageCode(result.suggested_language) }
    } catch (error) {
      setStatus(`语言识别失败：${errorText(error)}`)
      return null
    }
  }

  async function startQuickTask(payload: { inputArtifact: Artifact; referenceArtifacts: Artifact[]; objective: 'translate' | 'qa'; language: LanguageCode }): Promise<Run | null> {
    if (!current) return null
    const projectId = current.id
    const { inputArtifact, referenceArtifacts, objective, language } = payload
    const referenceArtifactIds = referenceArtifacts.map((artifact) => artifact.id)
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    setBusy(true)
    setStatusForProject(projectId, objective === 'qa' ? `快速校对准备中：${languageSpec(language).short}` : `快速翻译准备中：${languageSpec(language).short}`)
    try {
      const inputName = `${inputArtifact.label || ''} ${inputArtifact.path || ''}`.toLowerCase()
      if (objective === 'qa' && /\.(txt|md|markdown)(\s|$)/i.test(inputName)) {
        setStatusForProject(projectId, 'TXT 快速任务目前支持翻译并输出同格式文本；校对请上传已译语言表。')
        return null
      }
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
        if (!isCurrentProject(projectId)) return null
        const hydrated = { ...result.run, artifacts: result.artifacts }
        setLatestRun(hydrated)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        setStatusForProject(projectId, result.run.status === 'passed' ? '快速校对已通过，可在交付页生成最终文件。' : `快速校对结束：${result.run.status}`)
        return hydrated
      }

      const readiness = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${inputArtifact.id}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      if (!isCurrentProject(projectId)) return null
      if (canSkipModelTranslation(readiness)) {
        setStatusForProject(projectId, `已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文；建议切换为“校对”直接跑 QA。`)
        return null
      }
      const blockReason = formalTranslationBlockReason(settings, inputArtifact, current, readiness)
      if (blockReason) {
        setStatusForProject(projectId, `无法开始快速翻译：${blockReason}`)
        return null
      }
      const resumableRun = (current.runs || []).find((run) =>
        matchesTranslationRun(run, language, inputArtifact.id, 'quick_task')
        && isTranslationRunResumable(run)
      ) || null
      const run = resumableRun || await api<Run>('/api/runs', {
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
      if (!isCurrentProject(projectId)) return null
      setLatestRun(run)
      const endpoint = resumableRun ? 'resume' : 'start'
      const started = await api<Run>(`/api/runs/${run.id}/translate/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize })
      })
      if (!isCurrentProject(projectId)) return null
      setLatestRun(started)
      setStatusForProject(projectId, resumableRun
        ? `快速翻译已继续：${languageSpec(language).short} · 会从已保存批次接着跑。`
        : `快速翻译已进入后台：${languageSpec(language).short} · ${readiness.source_rows} 行 · 预计 ${readiness.estimated_batches || '-'} 批。`)
      return started
    } catch (error) {
      setStatusForProject(projectId, `快速任务失败：${errorText(error)}`)
      return null
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function runTranslate(taskCode: 'A' | 'T' = 'T') {
    if (!current || !sourceArtifact) return
    const projectId = current.id
    const selectedBatchSize = effectiveBatchSize(settings, translationBatchSize)
    const readiness = translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === selectedBatchSize
      ? translationReadiness
      : await refreshTranslationReadiness(sourceArtifact.id, projectId)
    if (!isCurrentProject(projectId)) return
    if (readiness && canSkipModelTranslation(readiness)) {
      setQaArtifact(sourceArtifact)
      setStep(8)
      setStatus(`已检测到 ${readiness.translated_rows}/${readiness.source_rows} 行已有译文，无需 AI 翻译，请直接运行 QA。`)
      return
    }
    const blockReason = formalTranslationBlockReason(settings, sourceArtifact, current, readiness)
    if (blockReason) {
      setStatus(`无法开始翻译：${blockReason}`)
      return
    }
    setBusy(true)
    setStatusForProject(projectId, `${currentLang.short} 翻译前检查通过，准备分批翻译：${readiness?.source_rows || 0} 行，预计 ${readiness?.estimated_batches || '-'} 批。`)
    try {
      const batchSize = selectedBatchSize
      const latestRunMatches = latestRun && matchesTranslationRun(latestRun, selectedLanguage, sourceArtifact.id, 'translation_run')
        ? latestRun
        : null
      const resumableRun = latestRunMatches && isTranslationRunResumable(latestRunMatches)
        ? latestRunMatches
        : findResumableTranslationRun(current, selectedLanguage, sourceArtifact.id, 'translation_run')
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
      if (!isCurrentProject(projectId)) return
      setLatestRun(run)
      const needsBudgetConfirm = run.metadata?.reason === 'api_budget_confirmation_required'
      const confirmedBudget = needsBudgetConfirm
        ? window.confirm('该任务预计 API token 用量超过设置的提醒阈值。确认后会从已完成批次继续，不会重跑已落盘批次。是否继续？')
        : false
      if (needsBudgetConfirm && !confirmedBudget) {
        setStatusForProject(projectId, '已暂停：等待确认 API 用量预算后继续。')
        return
      }
      const endpoint = resumableRun ? 'resume' : 'start'
      const started = await api<Run>(`/api/runs/${run.id}/translate/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize, confirm_api_budget: confirmedBudget })
      })
      if (!isCurrentProject(projectId)) return
      setLatestRun(started)
      setStatusForProject(projectId, `${currentLang.short} 翻译已进入后台队列：系统会自动拆批、限流、落盘和续跑。`)
    } catch (error) {
      setStatusForProject(projectId, `翻译失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function cancelTranslateRun() {
    if (!latestRun || latestRun.kind !== 'translation') return
    const projectId = latestRun.project_id
    setBusy(true)
    setStatus('正在取消后台翻译任务...')
    try {
      const canceled = await api<Run>(`/api/runs/${latestRun.id}/translate/cancel`, { method: 'POST' })
      if (!isCurrentProject(projectId)) return
      setLatestRun(canceled)
      setStatus('已请求取消：当前已完成批次会保留，后续可继续。')
    } catch (error) {
      setStatusForProject(projectId, `取消翻译失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function runDirectQA(taskCode: 'QA' = 'QA') {
    if (!current || !qaArtifact) return
    const projectId = current.id
    if (artifactRole(qaArtifact) === 'language_source') {
      const readiness = await refreshTranslationReadiness(qaArtifact.id, projectId)
      if (!isCurrentProject(projectId)) return
      if (!canSkipModelTranslation(readiness)) {
        setSourceArtifact(qaArtifact)
        setStep(7)
        setStatusForProject(projectId, '这份语言表还不像完整译文表：请先进入 AI 翻译补齐空译文或明显非目标语言内容，再运行 QA。')
        return
      }
    }
    const sourceRunId = qaArtifact.run_id && (current.runs || []).some((run) => run.id === qaArtifact.run_id && run.kind === 'translation')
      ? qaArtifact.run_id
      : null
    setBusy(true)
    setStatusForProject(projectId, '正在对已有译文表格执行 QA...')
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
      if (!isCurrentProject(projectId)) return
      setLatestRun({ ...run, status: 'running', artifacts: [] })
      setQualityIssues([])
      setStatusForProject(projectId, 'QA 正在运行：正在检查变量、标签、术语、中文残留和格式问题...')
      const result = await api<{ run: Run; artifacts: Artifact[]; quality_summary?: Record<string, unknown> }>(`/api/runs/${run.id}/qa`, {
        method: 'POST'
      })
      if (!isCurrentProject(projectId)) return
      setLatestRun({ ...result.run, artifacts: result.artifacts })
      const issues = result.run.status === 'passed' ? [] : await loadQualityIssues(result.run.id, projectId)
      await refreshCurrent()
      if (tab === 'delivery') await refreshDeliverables()
      const hardCount = Number(result.quality_summary?.hard_errors || 0) || issues.filter((issue) => issue.severity === 'hard').length
      setStatusForProject(projectId, result.run.status === 'passed'
        ? '已有译文 QA 通过，可进入交付。'
        : `QA 未完全通过：还有 ${hardCount || '若干'} 个问题；已生成可交付文件，可先修复，也可进入交付。`)
    } catch (error) {
      setStatusForProject(projectId, `已有译文 QA 失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function applyManualFixes(fixes: { issue_id?: string; sheet: string; row: number; translation: string; note?: string }[]) {
    if (!current || !latestRun || !fixes.length) return
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, '正在保存手工修复并重新 QA...')
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
      if (!isCurrentProject(projectId)) return
      if (result.qa_result) {
        setLatestRun({ ...result.qa_result.run, artifacts: result.qa_result.artifacts })
        setQualityIssues([])
        setStatusForProject(projectId, `手工修复已重新 QA：${result.qa_result.run.status}`)
      } else {
        setQaArtifact(result.fixed_artifact)
        setStatusForProject(projectId, '手工修复已保存，等待重新 QA')
      }
      await refreshCurrent()
    } catch (error) {
      setStatusForProject(projectId, `手工修复失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function applyModelFixes() {
    if (!current || !latestRun) return
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, '模型修复正在运行：系统会先批量修复可定位问题，再自动重跑 QA...')
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
      if (!isCurrentProject(projectId)) return
      if (result.qa_result) {
        setLatestRun({ ...result.qa_result.run, artifacts: result.qa_result.artifacts })
        const issues = result.qa_result.run.status === 'passed' ? [] : await loadQualityIssues(result.qa_result.run.id, projectId)
        if (result.qa_result.run.status === 'passed') setQualityIssues([])
        const hardCount = Number(result.qa_result.quality_summary?.hard_errors || 0) || issues.filter((issue) => issue.severity === 'hard').length
        setStatusForProject(projectId, result.qa_result.run.status === 'passed'
          ? `模型已修复 ${result.model_fixes.length} 条，重跑 QA 已通过，可进入交付。`
          : `模型已修复 ${result.model_fixes.length} 条，但 QA 仍有 ${hardCount || '若干'} 个问题；已生成可交付文件，可继续修或进入交付。`)
      } else {
        setQaArtifact(result.fixed_artifact)
        setStatusForProject(projectId, `模型已修复 ${result.model_fixes.length} 条，等待重新 QA`)
      }
      await refreshCurrent()
    } catch (error) {
      setStatusForProject(projectId, `模型修复失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
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

  async function uploadProjectMaterial(file: File) {
    const artifact = await upload(file, 'asset', 'project_material')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `参考素材已存在，已复用：${artifactPickerLabel(artifact)}` : `参考素材已归档：${artifactPickerLabel(artifact)}`)
    }
    return artifact
  }

  async function uploadSourceWorkbook(file: File) {
    const artifact = await upload(file, 'language_table')
    if (artifact) await classifySourceArtifact(artifact)
    return artifact
  }

  async function uploadAnnouncementResponse(file: File) {
    const artifact = await upload(file, 'asset')
    if (artifact) {
      setAssetArtifacts((prev) => uniqueArtifactsByContent([artifact, ...prev.filter((item) => item.id !== artifact.id)]))
      setStatus(artifact.duplicate ? `外部 AI 结果已存在，已复用：${artifactPickerLabel(artifact)}` : `外部 AI 结果已上传：${artifactPickerLabel(artifact)}`)
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
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, '正在创建公告任务...')
    try {
      const task = await api<AnnouncementTask>(`/api/projects/${projectId}/announcement-tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!isCurrentProject(projectId)) return null
      await refreshCurrent()
      setStatusForProject(projectId, `公告任务已创建：${task.title || task.id}`)
      return task
    } catch (error) {
      setStatusForProject(projectId, `公告任务创建失败：${errorText(error)}`)
      return null
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function runAnnouncementTaskAction(taskId: string, endpoint: string, payload: Record<string, unknown> = {}) {
    if (!current) return null
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, `\u6b63\u5728\u6267\u884c\u516c\u544a\u4efb\u52a1\uff1a${announcementActionLabel(endpoint)}...`)
    try {
      const result = await api<AnnouncementTaskResult>(`/api/announcement-tasks/${taskId}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!isCurrentProject(projectId)) return null
      if (result.run) setLatestRun({ ...result.run, artifacts: result.artifacts || [] })
      await refreshCurrent()
      const summary = result.summary ? `\uff1a${compactSummary(result.summary)}` : ''
      const taskStatus = String(result.task?.status || '')
      if (endpoint.startsWith('translate/') && ['queued', 'running'].includes(taskStatus)) {
        setStatusForProject(projectId, `\u516c\u544a\u540e\u53f0\u7ffb\u8bd1\u5df2\u542f\u52a8\uff1a${announcementActionLabel(endpoint)}${summary}`)
      } else {
        setStatusForProject(projectId, `\u516c\u544a\u6b65\u9aa4\u5df2\u5b8c\u6210\uff1a${announcementActionLabel(endpoint)}${summary}`)
      }
      return result
    } catch (error) {
      setStatusForProject(projectId, `公告任务失败：${errorText(error)}`)
      return null
    } finally {
      setBusyForProject(projectId, false)
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
    return artifact
  }

  async function importTranslationArchive(artifactOverride?: Artifact | null): Promise<boolean> {
    const targetArtifact = artifactOverride || archiveArtifact
    if (!current || !targetArtifact) return false
    setBusy(true)
    setStatus('正在导入译文归档...')
    try {
      const result = await api<{ imported_count: number; languages?: LanguageCode[] }>(`/api/projects/${current.id}/translations/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: targetArtifact.id, auto_languages: true, language: selectedLanguage })
      })
      await refreshCurrent()
      const languageText = result.languages?.length ? `（${result.languages.map((item) => languageSpec(item).short).join('/')}）` : ''
      setStatus(`译文归档已导入：${result.imported_count} 条${languageText}`)
      return true
    } catch (error) {
      setStatus(`译文归档导入失败：${errorText(error)}`)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function skipQAArchive(artifactOverride?: Artifact | null) {
    const targetArtifact = artifactOverride || qaArtifact
    if (!current || !targetArtifact) {
      setStatus('请选择已有译文语言表后再跳过 QA。')
      return
    }
    const imported = await importTranslationArchive(targetArtifact)
    if (imported) {
      setStatus('已跳过 QA 并导入译文归档；建议后续补跑 QA。')
      await refreshCurrent()
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
                  <span className="pmeta">语言包 {project.stats.language_tasks ?? ((project.stats.translation_runs || 0) + (project.stats.qa_runs || 0))} · 公告 {visibleAnnouncementTaskCount(project)} · 归档 {project.stats.archived_rows || 0}</span>
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
                assetArtifacts={assetArtifacts}
                setSourceArtifact={selectSourceArtifact}
                setTermArtifact={setTermArtifact}
                setQaArtifact={selectQaArtifact}
                setArchiveArtifact={setArchiveArtifact}
                onSaveMeta={saveProjectMeta}
                onAnalyze={runAnalysis}
                onUploadSource={uploadSourceWorkbook}
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
                onUploadMaterial={uploadProjectMaterial}
                onTranslate={() => runTranslate('T')}
                onDirectQA={() => runDirectQA('QA')}
                onSkipQAArchive={skipQAArchive}
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
                setSelectedLanguage={setPrimaryLanguage}
                selectedLanguages={selectedLanguages}
                toggleSelectedLanguage={toggleTargetLanguage}
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
                sourceInputNotice={sourceInputNotice}
                invalidSourceArtifactIds={invalidSourceArtifactIds}
                glossaryBatches={glossaryBatches}
                glossaryCandidates={glossaryCandidates}
                qualityIssues={qualityIssues}
                selectedLanguage={selectedLanguage}
                setSelectedLanguage={setPrimaryLanguage}
                selectedLanguages={selectedLanguages}
                toggleSelectedLanguage={toggleTargetLanguage}
                setSourceArtifact={selectSourceArtifact}
                setTermArtifact={setTermArtifact}
                setQaArtifact={selectQaArtifact}
                glossaryPreview={glossaryPreview}
                settings={settings}
                status={status}
                onBack={() => setView('overview')}
                onUploadSource={uploadSourceWorkbook}
                onUploadTerm={async (file) => setTermArtifact(await upload(file, 'term_base'))}
                onUploadAsset={uploadProjectMaterial}
                onAnalyze={runAnalysis}
                onGlossaryExtract={runGlossaryExtract}
                onGlossaryPreview={previewGlossaryImport}
                onGlossaryImport={importGlossaryArtifact}
                onTranslate={() => runTranslate('A')}
                onCancelTranslate={cancelTranslateRun}
                onDirectQA={() => runDirectQA('QA')}
                onSkipQAArchive={skipQAArchive}
                allowSkipQAArchive
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

function visibleAnnouncementTaskCount(project: Project): number {
  return project.announcement_tasks ? activeAnnouncementTasks(project.announcement_tasks).length : (project.stats.announcement_tasks || 0)
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
  assetArtifacts,
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
  onUploadMaterial,
  onTranslate,
  onDirectQA,
  onSkipQAArchive,
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
  setSelectedLanguage,
  selectedLanguages,
  toggleSelectedLanguage
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
  assetArtifacts: Artifact[]
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
  onUploadArchive: (file: File) => Promise<Artifact | null>
  onImportArchive: (artifact?: Artifact | null) => Promise<boolean>
  onSaveHarness: (updates: Partial<ProjectHarness>) => Promise<void>
  onUploadMaterial: (file: File) => Promise<Artifact | null>
  onTranslate: () => void
  onDirectQA: () => void
  onSkipQAArchive: (artifact?: Artifact | null) => void
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
  selectedLanguages: LanguageCode[]
  toggleSelectedLanguage: (language: LanguageCode) => void
}) {
  const glossaryRows = glossaryWideRows(project)
  const archiveRows = translationWideRows(project)
  const languageTaskCount = project.stats.language_tasks ?? ((project.stats.translation_runs || 0) + (project.stats.qa_runs || 0))
  const announcementTaskCount = visibleAnnouncementTaskCount(project)
  const fallbackDeliverableCount = (project.runs || []).filter((run) =>
    ['translation', 'qa'].includes(run.kind)
    && run.status === 'passed'
    && (project.artifacts || []).some((artifact) => artifact.run_id === run.id && artifact.kind === 'qa_final_workbook')
  ).length
  const deliverableCount = project.stats.deliverables ?? fallbackDeliverableCount
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
        <button type="button" className="stat-card stat-action" onClick={() => setTab('translation')} title="进入语言包翻译任务">
          <div className="num">{languageTaskCount}</div><div className="lbl">语言包任务</div><div className="stat-hint">进入翻译</div>
        </button>
        <button type="button" className="stat-card stat-action" onClick={onStartAnnouncement} title="进入公告翻译任务">
          <div className="num">{announcementTaskCount}</div><div className="lbl">公告任务</div><div className="stat-hint">进入公告</div>
        </button>
        <button type="button" className="stat-card stat-action" onClick={() => setTab('delivery')} title="查看可交付文件">
          <div className="num">{deliverableCount}</div><div className="lbl">可交付</div><div className="stat-hint">查看下载</div>
        </button>
        <button type="button" className="stat-card stat-action" onClick={() => setTab('archive')} title="查看译文归档">
          <div className="num">{archiveRows.length}</div><div className="lbl">已归档文本</div><div className="stat-hint">查看归档</div>
        </button>
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
      {tab === 'meta' ? (
        <MetaTab
          project={project}
          intro={intro}
          setIntro={setIntro}
          busy={busy}
          selectedLanguage={selectedLanguage}
          onSaveMeta={onSaveMeta}
          onAnalyze={onAnalyze}
          onSaveHarness={onSaveHarness}
          assetArtifacts={assetArtifacts}
          onUploadMaterial={onUploadMaterial}
        />
      ) : null}
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
          onSkipQAArchive={onSkipQAArchive}
          onManualFixes={onManualFixes}
          onModelFixes={onModelFixes}
          onUploadTranslation={onUploadTranslation}
          busy={busy}
          status={status}
          selectedLanguage={selectedLanguage}
          setSelectedLanguage={setSelectedLanguage}
          selectedLanguages={selectedLanguages}
          toggleSelectedLanguage={toggleSelectedLanguage}
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
          onGoQA={() => setTab('qa')}
        />
      ) : null}
      {tab === 'delivery' ? (
        <DeliveryTab
          project={project}
          deliverables={deliverables}
          busy={busy}
          status={status}
          onCreateDelivery={onCreateDelivery}
          onGoTranslate={() => setTab('translation')}
          onGoQA={() => setTab('qa')}
          onGoArchive={() => setTab('archive')}
        />
      ) : null}
    </>
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

function NewProjectModal({ onClose, onCreate }: { onClose: () => void; onCreate: (form: FormData) => Promise<void> }) {
  const [typeMode, setTypeMode] = useState('科幻 SLG')
  const [customType, setCustomType] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await onCreate(new FormData(event.currentTarget))
    } catch (err) {
      setError(`创建失败：${errorText(err)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask show">
      <form className="modal" onSubmit={submit}>
        <h3>🆕 新建本地化项目</h3>
        <p>填写基本信息即可创建，后续可在项目里完善提示词和术语表。</p>
        <label className="field-label">项目名称</label>
        <input name="name" placeholder="例如：星际边境 / 机甲纪元" required disabled={busy} />
        <label className="field-label">项目类型</label>
        <select value={typeMode} disabled={busy} onChange={(event) => setTypeMode(event.target.value)}>
          <option>科幻 SLG</option>
          <option>女性向恋爱</option>
          <option>休闲合成</option>
          <option>武侠 RPG</option>
          <option>其他</option>
        </select>
        {typeMode === '其他' ? (
          <input key="custom-type" name="type" value={customType} onChange={(event) => setCustomType(event.target.value)} placeholder="手动填写项目类型 / 标签" required autoFocus disabled={busy} />
        ) : (
          <input key="preset-type" name="type" type="hidden" value={typeMode} />
        )}
        <label className="field-label">图标</label>
        <input name="icon" placeholder="🎮" disabled={busy} />
        <label className="field-label">描述</label>
        <input name="description" placeholder="目标用户、题材、语气要求" disabled={busy} />
        {error ? <div className="inline-status error" data-testid="new-project-error">{error}</div> : null}
        <div className="modal-foot"><button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>取消</button><button className="btn btn-primary" disabled={busy}>{busy ? '创建中...' : '创建'}</button></div>
      </form>
    </div>
  )
}

function FrequencyModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="modal-mask show">
      <div className="modal">
        <h3>💡 高频词补充策略</h3>
        <p>系统会从完整语言表中提取高频、易混淆和需要统一维护的中文术语，生成候选批次、项目说明和翻译提示词。</p>
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
