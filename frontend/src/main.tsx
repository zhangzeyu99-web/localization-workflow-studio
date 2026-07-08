import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { API, api } from './apiClient'
import { WIDE_TABLE_PAGE_SIZE, pagedRows } from './assetTableState'
import { announcementLanguages, refreshLanguageOptions, supportedLanguages, unsupportedLanguages, languageSpec, languageChipTitle, languageQuery, normalizeLanguageCode, normalizeLanguageArray, type LanguageCode, type LanguageOption } from './languages'
import { SettingsModal } from './SettingsModal'
import { useConfirmDialog } from './components/modals/ConfirmModal'
import { ActionStatus, ArtifactNote, AssetSelect, CheckItem, FileBox, GlossaryPreview, LanguageSelector, SelectedInput, TranslationProgressBar } from './components/shared/WorkflowPrimitives'
import { QuickTaskWizard } from './components/quickTask/QuickTaskWizard'
import { AnnouncementWizard } from './components/announcement/AnnouncementWorkflow'
import { Wizard, formalTranslationBlockReason } from './components/translationWizard/TranslationWizard'
import { DeleteProjectModal } from './components/modals/DeleteProjectModal'
import { CancelAnnouncementTaskModal } from './components/modals/CancelAnnouncementTaskModal'
import { NewProjectModal } from './components/modals/NewProjectModal'
import { FrequencyModal } from './components/modals/FrequencyModal'
import { EmptyState } from './components/project/EmptyState'
import { ProjectOverview } from './components/project/ProjectOverview'
import { useProjectListPolling } from './hooks/useProjectListPolling'
import { useProjectSnapshotPolling } from './hooks/useProjectSnapshotPolling'
import { useRunStatusPolling } from './hooks/useRunStatusPolling'
import { useAnnouncementTaskPolling } from './hooks/useAnnouncementTaskPolling'
import { artifactFileName, artifactKindLabel, artifactPickerLabel, artifactRole, artifactsByRole, artifactsByRoles, isAnnouncementSourceDocument, isGeneratedAnnouncementTermsArtifact, newestArtifact, pickerArtifacts, runArtifacts, uniqueArtifactsByContent } from './domain/artifacts'
import { uploadProjectFile } from './domain/projectApi'
import { mergeProjectListSummaries, preferredTranslationResultArtifact } from './domain/projectState'
import { projectActiveTaskCount, projectRunStatusText, projectTranslationPassedStatusText, visibleAnnouncementTaskCount } from './domain/projectActivity'
import { announcementActionLabel, announcementActionSummary, errorText } from './appText'
import { formatDate, formatDateTime, shortRunId } from './domain/format'
import { issueCountPhrase, runStatusLabel } from './uiText'
import { clampBatchSize, effectiveBatchSize, estimateBatches, canSkipModelTranslation, latestRunOfKind, findResumableTranslationRun, isTranslationRunResumable, matchesTranslationRun, translationInputMode, translationReadinessUserMessage } from './domain/translationFlow'
import { altColumnVisible, availableLookupLanguages, displayLanguagesForWideRows, fieldText, fixedTermsSummary, fixedTermsToLines, getProjectHarness, glossaryWideRowMatches, languageFromValue, linesToFixedTerms, linesToList, linesToRules, listToLines, normalizeGlossaryNote, projectPromptForLanguage, profileText, rowRecords, ruleSummary, rulesToLines, scopeProjectToLanguage, translationWideRowMatches, visibleLanguagesFromRows } from './domain/projectAssets'

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

import type { AnnouncementLookupOptions, AnnouncementLookupResult, AnnouncementTask, AnnouncementTaskResult, AnnouncementTermRow, AppRuntimeVersion, AppSettings, Artifact, DeliverableTask, DeliveryFile, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, GlossaryTerm, HistoryKind, MultilingualQueueStatus, Project, ProjectAnalysisResponse, ProjectHarness, ProjectTab, QualityIssue, QuickObjective, Run, TranslationEntry, TranslationProgress, TranslationReadiness, TranslationTargets, WideConflict, WideGlossaryRow, WideLanguageValue, WideTranslationRow, AppView } from './types'


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
  const [runtimeVersion, setRuntimeVersion] = useState<AppRuntimeVersion | null>(null)
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
  const [generatedDelivery, setGeneratedDelivery] = useState<{ projectId: string; runId: string; files: DeliveryFile[] } | null>(null)
  const [translationReadiness, setTranslationReadiness] = useState<TranslationReadiness | null>(null)
  const [sourceInputNotice, setSourceInputNotice] = useState<TranslationReadiness | null>(null)
  const [invalidSourceArtifactIds, setInvalidSourceArtifactIds] = useState<string[]>([])
  const translationBatchSize = 90
  const [announcementText, setAnnouncementText] = useState('')
  const [announcementLookupResult, setAnnouncementLookupResult] = useState<AnnouncementLookupResult | null>(null)
  const { confirm, alertDialog, dialog: confirmDialog } = useConfirmDialog()

  useEffect(() => {
    refreshProjects()
    refreshSettings()
    refreshRuntimeVersion()
    refreshLanguageOptions(API)
      .then(() => setLanguageVersion((value) => value + 1))
      .catch(() => undefined)
  }, [])

  useProjectListPolling(refreshProjects, currentIdRef)

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
    setGeneratedDelivery(null)
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

  useProjectSnapshotPolling(currentId, currentIdRef, refreshProjectSnapshot, isCurrentProject, setLatestRun, setBusy, setStatus)

  useEffect(() => {
    if (deleteProjectTarget && !projects.some((project) => project.id === deleteProjectTarget.id)) {
      longPressTriggeredProjectId.current = ''
      setDeleteProjectTarget(null)
    }
  }, [deleteProjectTarget?.id, projects.map((project) => project.id).join('|')])

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
    const preferredQa = preferredTranslationResultArtifact(current, hydratedRun)
    setQaArtifact(preferredQa || artifactsByRole(current, 'translation_workbook')[0] || newestArtifact(artifacts, ['final_workbook']))
    setArchiveArtifact(preferredQa || artifactsByRole(current, 'translation_workbook')[0] || artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['final_workbook', 'language_table']))
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
    if (current?.id && (tab === 'delivery' || (view === 'wizard' && step === 9))) {
      refreshDeliverables()
    }
    // current?.artifacts?.length is a dep because delivery generation registers
    // new artifacts (readback gate / retro), which resets deliverables above and
    // must trigger a refetch to keep download links visible.
  }, [current?.id, current?.runs?.length, current?.artifacts?.length, tab, selectedLanguage, view, step])

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
    if (!current || qaArtifact) return
    const artifact = preferredTranslationResultArtifact(current, latestRun)
    if (artifact) setQaArtifact(artifact)
  }, [current?.id, current?.artifacts?.length, current?.runs?.length, latestRun?.id, latestRun?.status, qaArtifact?.id])

  useEffect(() => {
    if (!current || !latestRun || latestRun.kind !== 'translation' || latestRun.status !== 'passed') return
    if (!isCurrentProject(latestRun.project_id) || !busy) return
    const resultArtifact = preferredTranslationResultArtifact(current, latestRun)
    if (resultArtifact) setQaArtifact(resultArtifact)
    setStep((prev) => (prev < 8 ? 8 : prev))
    setBusyForProject(latestRun.project_id, false)
    setStatusForProject(latestRun.project_id, projectTranslationPassedStatusText(latestRun, selectedLanguage))
  }, [busy, current?.id, current?.artifacts?.length, latestRun?.id, latestRun?.kind, latestRun?.status])

  useEffect(() => {
    if (!latestRun || !['failed', 'needs_input'].includes(latestRun.status)) {
      setQualityIssues([])
      return
    }
    loadQualityIssues(latestRun.id)
  }, [latestRun?.id, latestRun?.status])

  useRunStatusPolling(
    latestRun,
    tab,
    selectedLanguage,
    isCurrentProject,
    setLatestRun,
    setStep,
    setQualityIssues,
    setQaArtifact,
    setStatus,
    setStatusForProject,
    setBusyForProject,
    loadQualityIssues,
    refreshCurrent,
    refreshDeliverables
  )

  useAnnouncementTaskPolling(current, refreshProjectSnapshot, isCurrentProject, setBusyForProject, setStatusForProject)

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
    const targetId = project.id
    const targetName = project.name
    setBusy(true)
    setStatus(`\u6b63\u5728\u5220\u9664\u9879\u76ee\u201c${targetName}\u201d...`)
    try {
      await api(`/api/projects/${targetId}`, { method: 'DELETE' })
      const loaded = await api<Project[]>('/api/projects')
      const activeId = currentIdRef.current
      const nextId = loaded.some((item) => item.id === activeId && item.id !== targetId) ? activeId : loaded[0]?.id || ''
      setProjects((prev) => mergeProjectListSummaries(prev, loaded))
      currentIdRef.current = nextId
      setCurrentId(nextId)
      if (targetId === activeId) {
        setView('overview')
        setTab('meta')
      }
      longPressTriggeredProjectId.current = ''
      setDeleteProjectTarget(null)
      setStatus(`\u9879\u76ee\u201c${targetName}\u201d\u5df2\u5220\u9664`)
    } catch (error) {
      if (/not found/i.test(errorText(error))) {
        await refreshProjects()
        longPressTriggeredProjectId.current = ''
        setDeleteProjectTarget(null)
        setStatus(`\u9879\u76ee\u201c${targetName}\u201d\u5df2\u4e0d\u5b58\u5728\uff0c\u5217\u8868\u5df2\u5237\u65b0\u3002`)
      } else {
        setStatus(`\u5220\u9664\u9879\u76ee\u5931\u8d25\uff1a${errorText(error)}`)
      }
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
    const projectId = task.project_id || currentIdRef.current
    setBusyForProject(projectId, true)
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
      setBusyForProject(projectId, false)
    }
  }

  async function refreshProjects(selectId?: string) {
    const loaded = await api<Project[]>('/api/projects')
    const preferred = selectId && loaded.some((item) => item.id === selectId)
      ? selectId
      : (loaded.some((item) => item.id === currentIdRef.current) ? currentIdRef.current : '')
    const nextId = preferred || loaded[0]?.id || ''
    setProjects((prev) => mergeProjectListSummaries(prev, loaded))
    currentIdRef.current = nextId
    setCurrentId(nextId)
  }

  async function refreshCurrent(projectId = currentIdRef.current) {
    if (!projectId) return null
    const loaded = await api<Project>(`/api/projects/${projectId}`)
    if (!isCurrentProject(projectId)) return loaded
    setProjects((prev) => prev.map((p) => (p.id === loaded.id ? loaded : p)))
    return loaded
  }

  async function refreshProjectSnapshot(projectId: string) {
    if (!projectId) return null
    try {
      const loaded = await api<Project>(`/api/projects/${projectId}`)
      setProjects((prev) => prev.map((p) => (p.id === loaded.id ? loaded : p)))
      return loaded
    } catch (error) {
      if (/not found/i.test(errorText(error))) await refreshProjects()
      return null
    }
  }

  async function refreshGlossaryBatches(projectId = currentId) {
    if (!projectId) return
    const loaded = await api<{ batches: GlossaryBatch[]; active_batch: GlossaryBatch | null; candidates: GlossaryCandidate[] }>(`/api/projects/${projectId}/glossary/batches?${languageQuery(selectedLanguage)}`)
    setGlossaryBatches(loaded.batches || [])
    setGlossaryCandidates(loaded.candidates || [])
  }

  async function refreshRuntimeVersion() {
    try {
      const payload = await api<AppRuntimeVersion>('/api/version')
      setRuntimeVersion(payload)
    } catch {
      setRuntimeVersion({ version: 'unknown', deployment_mode: 'unknown' })
    }
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
      if (isCurrentProject(current.id)) {
        setProjects((prev) => prev.map((p) => (p.id === result.project.id ? result.project : p)))
      }
      const summary = result.analysis?.summary || {}
      const warning = result.analysis?.warning
      setStatus(`${currentLang.short} 项目分析完成：已读取 ${summary.parsed ?? 0}/${summary.total ?? 0} 个资料${warning ? `；${warning}` : ''}`)
      const candidates = result.analysis?.language_table_candidates || []
      if (candidates.length) {
        const confirmScan = await confirm(`识别到 ${candidates.length} 个完整语言表。是否现在扫描术语候选？候选不会直接进入项目术语库。`, {
          title: '扫描术语候选',
          confirmLabel: '现在扫描',
          cancelLabel: '暂不扫描'
        })
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
      setStatus('请先在「判定输入」步骤选择或上传语言表，再扫描术语候选。')
      return
    }
    if (!sourceArtifact || sourceArtifact.id !== artifact.id) {
      setSourceArtifact(artifact)
    }
    const detectedLanguage = await syncLanguageFromArtifact(artifact)
    const readiness = await refreshTranslationReadiness(artifact.id, current.id, detectedLanguage)
    if (!isCurrentProject(current.id)) return
    const inputMode = translationInputMode(readiness)
    if (inputMode === 'invalid') {
      setStatus(`语言表格式需要修正：${translationReadinessUserMessage(readiness)}`)
      setStep(4)
      return
    }
    if (inputMode === 'ready_for_qa') {
      setQaArtifact(artifact)
      setStep(8)
      setStatus(`这份表已有完整译文：${readiness?.translated_rows || 0}/${readiness?.source_rows || 0} 行。无需扫描术语候选，请直接运行 QA。`)
      return
    }
    const extractionLanguage = normalizeLanguageCode(readiness?.target_language) || detectedLanguage || selectedLanguage
    const extractionLang = languageSpec(extractionLanguage)
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
          target_column: extractionLang.targetHeader,
          language: extractionLanguage,
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
    const projectId = current.id
    const artifactId = termArtifact.id
    const language = selectedLanguage
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, '\u6b63\u5728\u5bfc\u5165\u672f\u8bed\u8868...')
    try {
      const result = await api<{ imported_count: number; languages?: LanguageCode[] }>(`/api/projects/${projectId}/glossary/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: artifactId, language })
      })
      await refreshProjectSnapshot(projectId)
      const languageText = result.languages?.length ? `（${result.languages.map((item) => languageSpec(item).short).join('/')}）` : ''
      setStatusForProject(projectId, `\u672f\u8bed\u8868\u5df2\u5bfc\u5165\uff1a${result.imported_count} \u6761${languageText}`)
    } catch (error) {
      setStatusForProject(projectId, `\u672f\u8bed\u8868\u5bfc\u5165\u5931\u8d25\uff1a${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function refreshTranslationReadiness(artifactId: string, projectId = currentIdRef.current, language: LanguageCode = selectedLanguage) {
    const batchSize = effectiveBatchSize(settings, translationBatchSize)
    try {
      const result = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}&${languageQuery(language)}`)
      if (
        isCurrentProject(projectId) &&
        result.reason === 'target_column_missing' &&
        result.format_errors?.includes('target_column_missing')
      ) {
        const targets = await inspectTranslationTargets(artifactId, projectId)
        const suggested = targets?.suggested_language
        if (suggested && suggested !== language) {
          setPrimaryLanguages(targets.detected_languages?.length ? targets.detected_languages : [suggested], suggested)
          const corrected = await api<TranslationReadiness>(`/api/projects/${projectId}/artifacts/${artifactId}/translation-readiness?batch_size=${batchSize}&${languageQuery(suggested)}`)
          if (isCurrentProject(projectId)) setTranslationReadiness(corrected)
          return corrected
        }
      }
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
        setStatusForProject(projectId, result.run.status === 'passed' ? '快速校对已通过，可在交付页生成最终文件。' : `快速校对结束：${runStatusLabel(result.run.status)}`)
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
      if (started.status === 'passed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook', 'final_text'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        setStatusForProject(projectId, `快速翻译已完成并通过 QA：${languageSpec(language).short}。可到交付页下载。`)
        return started
      }
      if (started.status === 'failed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook', 'final_text'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        setStatusForProject(projectId, `快速翻译已完成，但 QA 未通过：${projectRunStatusText(started)}。请到校对页修复；急需交付时可带问题摘要交付。`)
        return started
      }
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

  function selectedQueueLanguages() {
    const languages = selectedLanguages.length ? selectedLanguages : [selectedLanguage]
    return languages.filter((language, index) => languages.indexOf(language) === index)
  }

  async function confirmTermGapBeforeTranslate(language: LanguageCode): Promise<boolean> {
    if (!current || termArtifact) return true
    const confirmedTerms = (current.glossary || []).filter((term) => term.language === language && String(term.target || '').trim()).length
    const readyCandidates = glossaryCandidates.filter((item) =>
      item.status === 'pending' &&
      (item.language || language) === language &&
      String(item.target || '').trim()
    ).length
    if (confirmedTerms > 0 || readyCandidates === 0) return true
    const shouldContinue = await confirm(
      `检测到 ${languageSpec(language).short} 有 ${readyCandidates} 条候选术语尚未加入项目术语库。\n\n` +
      '这些候选术语默认不会参与本次翻译，可能导致译文不按术语表执行。\n\n' +
      '建议返回「术语候选」步骤先确认术语。仍要继续无术语翻译吗？',
      { title: '有未确认的候选术语', confirmLabel: '继续翻译', cancelLabel: '先去确认术语', tone: 'warn' }
    )
    if (!shouldContinue) {
      setStep(5)
      setStatusForProject(current.id, '已暂停翻译：请先在「术语候选」步骤确认候选术语，再启动 AI 翻译。')
    }
    return shouldContinue
  }

  async function confirmTermGapForLanguages(languages: LanguageCode[]): Promise<boolean> {
    for (const language of languages) {
      if (!(await confirmTermGapBeforeTranslate(language))) return false
    }
    return true
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
    const confirmedTermGap = await confirmTermGapBeforeTranslate(selectedLanguage)
    if (!confirmedTermGap) return
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
        ? await confirm('该任务预计 API token 用量超过设置的提醒阈值。确认后会从已完成批次继续，不会重跑已落盘批次。是否继续？', {
            title: 'API 用量确认',
            confirmLabel: '继续翻译',
            cancelLabel: '暂不继续'
          })
        : false
      if (needsBudgetConfirm && !confirmedBudget) {
        setStatusForProject(projectId, '已暂停：等待确认 API 用量预算后继续。')
        return
      }
      const endpoint = resumableRun ? 'resume' : 'start'
      const started = await api<Run>(`/api/runs/${run.id}/translate/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch_size: batchSize, confirm_api_budget: confirmedBudget, confirm_term_gap: confirmedTermGap, large_text_mode: 'auto' })
      })
      if (!isCurrentProject(projectId)) return
      setLatestRun(started)
      if (started.status === 'needs_input' && ['glossary_candidates_not_confirmed', 'selected_term_artifact_empty'].includes(String(started.metadata?.reason || ''))) {
        setStep(5)
        setStatusForProject(projectId, String(started.metadata?.user_message || '术语未正确进入翻译包，已暂停翻译；请先检查术语表或确认候选术语。'))
        return
      }
      if (started.status === 'passed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        setStep((prev) => (prev < 8 ? 8 : prev))
        setStatusForProject(projectId, projectTranslationPassedStatusText(started, selectedLanguage))
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        return
      }
      if (started.status === 'failed') {
        const resultArtifact = newestArtifact(started.artifacts || [], ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
        if (resultArtifact) setQaArtifact(resultArtifact)
        setStep((prev) => (prev < 8 ? 8 : prev))
        setStatusForProject(projectId, `翻译已完成，但 QA 未通过：${projectRunStatusText(started)}。请进入「QA 校对」步骤查看问题并修复；急需交付时可带问题摘要交付。`)
        await refreshCurrent()
        if (tab === 'delivery') await refreshDeliverables()
        return
      }
      setStatusForProject(projectId, `${currentLang.short} 翻译已进入后台队列：系统会自动拆批、限流、落盘和续跑。`)
    } catch (error) {
      setStatusForProject(projectId, `翻译失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }



  async function startMultilingualTranslationQueue(taskCode: 'A' | 'T' = 'T') {
    if (!current || !sourceArtifact) return
    const projectId = current.id
    const languages = selectedQueueLanguages()
    const selectedBatchSize = effectiveBatchSize(settings, translationBatchSize)
    const readiness = translationReadiness?.artifact_id === sourceArtifact.id && translationReadiness.batch_size === selectedBatchSize
      ? translationReadiness
      : await refreshTranslationReadiness(sourceArtifact.id, projectId)
    if (!isCurrentProject(projectId)) return
    const blockReason = formalTranslationBlockReason(settings, sourceArtifact, current, readiness)
    if (blockReason) {
      setStatusForProject(projectId, `无法开始多语言翻译：${blockReason}`)
      return
    }
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, `正在启动多语言翻译队列：${languages.map((language) => languageSpec(language).short).join(' / ')}`)
    try {
      const confirmedTermGap = await confirmTermGapForLanguages(languages)
      if (!confirmedTermGap) return
      const result = await api<MultilingualQueueStatus>(`/api/projects/${current.id}/multilingual/translate/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: sourceArtifact.id,
          languages,
          batch_size: selectedBatchSize,
          task_code: taskCode,
          term_artifact_id: termArtifact?.id || null,
          confirm_api_budget: false,
          confirm_term_gap: confirmedTermGap,
          large_text_mode: 'auto'
        })
      })
      if (!isCurrentProject(projectId)) return
      const firstRunId = result.languages.find((item) => item.translation_run_id || item.run_id)?.translation_run_id || result.languages.find((item) => item.run_id)?.run_id
      if (firstRunId) {
        const run = await api<Run>(`/api/runs/${firstRunId}`)
        if (isCurrentProject(projectId)) setLatestRun(run)
      }
      await refreshCurrent()
      setStatusForProject(projectId, `\u591a\u8bed\u8a00\u7ffb\u8bd1\u961f\u5217\u5df2\u542f\u52a8\uff1a${result.languages.map((item) => item.visible_language).join(' / ')}`)
    } catch (error) {
      setStatusForProject(projectId, `\u591a\u8bed\u8a00\u7ffb\u8bd1\u542f\u52a8\u5931\u8d25\uff1a${errorText(error)}`)
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

  async function runDirectQA(taskCode: 'QA' = 'QA', overrideArtifact?: Artifact | null) {
    const inputQaArtifact = overrideArtifact || qaArtifact
    if (!current || !inputQaArtifact) return
    const projectId = current.id
    if (artifactRole(inputQaArtifact) === 'language_source') {
      const readiness = await refreshTranslationReadiness(inputQaArtifact.id, projectId)
      if (!isCurrentProject(projectId)) return
      if (!canSkipModelTranslation(readiness)) {
        setSourceArtifact(inputQaArtifact)
        setStep(7)
        setStatusForProject(projectId, '这份语言表还不像完整译文表：请先进入 AI 翻译补齐空译文或明显非目标语言内容，再运行 QA。')
        return
      }
    }
    const sourceRunId = inputQaArtifact.run_id && (current.runs || []).some((run) => run.id === inputQaArtifact.run_id && run.kind === 'translation')
      ? inputQaArtifact.run_id
      : null
    if (overrideArtifact) setQaArtifact(overrideArtifact)
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
          input_artifact_id: inputQaArtifact.id,
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
        : `QA 未通过：发现${issueCountPhrase(hardCount)}问题。建议先修复并重跑；急需交付时可带问题摘要进入交付。`)
    } catch (error) {
      setStatusForProject(projectId, `已有译文 QA 失败：${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }



  async function startMultilingualQAQueue(taskCode: 'QA' = 'QA') {
    if (!current) return
    const projectId = current.id
    const inputArtifact = sourceArtifact || qaArtifact
    if (!inputArtifact) {
      setStatusForProject(projectId, '\u8bf7\u5148\u9009\u62e9\u8bed\u8a00\u8868\u6216\u5df2\u8bd1 workbook\uff0c\u518d\u8fd0\u884c\u591a\u8bed\u8a00 QA\u3002')
      return
    }
    const languages = selectedQueueLanguages()
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, `\u6b63\u5728\u542f\u52a8\u591a\u8bed\u8a00 QA \u961f\u5217\uff1a${languages.map((language) => languageSpec(language).short).join(' / ')}`)
    try {
      const result = await api<MultilingualQueueStatus>(`/api/projects/${current.id}/multilingual/qa/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: inputArtifact.id,
          languages,
          task_code: taskCode,
          term_artifact_id: termArtifact?.id || null
        })
      })
      if (!isCurrentProject(projectId)) return
      const firstRunId = result.languages.find((item) => item.qa_run_id || item.run_id)?.qa_run_id || result.languages.find((item) => item.run_id)?.run_id
      if (firstRunId) {
        const run = await api<Run>(`/api/runs/${firstRunId}`)
        if (isCurrentProject(projectId)) setLatestRun(run)
      }
      await refreshCurrent()
      if (tab === 'delivery') await refreshDeliverables()
      setStatusForProject(projectId, `\u591a\u8bed\u8a00 QA \u961f\u5217\u5df2\u542f\u52a8\uff1a${result.languages.map((item) => item.visible_language).join(' / ')}`)
    } catch (error) {
      setStatusForProject(projectId, `\u591a\u8bed\u8a00 QA \u542f\u52a8\u5931\u8d25\uff1a${errorText(error)}`)
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
        setStatusForProject(projectId, `手工修复已重新 QA：${runStatusLabel(result.qa_result.run.status)}`)
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
    setStatusForProject(projectId, '正在启动模型修复后台任务...')
    let started = false
    try {
      const run = await api<Run>(`/api/runs/${latestRun.id}/model-fixes/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_issues: 80, rerun_qa: true })
      })
      if (!isCurrentProject(projectId)) return
      started = true
      const resultRunId = String(run.metadata?.model_fix_result_run_id || '')
      if (resultRunId && run.metadata?.model_fix_status !== 'running') {
        const resultRun = await api<Run>(`/api/runs/${resultRunId}`)
        setLatestRun(resultRun)
        if (resultRun.status === 'passed') {
          setQualityIssues([])
          setStatusForProject(projectId, '模型修复并重跑 QA 已通过，可进入交付。')
        } else {
          const issues = await loadQualityIssues(resultRun.id, projectId)
          const hardCount = issues.filter((issue) => issue.severity === 'hard').length
          setStatusForProject(projectId, `模型修复已完成，但 QA 仍有${issueCountPhrase(hardCount || issues.length)}问题。请继续修复；急需交付时可带问题摘要交付。`)
        }
      } else {
        setLatestRun(run)
        setStatusForProject(projectId, '模型修复已进入后台：系统会修复可定位问题并自动重跑 QA，完成后会更新本页状态。')
      }
      await refreshCurrent()
    } catch (error) {
      setStatusForProject(projectId, `模型修复失败：${errorText(error)}`)
    } finally {
      if (!started) setBusyForProject(projectId, false)
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
      const summary = announcementActionSummary(endpoint, result.summary)
      const taskStatus = String(result.task?.status || '')
      if (endpoint.startsWith('translate/') && ['queued', 'running'].includes(taskStatus)) {
        setStatusForProject(projectId, summary || `公告后台翻译已启动：${announcementActionLabel(endpoint)}`)
      } else {
        setStatusForProject(projectId, summary || `公告步骤已完成：${announcementActionLabel(endpoint)}`)
      }
      return result
    } catch (error) {
      const message = errorText(error)
      setStatusForProject(projectId, `公告任务失败：${message}`)
      if (/约束文件|语言表|表头|可反查词条/.test(message)) {
        void alertDialog(`公告约束文件没有被正确读取：${message}`, { title: '约束文件读取失败', tone: 'warn' })
      }
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
    const projectId = current.id
    await api(`/api/projects/${projectId}/glossary`, {
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
    await refreshProjectSnapshot(projectId)
    setStatusForProject(projectId, '\u8bcd\u6761\u5df2\u65b0\u589e')
  }

  async function updateGlossaryTerm(term: GlossaryTerm, updates: Partial<GlossaryTerm>) {
    if (!current) return
    const projectId = current.id
    await api(`/api/projects/${projectId}/glossary/${term.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    })
    await refreshProjectSnapshot(projectId)
    setStatusForProject(projectId, '\u8bcd\u6761\u5df2\u4fdd\u5b58')
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
    const projectId = current.id
    setBusy(true)
    setStatusForProject(projectId, action === 'accept' ? `\u6b63\u5728\u786e\u8ba4\u52a0\u5165 ${candidates.length} \u6761\u672f\u8bed...` : `\u6b63\u5728\u8df3\u8fc7 ${candidates.length} \u6761\u5019\u9009...`)
    try {
      await api(`/api/projects/${projectId}/glossary/batches/${batchId}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_ids: candidates.map((candidate) => candidate.id) })
      })
      await refreshProjectSnapshot(projectId)
      await refreshGlossaryBatches(projectId)
      setStatusForProject(projectId, action === 'accept' ? `\u5df2\u52a0\u5165 ${candidates.length} \u6761\u672f\u8bed\uff0c\u540e\u7eed\u7ffb\u8bd1\u548c QA \u4f1a\u4f7f\u7528\u9879\u76ee\u672f\u8bed\u5e93\u3002` : `\u5df2\u8df3\u8fc7 ${candidates.length} \u6761\u5019\u9009\uff0c\u4e0d\u4f1a\u8fdb\u5165\u9879\u76ee\u672f\u8bed\u5e93\u3002`)
    } catch (error) {
      setStatusForProject(projectId, `\u672f\u8bed\u6279\u6b21\u5904\u7406\u5931\u8d25\uff1a${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  async function deleteGlossaryTerm(term: GlossaryTerm) {
    if (!current) return
    const projectId = current.id
    await api(`/api/projects/${projectId}/glossary/${term.id}`, { method: 'DELETE' })
    await refreshProjectSnapshot(projectId)
    setStatusForProject(projectId, '\u8bcd\u6761\u5df2\u5220\u9664')
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

  async function refreshDeliverables(projectId = currentIdRef.current) {
    if (!projectId) {
      setDeliverables([])
      return
    }
    try {
      const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${projectId}/deliverables`)
      if (isCurrentProject(projectId)) setDeliverables(result.deliverables || [])
    } catch {
      if (isCurrentProject(projectId)) setDeliverables([])
    }
  }

  async function loadDeliverables(projectId: string): Promise<DeliverableTask[]> {
    const result = await api<{ deliverables: DeliverableTask[] }>(`/api/projects/${projectId}/deliverables`)
    return result.deliverables || []
  }

  function mergeGeneratedDeliveryTask(tasks: DeliverableTask[], generated?: DeliverableTask | null): DeliverableTask[] {
    if (!generated) return tasks
    const next = tasks.filter((task) => task.run_id !== generated.run_id)
    return [generated, ...next]
  }

  async function createDeliveryPackage(runId: string): Promise<DeliveryFile[] | null> {
    if (!current) return null
    const projectId = current.id
    setBusy(true)
    setStatus('\u6b63\u5728\u751f\u6210\u6700\u7ec8\u4ea4\u4ed8\u6587\u4ef6...')
    try {
      const result = await api<{ files: DeliveryFile[]; deliverable?: DeliverableTask }>(`/api/projects/${projectId}/delivery-package?run_id=${encodeURIComponent(runId)}`, { method: 'POST' })
      const files = result.files || []
      const generatedTask = result.deliverable || null
      if (isCurrentProject(projectId)) {
        setGeneratedDelivery({ projectId, runId, files })
        try {
          const refreshed = await loadDeliverables(projectId)
          setDeliverables(mergeGeneratedDeliveryTask(refreshed, generatedTask))
        } catch {
          setDeliverables((previous) => mergeGeneratedDeliveryTask(previous, generatedTask))
        }
      }
      await refreshCurrent(projectId)
      setStatus(`\u6700\u7ec8\u4ea4\u4ed8\u5df2\u751f\u6210\uff1a${files.length} \u4e2a\u6587\u4ef6`)
      return files
    } catch (error) {
      setStatus(`\u6700\u7ec8\u4ea4\u4ed8\u751f\u6210\u5931\u8d25\uff1a${errorText(error)}`)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function finishWizardDelivery() {
    if (!current) return
    const projectId = current.id
    await refreshDeliverables(projectId)
    await refreshCurrent(projectId)
    setTab('delivery')
    setView('overview')
    setStatus('交付已完成，可在项目概览的“交付”页下载最新文件。')
  }



  async function createMergedDeliveryPackage() {
    if (!current || !sourceArtifact) return
    const projectId = current.id
    const languages = selectedQueueLanguages()
    setBusyForProject(projectId, true)
    setStatusForProject(projectId, `\u6b63\u5728\u751f\u6210\u591a\u8bed\u8a00\u5408\u5e76\u4ea4\u4ed8\uff1a${languages.map((language) => languageSpec(language).short).join(' / ')}`)
    try {
      const result = await api<{ files: DeliveryFile[]; merged_languages?: string[]; skipped_languages?: string[] }>(`/api/projects/${current.id}/delivery-package/merged`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          input_artifact_id: sourceArtifact.id,
          languages
        })
      })
      if (!isCurrentProject(projectId)) return
      await refreshDeliverables()
      await refreshCurrent()
      const skipped = result.skipped_languages?.length ? `\uff0c\u8df3\u8fc7 ${result.skipped_languages.length} \u79cd\u672a\u5b8c\u6210\u8bed\u8a00` : ''
      setStatusForProject(projectId, `\u591a\u8bed\u8a00\u5408\u5e76\u4ea4\u4ed8\u5df2\u751f\u6210\uff1a${result.files.length} \u4e2a\u6587\u4ef6${skipped}`)
    } catch (error) {
      setStatusForProject(projectId, `\u591a\u8bed\u8a00\u5408\u5e76\u4ea4\u4ed8\u5931\u8d25\uff1a${errorText(error)}`)
    } finally {
      setBusyForProject(projectId, false)
    }
  }

  const isCloudDeployment = runtimeVersion?.deployment_mode === 'cloud'
  const showSettingsButton = runtimeVersion?.deployment_mode === 'local'
  const bundleVersion = __APP_VERSION__
  const backendVersion = runtimeVersion?.version || ''
  const versionMismatch = Boolean(backendVersion) && backendVersion !== 'unknown' && backendVersion !== bundleVersion

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
            {showSettingsButton ? <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}>⚙ 设置</button> : null}
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
                  {projectActiveTaskCount(project) ? <span className="ptag ptag-live">后台 {projectActiveTaskCount(project)}</span> : null}
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
                onTranslateQueue={() => startMultilingualTranslationQueue('T')}
                onDirectQA={(artifact) => runDirectQA('QA', artifact)}
                onDirectQAQueue={() => startMultilingualQAQueue('QA')}
                onSkipQAArchive={skipQAArchive}
                onManualFixes={applyManualFixes}
                onModelFixes={applyModelFixes}
                onUploadTranslation={uploadTranslationWorkbook}
                onCreateDelivery={createDeliveryPackage}
                onCreateMergedDelivery={createMergedDeliveryPackage}
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
                confirm={confirm}
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
                confirm={confirm}
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
                deliverables={deliverables}
                generatedDeliveryRunId={generatedDelivery?.projectId === current.id ? generatedDelivery.runId : undefined}
                generatedDeliveryFiles={generatedDelivery?.projectId === current.id ? generatedDelivery.files : []}
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
                onTranslateQueue={() => startMultilingualTranslationQueue('T')}
                onCancelTranslate={cancelTranslateRun}
                onDirectQA={(artifact) => runDirectQA('QA', artifact)}
                onDirectQAQueue={() => startMultilingualQAQueue('QA')}
                onSkipQAArchive={skipQAArchive}
                allowSkipQAArchive
                onManualFixes={applyManualFixes}
                onModelFixes={applyModelFixes}
                onUploadTranslation={uploadTranslationWorkbook}
                onCreateDelivery={createDeliveryPackage}
                onCreateMergedDelivery={createMergedDeliveryPackage}
                onFinishDelivery={finishWizardDelivery}
                onFreq={() => setFreqOpen(true)}
                onSaveHarness={saveHarness}
                onUpdateCandidate={updateGlossaryCandidate}
                onResolveCandidates={resolveGlossaryCandidates}
                onTranslateMissingCandidates={translateMissingGlossaryCandidates}
                busy={busy}
                confirm={confirm}
              />
            )}
          </main>
        </div>
      </div>

      <div
        className={versionMismatch ? 'runtime-version-badge version-mismatch' : 'runtime-version-badge'}
        title={versionMismatch
          ? `前端 v${bundleVersion} 与后端 v${backendVersion} 版本不一致，请刷新页面或重新部署前端`
          : (runtimeVersion?.git_sha ? `commit ${runtimeVersion.git_sha}` : 'current deployment version')}
      >
        {versionMismatch ? `v${bundleVersion} / 后端 v${backendVersion} 版本不一致` : `v${bundleVersion}`}
      </div>

      {newProjectOpen ? <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} /> : null}
      {deleteProjectTarget ? <DeleteProjectModal project={deleteProjectTarget} busy={busy} onClose={() => { longPressTriggeredProjectId.current = ''; setDeleteProjectTarget(null) }} onDelete={deleteProject} /> : null}
      {announcementCancelTarget ? <CancelAnnouncementTaskModal task={announcementCancelTarget} busy={busy} onClose={() => { longPressTriggeredAnnouncementTaskId.current = ''; setAnnouncementCancelTarget(null) }} onCancelTask={cancelAnnouncementTask} /> : null}
      {settingsOpen ? <SettingsModal onClose={() => { setSettingsOpen(false); refreshSettings() }} /> : null}
      {freqOpen ? <FrequencyModal onClose={() => setFreqOpen(false)} /> : null}
      {confirmDialog}
    </div>
  )
}

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Missing root element')
}
window.__lwsRoot = window.__lwsRoot ?? createRoot(rootElement)
window.__lwsRoot.render(<App />)
