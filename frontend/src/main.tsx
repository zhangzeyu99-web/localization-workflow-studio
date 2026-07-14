import React, { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FolderKanban, Languages, Plus, Settings, WandSparkles, Zap } from 'lucide-react'
import './styles.css'
import './styles/workbench.css'
import { API, api } from './apiClient'
import { refreshLanguageOptions, languageSpec, normalizeLanguageCode, type LanguageCode } from './languages'
import { SettingsModal } from './SettingsModal'
import { useConfirmDialog } from './components/modals/ConfirmModal'
import { DeleteProjectModal } from './components/modals/DeleteProjectModal'
import { CancelAnnouncementTaskModal } from './components/modals/CancelAnnouncementTaskModal'
import { NewProjectModal } from './components/modals/NewProjectModal'
import { FrequencyModal } from './components/modals/FrequencyModal'
import { EmptyState } from './components/project/EmptyState'
import { ProjectOverview } from './components/project/ProjectOverview'
import { ProjectListItem } from './components/project/ProjectListItem'
import { useProjectListPolling } from './hooks/useProjectListPolling'
import { useProjectSnapshotPolling } from './hooks/useProjectSnapshotPolling'
import { useRunStatusPolling } from './hooks/useRunStatusPolling'
import { useAnnouncementTaskPolling } from './hooks/useAnnouncementTaskPolling'
import { useActiveJobsPolling } from './hooks/useActiveJobsPolling'
import { useProjectActions } from './hooks/useProjectActions'
import { useTranslationActions } from './hooks/useTranslationActions'
import { useGlossaryActions } from './hooks/useGlossaryActions'
import { useAnnouncementActions } from './hooks/useAnnouncementActions'
import { ActiveJobsBadge } from './components/system/ActiveJobsBadge'
import { ActiveJobsPanel } from './components/system/ActiveJobsPanel'
import { onOpenActiveJobsPanelRequest } from './components/system/activeJobsPanelBus'
import { artifactsByRole, newestArtifact, runArtifacts, uniqueArtifactsByContent } from './domain/artifacts'
import { artifactForProject, preferredTranslationResultArtifact, runForProject } from './domain/projectState'
import { projectTranslationPassedStatusText } from './domain/projectActivity'
import { canSkipModelTranslation, findVisibleQualityRun } from './domain/translationFlow'
import { scopeProjectToLanguage } from './domain/projectAssets'
import {
  createTranslationTaskId,
  findActiveFormalTask,
  findUnfinishedFormalTask,
  formalTranslationTasks,
  runMatchesTranslationTask,
  translationTaskResumeStep,
  type FormalTranslationTask,
  type TranslationTaskSession,
} from './domain/translationTaskLifecycle'

const QuickTaskWizard = lazy(() => import('./components/quickTask/QuickTaskWizard').then((m) => ({ default: m.QuickTaskWizard })))
const AnnouncementWizard = lazy(() => import('./components/announcement/AnnouncementWorkflow').then((m) => ({ default: m.AnnouncementWizard })))
const Wizard = lazy(() => import('./components/translationWizard/TranslationWizard').then((m) => ({ default: m.Wizard })))

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

import type { AnnouncementLookupResult, AnnouncementTask, AppRuntimeVersion, AppSettings, Artifact, DeliverableTask, GeneratedDeliveryState, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, Project, ProjectTab, QualityIssue, Run, TranslationReadiness, AppView } from './types'


function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsReady, setProjectsReady] = useState(false)
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
  const [activeJobsPanelOpen, setActiveJobsPanelOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('准备就绪')
  const currentIdRef = useRef('')
  const [translationTaskId, setTranslationTaskId] = useState('')
  const translationTaskIdRef = useRef('')
  const translationTaskSessionsRef = useRef(new Map<string, TranslationTaskSession>())
  const [hydratedProjectId, setHydratedProjectId] = useState('')
  const projectNavigationRef = useRef(new Map<string, { view: AppView; tab: ProjectTab; step: number }>())
  const [intro, setIntro] = useState('')
  const [sourceArtifact, setSourceArtifact] = useState<Artifact | null>(null)
  const [termArtifact, setTermArtifact] = useState<Artifact | null>(null)
  const [qaArtifact, setQaArtifact] = useState<Artifact | null>(null)
  const [archiveArtifact, setArchiveArtifact] = useState<Artifact | null>(null)
  const [assetArtifacts, setAssetArtifacts] = useState<Artifact[]>([])
  const [latestRun, setLatestRun] = useState<Run | null>(null)
  const [selectedLanguage, setSelectedLanguage] = useState<LanguageCode>('en')
  const [selectedLanguages, setSelectedLanguages] = useState<LanguageCode[]>(['en'])
  const [lineProofread, setLineProofread] = useState(false)
  const [glossaryPreview, setGlossaryPreview] = useState<GlossaryPreviewRow[]>([])
  const [glossaryBatches, setGlossaryBatches] = useState<GlossaryBatch[]>([])
  const [glossaryCandidates, setGlossaryCandidates] = useState<GlossaryCandidate[]>([])
  const [qualityIssues, setQualityIssues] = useState<QualityIssue[]>([])
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [deliverables, setDeliverables] = useState<DeliverableTask[]>([])
  const [deliverablesLoading, setDeliverablesLoading] = useState(false)
  const [deliverablesError, setDeliverablesError] = useState('')
  const [generatedDelivery, setGeneratedDelivery] = useState<GeneratedDeliveryState | null>(null)
  const [translationReadiness, setTranslationReadiness] = useState<TranslationReadiness | null>(null)
  const [sourceInputNotice, setSourceInputNotice] = useState<TranslationReadiness | null>(null)
  const [invalidSourceArtifactIds, setInvalidSourceArtifactIds] = useState<string[]>([])
  const translationBatchSize = 90
  const [announcementText, setAnnouncementText] = useState('')
  const [announcementLookupResult, setAnnouncementLookupResult] = useState<AnnouncementLookupResult | null>(null)
  const { confirm, alertDialog, dialog: confirmDialog } = useConfirmDialog()
  const runGlossaryExtractRef = useRef<(inputArtifact?: Artifact | null) => Promise<void>>(async () => undefined)

  const current = useMemo(() => projects.find((p) => p.id === currentId), [projects, currentId])
  const scopedSourceArtifact = artifactForProject(current, sourceArtifact)
  const scopedTermArtifact = artifactForProject(current, termArtifact)
  const scopedQaArtifact = artifactForProject(current, qaArtifact)
  const scopedArchiveArtifact = artifactForProject(current, archiveArtifact)
  const scopedLatestRun = runForProject(current, latestRun)
  const currentTaskSession = current?.id ? translationTaskSessionsRef.current.get(current.id) : undefined
  const currentFormalTask = translationTaskId
    ? formalTranslationTasks(current).find((task) => task.translationTaskId === translationTaskId) || null
    : null
  const currentFormalLatestRun = current && currentFormalTask
    ? { ...currentFormalTask.latestRun, artifacts: runArtifacts(current, currentFormalTask.latestRun.id) }
    : null
  const wizardLatestRun = view === 'wizard' && currentTaskSession
    ? currentFormalLatestRun || (scopedLatestRun && (!translationTaskId || runMatchesTranslationTask(scopedLatestRun, translationTaskId)) ? scopedLatestRun : null)
    : scopedLatestRun
  const scopedGeneratedDelivery = generatedDelivery && generatedDelivery.projectId === current?.id
    && (!generatedDelivery.sourceArtifactId || generatedDelivery.sourceArtifactId === scopedSourceArtifact?.id)
    && (view !== 'wizard' || !translationTaskId || generatedDelivery.translationTaskId === translationTaskId)
    ? generatedDelivery
    : null
  const scopedAssetArtifacts = useMemo(
    () => assetArtifacts.filter((artifact) => artifactForProject(current, artifact)),
    [current?.id, assetArtifacts]
  )
  const projectContextLoading = Boolean(currentId) && hydratedProjectId !== currentId
  const currentScoped = useMemo(() => current ? scopeProjectToLanguage(current, selectedLanguage) : undefined, [current, selectedLanguage])
  const currentLang = languageSpec(selectedLanguage)
  const selectedQualityRun = useMemo(
    () => current ? findVisibleQualityRun(current, selectedLanguage, scopedSourceArtifact?.id, view === 'wizard' ? translationTaskId : undefined) : null,
    [current, selectedLanguage, scopedSourceArtifact?.id, view, translationTaskId]
  )

  const setPrimaryLanguage = useCallback((language: LanguageCode) => {
    setSelectedLanguage(language)
    setSelectedLanguages((prev) => prev.includes(language) ? prev : [...prev, language])
  }, [])

  const setPrimaryLanguages = useCallback((languages: LanguageCode[], primary?: LanguageCode | null) => {
    const normalized = languages.length ? languages : [primary || 'en']
    const nextPrimary = primary && normalized.includes(primary) ? primary : normalized[0]
    setSelectedLanguages(normalized)
    setSelectedLanguage(nextPrimary)
  }, [])

  const toggleTargetLanguage = useCallback((language: LanguageCode) => {
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
  }, [selectedLanguage])

  const isCurrentProject = useCallback((projectId?: string | null): boolean => {
    return Boolean(projectId) && currentIdRef.current === projectId
  }, [])

  const activateTranslationTaskId = useCallback((taskId: string) => {
    translationTaskIdRef.current = taskId
    setTranslationTaskId(taskId)
  }, [])

  const isCurrentTranslationTask = useCallback((projectId: string, taskId: string): boolean => {
    const activeSessionId = translationTaskSessionsRef.current.get(projectId)?.id || ''
    return isCurrentProject(projectId)
      && activeSessionId === (currentTaskSession?.id || '')
      && (!taskId || translationTaskIdRef.current === taskId)
  }, [currentTaskSession?.id, isCurrentProject])

  const isCurrentRunScope = useCallback((run: Run): boolean => {
    if (!isCurrentProject(run.project_id)) return false
    if (view !== 'wizard' || !translationTaskIdRef.current) return true
    return runMatchesTranslationTask(run, translationTaskIdRef.current)
  }, [isCurrentProject, view])

  const setStatusForProject = useCallback((projectId: string, message: string) => {
    if (isCurrentProject(projectId)) setStatus(message)
  }, [isCurrentProject])

  const setBusyForProject = useCallback((projectId: string, value: boolean) => {
    if (isCurrentProject(projectId)) setBusy(value)
  }, [isCurrentProject])

  const resetProjectTransientState = useCallback((message = '准备就绪') => {
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
    setLineProofread(false)
    setGlossaryPreview([])
    setGlossaryBatches([])
    setGlossaryCandidates([])
    setQualityIssues([])
    setDeliverables([])
    setDeliverablesLoading(false)
    setDeliverablesError('')
    setGeneratedDelivery(null)
    setTranslationReadiness(null)
    setAnnouncementText('')
    setAnnouncementLookupResult(null)
  }, [])

  const beginFreshTranslationTask = useCallback((project: Project) => {
    const taskId = createTranslationTaskId()
    const session: TranslationTaskSession = {
      id: taskId,
      projectId: project.id,
      step: 1,
      sourceArtifactId: '',
      selectedLanguages: ['en'],
      status: 'draft',
    }
    translationTaskSessionsRef.current.set(project.id, session)
    activateTranslationTaskId(taskId)
    setBusy(false)
    setStatus('新的翻译任务已就绪。')
    setIntro(project.description || '')
    setSourceArtifact(null)
    setQaArtifact(null)
    setLatestRun(null)
    setSelectedLanguage('en')
    setSelectedLanguages(['en'])
    setLineProofread(false)
    setGlossaryPreview([])
    setGlossaryBatches([])
    setGlossaryCandidates([])
    setQualityIssues([])
    setGeneratedDelivery(null)
    setTranslationReadiness(null)
    setSourceInputNotice(null)
    setInvalidSourceArtifactIds([])
    setTab('meta')
    setStep(1)
    setView('wizard')
  }, [activateTranslationTaskId])

  const {
    cancelProjectDeleteHold, beginProjectDeleteHold, selectProject, deleteProject, refreshProjects,
    refreshCurrent, refreshProjectSnapshot, refreshRuntimeVersion, refreshSettings, saveProjectMeta,
    loadQualityIssues, createProject, upload, runAnalysis, saveHarness, uploadAsset, uploadProjectMaterial
  } = useProjectActions({
    current, currentId, currentIdRef, intro, assetArtifacts: scopedAssetArtifacts, selectedLanguage, translationTaskId, currentLang, busy,
    deleteHoldTimer, longPressTriggeredProjectId, isCurrentProject, isCurrentTranslationTask,
    setProjects, setCurrentId, setView, setTab, setBusy, setStatus, setStatusForProject, setQualityIssues,
    setRuntimeVersion, setSettings, setNewProjectOpen, setDeleteHoldProjectId, setDeleteProjectTarget,
    setSourceArtifact, setAssetArtifacts, resetProjectTransientState, confirm,
    runGlossaryExtract: (inputArtifact) => runGlossaryExtractRef.current(inputArtifact)
  })
  const handleUploadTerm = useCallback(async (file: File) => {
    setTermArtifact(await upload(file, 'term_base'))
  }, [upload])
  const handleProjectPointerDown = useCallback((project: Project, event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button === 0) beginProjectDeleteHold(project)
  }, [beginProjectDeleteHold])
  const actionLatestRun = view === 'wizard' ? wizardLatestRun : scopedLatestRun
  const actionTranslationTaskId = view === 'wizard' ? translationTaskId : ''
  const {
    refreshTranslationReadiness, selectSourceArtifact, selectQaArtifact, syncLanguageFromArtifact,
    classifySourceArtifact, inspectTranslationTargets, startQuickTask, runTranslate,
    startMultilingualTranslationQueue, cancelTranslateRun, runDirectQA, cancelQaRun, startMultilingualQAQueue,
    applyManualFixes, applyModelFixes, uploadSourceWorkbook, uploadArchiveWorkbook, uploadTranslationWorkbook,
    importTranslationArchive, skipQAArchive, addTranslationEntry, updateTranslationEntry, deleteTranslationEntry,
    refreshDeliverables, loadDeliverables, createDeliveryPackage, finishWizardDelivery, createMergedDeliveryPackage
  } = useTranslationActions({
    current, currentIdRef, translationTaskId: actionTranslationTaskId, translationTaskIdRef,
    sourceArtifact: scopedSourceArtifact, termArtifact: scopedTermArtifact, qaArtifact: scopedQaArtifact, archiveArtifact: scopedArchiveArtifact, latestRun: actionLatestRun,
    translationReadiness, glossaryCandidates, settings, translationBatchSize, tab, selectedLanguage,
    selectedLanguages, lineProofread, currentLang, isCurrentProject, isCurrentTranslationTask,
    setSourceArtifact, setQaArtifact, setArchiveArtifact, setTranslationReadiness, setSourceInputNotice,
    setInvalidSourceArtifactIds, setStep, setBusy, setStatus, setStatusForProject, setBusyForProject,
    setQualityIssues, setLatestRun, setDeliverables, setDeliverablesLoading, setDeliverablesError, setGeneratedDelivery, setTab, setView,
    setPrimaryLanguage, setPrimaryLanguages, confirm, refreshCurrent, loadQualityIssues, upload
  })
  const selectWizardSourceArtifact = useCallback((artifact: Artifact | null) => {
    if (current?.id) {
      const session = translationTaskSessionsRef.current.get(current.id)
      if (session) translationTaskSessionsRef.current.set(current.id, { ...session, sourceArtifactId: artifact?.id || '' })
    }
    selectSourceArtifact(artifact)
  }, [current?.id, selectSourceArtifact])
  const glossaryActions = useGlossaryActions({
    current, currentId, sourceArtifact: scopedSourceArtifact, termArtifact: scopedTermArtifact, assetArtifacts: scopedAssetArtifacts, intro, selectedLanguage,
    translationTaskId, translationTaskIdRef, isCurrentProject,
    setSourceArtifact, setTermArtifact, setLatestRun, setStep, setBusy, setStatus, setStatusForProject,
    setBusyForProject, setGlossaryPreview, setGlossaryBatches, setGlossaryCandidates, setQaArtifact,
    refreshCurrent, refreshProjectSnapshot, syncLanguageFromArtifact, refreshTranslationReadiness
  })
  runGlossaryExtractRef.current = glossaryActions.runGlossaryExtract
  const {
    refreshGlossaryBatches, runGlossaryExtract, previewGlossaryImport, importGlossaryArtifact, addGlossaryTerm,
    updateGlossaryTerm, updateGlossaryCandidate, translateMissingGlossaryCandidates, resolveGlossaryCandidates,
    deleteGlossaryTerm
  } = glossaryActions
  const {
    cancelAnnouncementCancelHold, beginAnnouncementCancelHold, openAnnouncementTask, cancelAnnouncementTask,
    uploadAnnouncementResponse, uploadAnnouncementConstraint, uploadAnnouncementTermsFile, createAnnouncementTask,
    runAnnouncementTaskAction, runAnnouncementLookup
  } = useAnnouncementActions({
    current, currentLang, currentIdRef, selectedLanguage, busy, announcementFocusTaskId,
    announcementCancelHoldTimer, longPressTriggeredAnnouncementTaskId, isCurrentProject,
    setAnnouncementCancelHoldTaskId, setAnnouncementCancelTarget, setAnnouncementFocusTaskId,
    setAnnouncementLookupResult, setView, setBusy, setStatus, setStatusForProject, setBusyForProject,
    setLatestRun, setAssetArtifacts, refreshCurrent, upload, alertDialog
  })

  const openFormalTaskInWizard = useCallback((project: Project, task: FormalTranslationTask, message: string) => {
    const replacingTask = translationTaskSessionsRef.current.get(project.id)?.id !== task.id
    const source = (project.artifacts || []).find((artifact) => artifact.id === task.sourceArtifactId) || null
    const latest = { ...task.latestRun, artifacts: runArtifacts(project, task.latestRun.id) }
    const session: TranslationTaskSession = {
      id: task.id,
      projectId: project.id,
      step: translationTaskResumeStep(task),
      sourceArtifactId: task.sourceArtifactId,
      selectedLanguages: task.languages,
      status: 'draft',
    }
    translationTaskSessionsRef.current.set(project.id, session)
    activateTranslationTaskId(task.translationTaskId)
    if (replacingTask) setBusy(false)
    setIntro(project.description || '')
    setSourceArtifact(source)
    setPrimaryLanguages(task.languages, normalizeLanguageCode(latest.language) || task.languages[0])
    setLatestRun(latest)
    setQaArtifact(preferredTranslationResultArtifact(project, latest))
    setGeneratedDelivery(null)
    setTranslationReadiness(null)
    setSourceInputNotice(null)
    setQualityIssues([])
    setStep(session.step)
    setView('wizard')
    setStatusForProject(project.id, message)
  }, [activateTranslationTaskId, setPrimaryLanguages, setStatusForProject])

  const restoreDraftSessionInWizard = useCallback((project: Project, session: TranslationTaskSession) => {
    const task = formalTranslationTasks(project).find((item) => item.id === session.id)
    if (task) {
      openFormalTaskInWizard(project, task, '已继续当前未完成翻译任务。')
      return
    }
    const replacingTask = translationTaskSessionsRef.current.get(project.id)?.id !== session.id
    const source = (project.artifacts || []).find((artifact) => artifact.id === session.sourceArtifactId) || null
    activateTranslationTaskId(session.id.startsWith('legacy:') ? '' : session.id)
    if (replacingTask) setBusy(false)
    setIntro(project.description || '')
    setSourceArtifact(source)
    setQaArtifact(null)
    setLatestRun(null)
    setPrimaryLanguages(session.selectedLanguages)
    setGeneratedDelivery(null)
    setTranslationReadiness(null)
    setSourceInputNotice(null)
    setQualityIssues([])
    setStep(session.step)
    setView('wizard')
    setStatusForProject(project.id, '已继续当前未完成翻译任务。')
  }, [activateTranslationTaskId, openFormalTaskInWizard, setPrimaryLanguages, setStatusForProject])

  const abandonFormalTask = useCallback(async (project: Project, task: FormalTranslationTask) => {
    const path = task.legacy
      ? `/api/runs/${task.latestRun.id}/abandon-translation-task`
      : `/api/projects/${project.id}/translation-tasks/${task.translationTaskId}/abandon`
    await api(path, { method: 'POST' })
  }, [])

  const openNewTranslationTask = useCallback(async () => {
    if (!current) return
    const projectId = current.id
    const loaded = await refreshCurrent(projectId).catch(() => null)
    if (!isCurrentProject(projectId)) return
    const project = loaded || current
    const activeTask = findActiveFormalTask(project)
    if (activeTask) {
      openFormalTaskInWizard(project, activeTask, '已有任务正在处理，已带你回到当前任务。')
      return
    }

    const session = translationTaskSessionsRef.current.get(projectId)
    const sessionTask = session ? formalTranslationTasks(project).find((task) => task.id === session.id) || null : null
    if (session?.status === 'delivered' || (sessionTask && ['delivered', 'abandoned', 'closed'].includes(sessionTask.state))) {
      beginFreshTranslationTask(project)
      return
    }

    const unfinishedTask = sessionTask || (!session ? findUnfinishedFormalTask(project) : null)
    if (session || unfinishedTask) {
      const abandon = await confirm('当前项目还有一项未完成的翻译任务。你可以继续原任务，或放弃它并从空白任务开始。', {
        title: '已有未完成翻译任务',
        confirmLabel: '放弃草稿并新建',
        cancelLabel: '继续当前任务',
        tone: 'warn',
      })
      if (!isCurrentProject(projectId)) return
      if (!abandon) {
        if (unfinishedTask) openFormalTaskInWizard(project, unfinishedTask, '已继续当前未完成翻译任务。')
        else if (session) restoreDraftSessionInWizard(project, session)
        return
      }
      if (unfinishedTask) {
        try {
          await abandonFormalTask(project, unfinishedTask)
          if (!isCurrentProject(projectId)) return
          await refreshCurrent(projectId)
        } catch (error) {
          setStatusForProject(projectId, `无法放弃当前任务：${String(error)}`)
          return
        }
      }
    }
    beginFreshTranslationTask(project)
  }, [current, refreshCurrent, isCurrentProject, openFormalTaskInWizard, beginFreshTranslationTask, confirm, restoreDraftSessionInWizard, abandonFormalTask, setStatusForProject])

  const finishCurrentTranslationTask = useCallback(async (): Promise<boolean> => {
    if (!current) return false
    const projectId = current.id
    const session = translationTaskSessionsRef.current.get(projectId)
    const finished = await finishWizardDelivery()
    if (!finished || !isCurrentProject(projectId)) return false
    if (session) translationTaskSessionsRef.current.set(projectId, { ...session, status: 'delivered' })
    projectNavigationRef.current.set(projectId, { view: 'overview', tab: 'delivery', step: 1 })
    return true
  }, [current, finishWizardDelivery, isCurrentProject])

  const startNextTranslationTask = useCallback(async () => {
    if (!current) return
    const project = current
    if (await finishCurrentTranslationTask()) beginFreshTranslationTask(project)
  }, [current, finishCurrentTranslationTask, beginFreshTranslationTask])

  useEffect(() => {
    refreshProjects().catch(() => undefined).finally(() => setProjectsReady(true))
    refreshSettings()
    refreshRuntimeVersion()
    refreshLanguageOptions(API)
      .then(() => setLanguageVersion((value) => value + 1))
      .catch(() => undefined)
  }, [])

  useProjectListPolling(refreshProjects, currentIdRef)
  const activeJobs = useActiveJobsPolling()

  useEffect(() => onOpenActiveJobsPanelRequest(() => setActiveJobsPanelOpen(true)), [])

  useEffect(() => {
    currentIdRef.current = currentId
    const session = translationTaskSessionsRef.current.get(currentId)
    activateTranslationTaskId(session && !session.id.startsWith('legacy:') ? session.id : '')
    resetProjectTransientState('准备就绪')
    return () => {
      if (deleteHoldTimer.current !== null) window.clearTimeout(deleteHoldTimer.current)
      if (announcementCancelHoldTimer.current !== null) window.clearTimeout(announcementCancelHoldTimer.current)
    }
  }, [currentId, activateTranslationTaskId, resetProjectTransientState])

  useEffect(() => {
    let canceled = false
    setHydratedProjectId('')
    if (!currentId) return () => { canceled = true }
    refreshCurrent(currentId)
      .catch(() => null)
      .finally(() => {
        if (!canceled && currentIdRef.current === currentId) setHydratedProjectId(currentId)
      })
    return () => { canceled = true }
  }, [currentId])

  useEffect(() => {
    if (currentId) projectNavigationRef.current.set(currentId, { view, tab, step })
  }, [currentId, view, tab, step])

  useEffect(() => {
    if (!currentId || view !== 'wizard' || hydratedProjectId !== currentId) return
    const session = translationTaskSessionsRef.current.get(currentId)
    if (!session) return
    translationTaskSessionsRef.current.set(currentId, {
      ...session,
      step,
      sourceArtifactId: scopedSourceArtifact?.id || '',
      selectedLanguages,
    })
  }, [currentId, hydratedProjectId, view, step, scopedSourceArtifact?.id, selectedLanguages.join('|')])

  const activeRunPolling = Boolean(actionLatestRun && ['queued', 'running'].includes(actionLatestRun.status))
  const activeAnnouncementPolling = Boolean(current?.announcement_tasks?.some((task) => ['queued', 'running'].includes(task.status)))
  useProjectSnapshotPolling(currentId, currentIdRef, refreshProjectSnapshot, isCurrentProject, setLatestRun, setBusy, setStatus, activeRunPolling || activeAnnouncementPolling, isCurrentRunScope)

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
      setDeliverablesLoading(false)
      setDeliverablesError('')
      setSourceInputNotice(null)
      setInvalidSourceArtifactIds([])
      setAnnouncementText('')
      setAnnouncementLookupResult(null)
      return
    }
    const artifacts = current.artifacts || []
    setTermArtifact(artifactsByRole(current, 'glossary_curated')[0] || artifactsByRole(current, 'glossary_source')[0] || newestArtifact(artifacts, ['glossary_final', 'term_base']))
    setAssetArtifacts(uniqueArtifactsByContent(artifacts.filter((artifact) => artifact.kind === 'asset')))
    const fallbackArchive = artifactsByRole(current, 'translation_workbook')[0] || artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['final_workbook', 'language_table'])
    setArchiveArtifact(fallbackArchive)
    const session = translationTaskSessionsRef.current.get(current.id)
    if (session) {
      const source = artifacts.find((artifact) => artifact.id === session.sourceArtifactId) || null
      const task = formalTranslationTasks(current).find((item) => item.id === session.id) || null
      const hydratedRun = task ? { ...task.latestRun, artifacts: runArtifacts(current, task.latestRun.id) } : null
      setSourceArtifact(source)
      setPrimaryLanguages(session.selectedLanguages, normalizeLanguageCode(hydratedRun?.language) || session.selectedLanguages[0])
      setLatestRun(hydratedRun)
      setQaArtifact(hydratedRun ? preferredTranslationResultArtifact(current, hydratedRun) : null)
      setStep(session.step)
    } else {
      const latestProjectRun = (current.runs || [])[0] || null
      const hydratedRun = latestProjectRun ? { ...latestProjectRun, artifacts: runArtifacts(current, latestProjectRun.id) } : null
      const preferredQa = preferredTranslationResultArtifact(current, hydratedRun)
      setSourceArtifact(artifactsByRole(current, 'language_source')[0] || newestArtifact(artifacts, ['language_table']))
      setQaArtifact(preferredQa || artifactsByRole(current, 'translation_workbook')[0] || newestArtifact(artifacts, ['final_workbook']))
      setArchiveArtifact(preferredQa || fallbackArchive)
      setLatestRun(hydratedRun)
    }
    setDeliverables([])
    setDeliverablesLoading(false)
    setDeliverablesError('')
    setSourceInputNotice(null)
    setInvalidSourceArtifactIds([])
  }, [current?.id, current?.artifacts?.length, current?.runs?.length, setPrimaryLanguages])

  useEffect(() => {
    if (!current?.id) return
    if (view === 'wizard' && currentTaskSession) {
      if (scopedSourceArtifact?.id) refreshGlossaryBatches(current.id, scopedSourceArtifact.id)
      else {
        setGlossaryBatches([])
        setGlossaryCandidates([])
      }
      return
    }
    refreshGlossaryBatches(current.id)
  }, [current?.id, wizardLatestRun?.id, wizardLatestRun?.status, selectedLanguage, view, currentTaskSession?.id, scopedSourceArtifact?.id])

  useEffect(() => {
    // Reset the content scroll position when the user switches project, view,
    // tab, or wizard step; otherwise a long previous page leaves the new one
    // scrolled halfway down.
    const main = document.querySelector('.main')
    if (main) main.scrollTop = 0
    window.scrollTo(0, 0)
  }, [currentId, view, tab, step])

  useEffect(() => {
    if (current?.id && (tab === 'delivery' || (view === 'wizard' && step === 9))) {
      refreshDeliverables()
    }
    // current?.artifacts?.length is a dep because delivery generation registers
    // new artifacts (readback gate / retro), which resets deliverables above and
    // must trigger a refetch to keep download links visible.
  }, [current?.id, current?.runs?.length, current?.artifacts?.length, tab, selectedLanguage, view, step])

  useEffect(() => {
    if (!current?.id || !currentTaskSession) return
    const generatedBelongsToTask = Boolean(
      generatedDelivery?.projectId === current.id
      && generatedDelivery.files.length
      && (translationTaskId
        ? generatedDelivery.translationTaskId === translationTaskId
        : generatedDelivery.runId === wizardLatestRun?.id)
    )
    if (!generatedBelongsToTask && currentFormalTask?.state !== 'delivered') return
    translationTaskSessionsRef.current.set(current.id, { ...currentTaskSession, status: 'delivered' })
  }, [current?.id, currentTaskSession?.id, generatedDelivery?.runId, generatedDelivery?.translationTaskId, generatedDelivery?.files.length, currentFormalTask?.state, translationTaskId, wizardLatestRun?.id])

  useEffect(() => {
    if (current?.id && scopedSourceArtifact) void syncLanguageFromArtifact(scopedSourceArtifact)
  }, [current?.id, scopedSourceArtifact?.id])

  useEffect(() => {
    if (!scopedSourceArtifact?.id) {
      setTranslationReadiness(null)
      return
    }
    refreshTranslationReadiness(scopedSourceArtifact.id, currentIdRef.current, selectedLanguage, false)
  }, [scopedSourceArtifact?.id, settings?.batch_size, selectedLanguage])

  useEffect(() => {
    if (view !== 'wizard' || step < 8 || !current || !selectedQualityRun) return
    setLatestRun({ ...selectedQualityRun, artifacts: runArtifacts(current, selectedQualityRun.id) })
  }, [view, step, current?.id, selectedQualityRun?.id, selectedQualityRun?.status, selectedQualityRun?.updated_at])

  useEffect(() => {
    if (!scopedQaArtifact && scopedSourceArtifact && translationReadiness?.artifact_id === scopedSourceArtifact.id && canSkipModelTranslation(translationReadiness)) {
      setQaArtifact(scopedSourceArtifact)
    }
  }, [scopedQaArtifact?.id, scopedSourceArtifact?.id, translationReadiness?.artifact_id, translationReadiness?.ready_for_qa, translationReadiness?.translated_rows, translationReadiness?.empty_target_rows, translationReadiness?.cjk_target_rows])

  useEffect(() => {
    if (!current || scopedQaArtifact) return
    const artifact = preferredTranslationResultArtifact(current, actionLatestRun)
    if (artifact) setQaArtifact(artifact)
  }, [current?.id, current?.artifacts?.length, current?.runs?.length, actionLatestRun?.id, actionLatestRun?.status, scopedQaArtifact?.id])

  useEffect(() => {
    if (!current || !actionLatestRun || actionLatestRun.kind !== 'translation' || actionLatestRun.status !== 'passed') return
    if (!isCurrentProject(actionLatestRun.project_id) || !isCurrentRunScope(actionLatestRun) || !busy) return
    const resultArtifact = preferredTranslationResultArtifact(current, actionLatestRun)
    if (resultArtifact) setQaArtifact(resultArtifact)
    setStep((prev) => (prev < 8 ? 8 : prev))
    setBusyForProject(actionLatestRun.project_id, false)
    setStatusForProject(actionLatestRun.project_id, projectTranslationPassedStatusText(actionLatestRun, selectedLanguage))
  }, [busy, current?.id, current?.artifacts?.length, actionLatestRun?.id, actionLatestRun?.kind, actionLatestRun?.status, isCurrentRunScope])

  useEffect(() => {
    if (!actionLatestRun || !['failed', 'needs_input'].includes(actionLatestRun.status) || !isCurrentRunScope(actionLatestRun)) {
      setQualityIssues([])
      return
    }
    loadQualityIssues(actionLatestRun.id, actionLatestRun.project_id, () => isCurrentRunScope(actionLatestRun))
  }, [actionLatestRun?.id, actionLatestRun?.status, isCurrentRunScope])

  useRunStatusPolling(
    actionLatestRun,
    tab,
    selectedLanguage,
    isCurrentProject,
    isCurrentRunScope,
    setLatestRun,
    setStep,
    setQualityIssues,
    setQaArtifact,
    setStatus,
    setStatusForProject,
    setBusyForProject,
    loadQualityIssues,
    refreshCurrent,
    refreshDeliverables,
    () => refreshProjects(currentIdRef.current)
  )

  useAnnouncementTaskPolling(current, refreshProjectSnapshot, isCurrentProject, setBusyForProject, setStatusForProject)

  const isCloudDeployment = runtimeVersion?.deployment_mode === 'cloud'
  const showSettingsButton = !__HIDE_SETTINGS__ && runtimeVersion?.deployment_mode === 'local'
  const bundleVersion = __APP_VERSION__
  const backendVersion = runtimeVersion?.version || ''
  const versionMismatch = Boolean(backendVersion) && backendVersion !== 'unknown' && backendVersion !== bundleVersion

  return (
    <div className="shell">
      <div className="app">
        <header className="header">
          <div className="brand-lockup">
            <span className="brand-mark"><Languages size={22} aria-hidden="true" /></span>
            <div>
              <h1>本地化工作台</h1>
              <p>Localization Workflow Studio</p>
            </div>
          </div>
          <div className="header-actions">
            <span className={`status ${busy ? 'running' : ''}`} role="status" aria-live="polite">{busy ? <span className="loading" /> : null}{status}</span>
            <div className="active-jobs-anchor">
              <ActiveJobsBadge jobs={activeJobs} open={activeJobsPanelOpen} onToggle={() => setActiveJobsPanelOpen((value) => !value)} />
              {activeJobsPanelOpen ? <ActiveJobsPanel jobs={activeJobs} onClose={() => setActiveJobsPanelOpen(false)} /> : null}
            </div>
            <span
              className={versionMismatch ? 'runtime-version-badge version-mismatch' : 'runtime-version-badge'}
              title={versionMismatch
                ? `前端 v${bundleVersion} 与后端 v${backendVersion} 版本不一致，请刷新页面或重新部署前端`
                : (runtimeVersion?.git_sha ? `commit ${runtimeVersion.git_sha}` : 'current deployment version')}
            >
              {versionMismatch ? `v${bundleVersion} / 后端 v${backendVersion} 版本不一致` : `v${bundleVersion}`}
            </span>
            {showSettingsButton ? <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}><Settings size={16} aria-hidden="true" />设置</button> : null}
          </div>
        </header>

        <div className="layout">
          <aside className="sidebar">
            <div className="sidebar-title"><FolderKanban size={15} aria-hidden="true" />项目</div>
            <div className="project-list">
              {projects.map((project) => (
                <ProjectListItem
                  key={project.id}
                  project={project}
                  isActive={project.id === currentId}
                  isDeleteHold={deleteHoldProjectId === project.id}
                  onPointerDown={handleProjectPointerDown}
                  onPointerUp={cancelProjectDeleteHold}
                  onPointerLeave={cancelProjectDeleteHold}
                  onPointerCancel={cancelProjectDeleteHold}
                  onSelect={(project, event) => {
                    const saved = projectNavigationRef.current.get(project.id)
                    selectProject(project, event)
                    if (event.defaultPrevented || project.id === currentId) return
                    setView(saved?.view || 'overview')
                    setTab(saved?.tab || 'meta')
                    setStep(saved?.step || 1)
                  }}
                />
              ))}
            </div>
            <button className="new-project-btn" onClick={() => setNewProjectOpen(true)}><Plus size={15} aria-hidden="true" />新建项目</button>
            <div className="sidebar-title quick"><Zap size={15} aria-hidden="true" />快捷入口</div>
            <button className="project-item quick-entry" onClick={() => {
              if (!current) return
              void openNewTranslationTask()
            }} disabled={!current || projectContextLoading}>
              <span className="pname"><WandSparkles size={16} aria-hidden="true" />新翻译任务</span>
              <span className="pmeta">基于当前项目启动工作流</span>
            </button>
            <button className="project-item quick-entry" data-testid="quick-task-entry" onClick={() => {
              if (!current) return
              setStatusForProject(current.id, '\u5feb\u901f\u4efb\u52a1\u5df2\u5c31\u7eea\u3002')
              setView('quick')
            }} disabled={!current || projectContextLoading}>
              <span className="pname"><Zap size={16} aria-hidden="true" />快速任务</span>
              <span className="pmeta">三步完成翻译或校对</span>
            </button>
          </aside>

          <main className="main">
            <div className="main-content">
              {!current ? <EmptyState onCreate={() => setNewProjectOpen(true)} loading={!projectsReady} /> : projectContextLoading ? <span className="loading">正在加载项目...</span> : view === 'overview' ? (
              <ProjectOverview
                project={current}
                tab={tab}
                setTab={setTab}
                settings={settings}
                busy={busy}
                status={status}
                intro={intro}
                setIntro={setIntro}
                sourceArtifact={scopedSourceArtifact}
                termArtifact={scopedTermArtifact}
                qaArtifact={scopedQaArtifact}
                archiveArtifact={scopedArchiveArtifact}
                latestRun={scopedLatestRun}
                translationReadiness={translationReadiness}
                qualityIssues={qualityIssues}
                glossaryPreview={glossaryPreview}
                deliverables={deliverables}
                deliverablesLoading={deliverablesLoading}
                deliverablesError={deliverablesError}
                assetArtifacts={scopedAssetArtifacts}
                setSourceArtifact={selectSourceArtifact}
                setTermArtifact={setTermArtifact}
                setQaArtifact={selectQaArtifact}
                setArchiveArtifact={setArchiveArtifact}
                onSaveMeta={saveProjectMeta}
                onAnalyze={runAnalysis}
                onUploadSource={uploadSourceWorkbook}
                onUploadTerm={handleUploadTerm}
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
                onCancelQa={cancelQaRun}
                onSkipQAArchive={skipQAArchive}
                onManualFixes={applyManualFixes}
                onModelFixes={applyModelFixes}
                onUploadTranslation={uploadTranslationWorkbook}
                onCreateDelivery={createDeliveryPackage}
                onRefreshDelivery={refreshDeliverables}
                onCreateMergedDelivery={createMergedDeliveryPackage}
                onOpenActivityRun={(run) => {
                  const artifacts = runArtifacts(current, run.id)
                  setLatestRun({ ...run, artifacts })
                  const language = normalizeLanguageCode(run.language)
                  if (language) setPrimaryLanguage(language)
                  if (run.kind === 'qa') {
                    const inputArtifactId = String(run.metadata?.input_artifact_id || '')
                    const inputArtifact = (current.artifacts || []).find((artifact) => artifact.id === inputArtifactId) || null
                    setQaArtifact(newestArtifact(artifacts, ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook']) || inputArtifact)
                    setTab('qa')
                  } else {
                    setTab('translation')
                  }
                }}
                onStartTask={() => { void openNewTranslationTask() }}
                onStartAnnouncement={() => openAnnouncementTask()}
                onStartQuickTask={() => { setStatusForProject(current.id, '快速任务已就绪。'); setView('quick') }}
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
            ) : (
              <Suspense fallback={<span className="loading" />}>
                {view === 'quick' ? (
                  <QuickTaskWizard
                    project={current}
                    busy={busy}
                    status={status}
                    settings={settings}
                    latestRun={scopedLatestRun}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
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
                    assetArtifacts={scopedAssetArtifacts}
                    announcementText={announcementText}
                    setAnnouncementText={setAnnouncementText}
                    lookupResult={announcementLookupResult}
                    onUploadAsset={uploadAsset}
                    onUploadConstraint={uploadAnnouncementConstraint}
                    onUploadTermsFile={uploadAnnouncementTermsFile}
                    onCreateTask={createAnnouncementTask}
                    onTaskAction={runAnnouncementTaskAction}
                    onLookup={runAnnouncementLookup}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
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
                    translationTaskId={translationTaskId}
                    step={step}
                    setStep={setStep}
                    intro={intro}
                    setIntro={setIntro}
                    sourceArtifact={scopedSourceArtifact}
                    termArtifact={scopedTermArtifact}
                    qaArtifact={scopedQaArtifact}
                    assetArtifacts={scopedAssetArtifacts}
                    latestRun={wizardLatestRun}
                    translationReadiness={translationReadiness}
                    sourceInputNotice={sourceInputNotice}
                    invalidSourceArtifactIds={invalidSourceArtifactIds}
                    glossaryBatches={glossaryBatches}
                    glossaryCandidates={glossaryCandidates}
                    qualityIssues={qualityIssues}
                    deliverables={deliverables}
                    generatedDeliveryRunId={scopedGeneratedDelivery?.runId}
                    generatedDeliveryFiles={scopedGeneratedDelivery?.files || []}
                    generatedDeliveryMergedLanguages={scopedGeneratedDelivery?.mergedLanguages || []}
                    generatedDeliverySkippedLanguages={scopedGeneratedDelivery?.skippedLanguages || []}
                    generatedDeliveryLanguageResults={scopedGeneratedDelivery?.languageResults || []}
                    selectedLanguage={selectedLanguage}
                    setSelectedLanguage={setPrimaryLanguage}
                    selectedLanguages={selectedLanguages}
                    toggleSelectedLanguage={toggleTargetLanguage}
                    lineProofread={lineProofread}
                    setLineProofread={setLineProofread}
                    setSourceArtifact={selectWizardSourceArtifact}
                    setTermArtifact={setTermArtifact}
                    setQaArtifact={selectQaArtifact}
                    glossaryPreview={glossaryPreview}
                    settings={settings}
                    status={status}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
                    onUploadSource={uploadSourceWorkbook}
                    onUploadTerm={handleUploadTerm}
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
                    onCancelQa={cancelQaRun}
                    onSkipQAArchive={skipQAArchive}
                    allowSkipQAArchive
                    onManualFixes={applyManualFixes}
                    onModelFixes={applyModelFixes}
                    onUploadTranslation={uploadTranslationWorkbook}
                    onCreateDelivery={createDeliveryPackage}
                    onCreateMergedDelivery={createMergedDeliveryPackage}
                    onFinishDelivery={() => { void finishCurrentTranslationTask() }}
                    onStartNextTask={() => { void startNextTranslationTask() }}
                    onFreq={() => setFreqOpen(true)}
                    onSaveHarness={saveHarness}
                    onUpdateCandidate={updateGlossaryCandidate}
                    onResolveCandidates={resolveGlossaryCandidates}
                    onTranslateMissingCandidates={translateMissingGlossaryCandidates}
                    busy={busy}
                    confirm={confirm}
                  />
                )}
              </Suspense>
              )}
            </div>
          </main>
        </div>
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
