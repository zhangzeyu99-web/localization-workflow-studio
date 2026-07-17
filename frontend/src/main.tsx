import React, { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FolderKanban, Languages, LogOut, Plus, Settings, UserCog, WandSparkles, Zap } from 'lucide-react'
import './styles.css'
import './styles/workbench.css'
import { API, api } from './apiClient'
import { ADMIN, AuthGate, AuthProvider, PROJECT_MANAGE, PROJECT_READ, TASK_RUN, useAuth } from './auth'
import { roleBadgeLabel } from './auth/roleText'
import { refreshLanguageOptions, languageSpec, normalizeLanguageCode, type LanguageCode } from './languages'
import { SettingsModal } from './SettingsModal'
import { useConfirmDialog } from './components/modals/ConfirmModal'
import { DeleteProjectModal } from './components/modals/DeleteProjectModal'
import { CancelAnnouncementTaskModal } from './components/modals/CancelAnnouncementTaskModal'
import { NewProjectModal } from './components/modals/NewProjectModal'
import { UserManagementModal } from './components/modals/UserManagementModal'
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
import { OperatorIdentityControl } from './components/system/OperatorIdentityControl'
import { artifactsByRole, newestArtifact, runArtifacts, uniqueArtifactsByContent } from './domain/artifacts'
import { artifactForProject, preferredTranslationResultArtifact, runForProject } from './domain/projectState'
import { projectTranslationPassedStatusText } from './domain/projectActivity'
import { projectQueueJobCount, queueJobKindLabel } from './domain/jobQueues'
import { canSkipModelTranslation, findVisibleQualityRun } from './domain/translationFlow'
import { scopeProjectToLanguage } from './domain/projectAssets'
import { announcementTaskStatusConflict, selectAnnouncementTaskLifecycle, type AnnouncementSessionScope } from './domain/announcementTaskLifecycle'
import {
  createQuickTaskId,
  isQuickTaskRun,
  quickTaskIdOfRun,
  quickTaskIsTerminalState,
  selectQuickTaskLifecycle,
  type QuickTaskGroup,
  type QuickTaskSessionScope,
} from './domain/quickTaskLifecycle'
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
import { clearSessionNavigation, readSessionNavigation, writeSessionNavigation, type SessionNavigation, type SessionTaskScope } from './sessionNavigation'

const QuickTaskWizard = lazy(() => import('./components/quickTask/QuickTaskWizard').then((m) => ({ default: m.QuickTaskWizard })))
const AnnouncementWizard = lazy(() => import('./components/announcement/AnnouncementWorkflow').then((m) => ({ default: m.AnnouncementWizard })))
const Wizard = lazy(() => import('./components/translationWizard/TranslationWizard').then((m) => ({ default: m.Wizard })))

declare global {
  interface Window {
    __lwsRoot?: ReturnType<typeof createRoot>
  }
}

import type { AnnouncementLookupResult, AnnouncementTask, AppRuntimeVersion, AppSettings, Artifact, DeliverableTask, GeneratedDeliveryState, GlossaryBatch, GlossaryCandidate, GlossaryPreviewRow, JobQueueEntry, Project, ProjectTab, QualityIssue, Run, TranslationReadiness, AppView } from './types'


function App() {
  const { user, authEnabled, can, logout } = useAuth()
  const [projects, setProjects] = useState<Project[]>([])
  const [projectsReady, setProjectsReady] = useState(false)
  const [, setLanguageVersion] = useState(0)
  const [currentId, setCurrentId] = useState<string>('')
  const [view, setView] = useState<AppView>('overview')
  const viewRef = useRef<AppView>('overview')
  viewRef.current = view
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
  const announcementFocusTaskIdRef = useRef('')
  const announcementSessionGenerationRef = useRef(0)
  const [announcementSessionGeneration, setAnnouncementSessionGeneration] = useState(0)
  const quickTaskSessionRef = useRef<QuickTaskSessionScope>({ projectId: '', taskId: '', generation: 0 })
  const quickTaskDetailRef = useRef({ projectId: '', taskId: '', runId: '' })
  const [quickTaskSession, setQuickTaskSession] = useState<QuickTaskSessionScope | null>(null)
  const [quickTaskInitialRun, setQuickTaskInitialRun] = useState<Run | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [userManagementOpen, setUserManagementOpen] = useState(false)
  const [runtimeVersion, setRuntimeVersion] = useState<AppRuntimeVersion | null>(null)
  const [freqOpen, setFreqOpen] = useState(false)
  const [activeJobsPanelOpen, setActiveJobsPanelOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('准备就绪')
  const currentIdRef = useRef('')
  const [translationTaskId, setTranslationTaskId] = useState('')
  const translationTaskIdRef = useRef('')
  const translationTaskSessionsRef = useRef(new Map<string, TranslationTaskSession>())
  const restoredNavigationRef = useRef<SessionNavigation | null | undefined>(undefined)
  if (restoredNavigationRef.current === undefined) restoredNavigationRef.current = readSessionNavigation()
  const [restoredTaskScopeHandled, setRestoredTaskScopeHandled] = useState(() => (
    !restoredNavigationRef.current || restoredNavigationRef.current.view === 'overview'
  ))
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

  const beginAnnouncementSession = useCallback((taskId: string) => {
    const generation = announcementSessionGenerationRef.current + 1
    announcementSessionGenerationRef.current = generation
    announcementFocusTaskIdRef.current = taskId
    setAnnouncementFocusTaskId(taskId)
    setAnnouncementSessionGeneration(generation)
  }, [])

  const captureAnnouncementSession = useCallback((taskId = announcementFocusTaskIdRef.current): AnnouncementSessionScope => ({
    projectId: currentIdRef.current,
    taskId,
    generation: announcementSessionGenerationRef.current,
  }), [])

  const isCurrentAnnouncementSession = useCallback((scope: AnnouncementSessionScope): boolean => (
    isCurrentProject(scope.projectId)
    && announcementFocusTaskIdRef.current === scope.taskId
    && announcementSessionGenerationRef.current === scope.generation
  ), [isCurrentProject])

  const beginQuickTaskSession = useCallback((projectId: string, taskId: string, initialRun: Run | null = null) => {
    const scope = {
      projectId,
      taskId,
      generation: quickTaskSessionRef.current.generation + 1,
    }
    quickTaskSessionRef.current = scope
    setQuickTaskSession(scope)
    setQuickTaskInitialRun(initialRun)
    return scope
  }, [])

  const beginQuickTaskEntryScope = useCallback((projectId: string): QuickTaskSessionScope => {
    const scope = {
      projectId,
      taskId: `quick-entry-${createQuickTaskId()}`,
      generation: quickTaskSessionRef.current.generation + 1,
    }
    quickTaskSessionRef.current = scope
    quickTaskDetailRef.current = { projectId: '', taskId: '', runId: '' }
    return scope
  }, [])

  const invalidateQuickTaskSession = useCallback((projectId: string) => {
    const scope = {
      projectId,
      taskId: `quick-idle-${createQuickTaskId()}`,
      generation: quickTaskSessionRef.current.generation + 1,
    }
    quickTaskSessionRef.current = scope
    quickTaskDetailRef.current = { projectId: '', taskId: '', runId: '' }
    return scope
  }, [])

  const isCurrentQuickTaskSession = useCallback((scope: QuickTaskSessionScope): boolean => (
    isCurrentProject(scope.projectId)
    && quickTaskSessionRef.current.projectId === scope.projectId
    && quickTaskSessionRef.current.taskId === scope.taskId
    && quickTaskSessionRef.current.generation === scope.generation
    && (scope.taskId.startsWith('quick-entry-') || viewRef.current === 'quick')
  ), [isCurrentProject])

  const isCurrentQuickTaskAction = useCallback((run: Run): boolean => {
    if (!isQuickTaskRun(run) || !isCurrentProject(run.project_id) || viewRef.current !== 'overview') return false
    const focus = quickTaskDetailRef.current
    if (focus.projectId !== run.project_id) return false
    const taskId = quickTaskIdOfRun(run)
    if (!taskId || quickTaskIsTerminalState(String(run.metadata?.translation_task_state || ''))) return false
    return focus.taskId === taskId
  }, [isCurrentProject])

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
    if (view === 'quick') {
      const scope = quickTaskSessionRef.current
      return isQuickTaskRun(run) && Boolean(scope.taskId) && scope.projectId === run.project_id && quickTaskIdOfRun(run) === scope.taskId
    }
    if (isQuickTaskRun(run)) return false
    if (view === 'announcement') {
      const taskId = String(run.metadata?.task_id || run.metadata?.announcement_task_id || '')
      return Boolean(announcementFocusTaskIdRef.current) && taskId === announcementFocusTaskIdRef.current
    }
    if (view !== 'wizard' || !translationTaskIdRef.current) return true
    return runMatchesTranslationTask(run, translationTaskIdRef.current)
  }, [announcementSessionGeneration, quickTaskSession?.generation, isCurrentProject, view])

  const isCurrentActionRunScope = useCallback((run: Run): boolean => (
    isQuickTaskRun(run) ? isCurrentQuickTaskAction(run) : isCurrentRunScope(run)
  ), [isCurrentQuickTaskAction, isCurrentRunScope])

  const setActionLatestRun = useCallback((run: Run | null) => {
    if (run && isQuickTaskRun(run)) {
      const focus = quickTaskDetailRef.current
      const taskId = quickTaskIdOfRun(run)
      if (
        viewRef.current === 'overview'
        && focus.projectId === run.project_id
        && ((focus.taskId && focus.taskId === taskId) || (!focus.taskId && focus.runId === run.id))
      ) {
        quickTaskDetailRef.current = { projectId: focus.projectId, taskId: focus.taskId || taskId, runId: run.id }
      }
    }
    setLatestRun(run)
  }, [])

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
    loadQualityIssues, createProject, upload, runAnalysis, saveHarness, uploadProjectMaterial
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
    if (event.button === 0 && can(PROJECT_MANAGE)) beginProjectDeleteHold(project)
  }, [beginProjectDeleteHold, can])
  const actionLatestRun = view === 'quick'
    ? null
    : view === 'wizard'
      ? wizardLatestRun
      : scopedLatestRun && isQuickTaskRun(scopedLatestRun)
        ? (quickTaskDetailRef.current.projectId === current?.id && quickTaskDetailRef.current.runId === scopedLatestRun.id ? scopedLatestRun : null)
        : scopedLatestRun
  const pollingLatestRun = actionLatestRun && isQuickTaskRun(actionLatestRun) && !isCurrentQuickTaskAction(actionLatestRun) ? null : actionLatestRun
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
    isCurrentQuickTaskAction,
    setSourceArtifact, setQaArtifact, setArchiveArtifact, setTranslationReadiness, setSourceInputNotice,
    setInvalidSourceArtifactIds, setStep, setBusy, setStatus, setStatusForProject, setBusyForProject,
    setQualityIssues, setLatestRun: setActionLatestRun, setDeliverables, setDeliverablesLoading, setDeliverablesError, setGeneratedDelivery, setTab, setView,
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
    uploadAnnouncementAsset, uploadAnnouncementResponse, uploadAnnouncementConstraint, uploadAnnouncementTermsFile, createAnnouncementTask,
    runAnnouncementTaskAction, runAnnouncementLookup
  } = useAnnouncementActions({
    current, currentLang, currentIdRef, selectedLanguage, busy, announcementFocusTaskId,
    announcementCancelHoldTimer, longPressTriggeredAnnouncementTaskId, isCurrentProject,
    setAnnouncementCancelHoldTaskId, setAnnouncementCancelTarget,
    setAnnouncementLookupResult, setView, setBusy, setStatus, setStatusForProject, setBusyForProject,
    setLatestRun, setAssetArtifacts, refreshCurrent, upload, alertDialog,
    beginAnnouncementSession, captureAnnouncementSession, isCurrentAnnouncementSession
  })

  const openNewAnnouncementTask = useCallback(async () => {
    if (!current) return
    const projectId = current.id
    invalidateQuickTaskSession(projectId)
    const session = captureAnnouncementSession()
    const loaded = await refreshCurrent(projectId).catch(() => null)
    if (!isCurrentAnnouncementSession(session)) return
    let candidateProject = loaded || current
    for (let decisionRound = 0; decisionRound < 3; decisionRound += 1) {
      const lifecycle = selectAnnouncementTaskLifecycle(candidateProject.announcement_tasks || [])
      if (lifecycle.activeTask) {
        openAnnouncementTask(lifecycle.activeTask)
        return
      }
      if (!lifecycle.stoppedTasks.length) {
        openAnnouncementTask()
        return
      }
      const discard = await confirm('当前项目还有未完成的公告任务。你可以继续当前任务，或放弃并从空白任务开始。', {
        title: '已有未完成公告任务',
        confirmLabel: '放弃并新建',
        cancelLabel: '继续当前任务',
        tone: 'warn',
      })
      if (!isCurrentAnnouncementSession(session)) return
      if (!discard) {
        openAnnouncementTask(lifecycle.stoppedTasks[0])
        return
      }
      const latest = await refreshCurrent(projectId).catch(() => null)
      if (!latest || !isCurrentAnnouncementSession(session)) return
      const latestLifecycle = selectAnnouncementTaskLifecycle(latest.announcement_tasks || [])
      if (latestLifecycle.activeTask) {
        openAnnouncementTask(latestLifecycle.activeTask)
        return
      }
      for (const task of latestLifecycle.stoppedTasks) {
        try {
          await api(`/api/announcement-tasks/${task.id}/cancel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ expected_statuses: [task.status] }),
          })
          if (!isCurrentAnnouncementSession(session)) return
        } catch (error) {
          if (!isCurrentAnnouncementSession(session)) return
          const conflict = announcementTaskStatusConflict(error)
          if (conflict) {
            const conflicted = await refreshCurrent(projectId).catch(() => null)
            if (!conflicted || !isCurrentAnnouncementSession(session)) return
            const conflictLifecycle = selectAnnouncementTaskLifecycle(conflicted.announcement_tasks || [])
            const active = conflictLifecycle.activeTask
              || (conflicted.announcement_tasks || []).find((item) => item.id === conflict.taskId && ['queued', 'running'].includes(item.status))
              || null
            if (active) {
              openAnnouncementTask(active)
              return
            }
          }
          setStatusForProject(projectId, '放弃未完成公告任务失败，请重试。')
          return
        }
      }
      if (!isCurrentAnnouncementSession(session)) return
      const refreshed = await refreshCurrent(projectId).catch(() => null)
      if (!refreshed || !isCurrentAnnouncementSession(session)) return
      const refreshedLifecycle = selectAnnouncementTaskLifecycle(refreshed.announcement_tasks || [])
      if (refreshedLifecycle.activeTask) {
        openAnnouncementTask(refreshedLifecycle.activeTask)
        return
      }
      if (refreshedLifecycle.stoppedTasks.length) {
        if (decisionRound >= 2) {
          openAnnouncementTask(refreshedLifecycle.stoppedTasks[0], '检测到新的未完成公告任务，已打开继续。')
          return
        }
        candidateProject = refreshed
        continue
      }
      openAnnouncementTask()
      return
    }
  }, [current, invalidateQuickTaskSession, captureAnnouncementSession, refreshCurrent, isCurrentAnnouncementSession, openAnnouncementTask, confirm, setStatusForProject])

  const openQuickTaskGroup = useCallback((project: Project, group: QuickTaskGroup | null, message: string, preferredRunId = '') => {
    const taskId = group?.taskId || createQuickTaskId()
    const selectedRun = group?.runs.find((run) => run.id === preferredRunId) || group?.activeRun || group?.latestRun || null
    const initialRun = selectedRun
      ? { ...selectedRun, artifacts: runArtifacts(project, selectedRun.id) }
      : null
    beginQuickTaskSession(project.id, taskId, initialRun)
    quickTaskDetailRef.current = { projectId: '', taskId: '', runId: '' }
    setBusy(false)
    setLatestRun(null)
    setQualityIssues([])
    setGeneratedDelivery(null)
    setView('quick')
    setStatusForProject(project.id, message)
  }, [beginQuickTaskSession, setStatusForProject])

  const openNewQuickTask = useCallback(async () => {
    if (!current) return
    const projectId = current.id
    const entryScope = beginQuickTaskEntryScope(projectId)
    const loaded = await refreshCurrent(projectId).catch(() => null)
    if (!isCurrentQuickTaskSession(entryScope)) return
    let project = loaded || current
    for (let decisionRound = 0; decisionRound < 3; decisionRound += 1) {
      const lifecycle = selectQuickTaskLifecycle(project.runs || [])
      if (lifecycle.activeTask) {
        openQuickTaskGroup(project, lifecycle.activeTask, '已有快速任务正在处理，已返回当前任务。')
        return
      }
      if (!lifecycle.stoppedTasks.length) {
        openQuickTaskGroup(project, null, '新的快速任务已就绪。')
        return
      }
      const abandon = await confirm('当前项目还有未交付的快速任务。你可以继续原任务，或放弃并从空白任务开始。', {
        title: '已有未完成快速任务',
        confirmLabel: '放弃并新建',
        cancelLabel: '继续当前任务',
        tone: 'warn',
      })
      if (!isCurrentQuickTaskSession(entryScope)) return
      if (!abandon) {
        openQuickTaskGroup(project, lifecycle.stoppedTasks[0], '已继续当前未完成快速任务。')
        return
      }
      const refreshed = await refreshCurrent(projectId).catch(() => null)
      if (!refreshed || !isCurrentQuickTaskSession(entryScope)) return
      project = refreshed
      const latestLifecycle = selectQuickTaskLifecycle(project.runs || [])
      if (latestLifecycle.activeTask) {
        openQuickTaskGroup(project, latestLifecycle.activeTask, '检测到快速任务仍在处理，已返回当前任务。')
        return
      }
      try {
        for (const group of latestLifecycle.stoppedTasks) {
          await api(`/api/projects/${projectId}/translation-tasks/${encodeURIComponent(group.taskId)}/abandon`, { method: 'POST' })
          if (!isCurrentQuickTaskSession(entryScope)) return
        }
      } catch (error) {
        const conflicted = await refreshCurrent(projectId).catch(() => null)
        if (!conflicted || !isCurrentQuickTaskSession(entryScope)) {
          if (isCurrentQuickTaskSession(entryScope)) setStatusForProject(projectId, `放弃快速任务失败：${String(error)}`)
          return
        }
        project = conflicted
        const conflictLifecycle = selectQuickTaskLifecycle(project.runs || [])
        if (conflictLifecycle.activeTask) {
          openQuickTaskGroup(project, conflictLifecycle.activeTask, '任务状态已变化，已返回当前运行中的快速任务。')
          return
        }
        if (!conflictLifecycle.stoppedTasks.length) {
          openQuickTaskGroup(project, null, '原快速任务已结束，新的快速任务已就绪。')
          return
        }
        if (decisionRound >= 2) {
          openQuickTaskGroup(project, conflictLifecycle.stoppedTasks[0], '任务状态持续变化，已打开最新未完成任务。')
          return
        }
        continue
      }
      const afterAbandon = await refreshCurrent(projectId).catch(() => null)
      if (!afterAbandon || !isCurrentQuickTaskSession(entryScope)) return
      project = afterAbandon
      const afterLifecycle = selectQuickTaskLifecycle(project.runs || [])
      if (afterLifecycle.activeTask) {
        openQuickTaskGroup(project, afterLifecycle.activeTask, '检测到新的快速任务正在处理，已返回当前任务。')
        return
      }
      if (afterLifecycle.stoppedTasks.length) {
        if (decisionRound >= 2) {
          openQuickTaskGroup(project, afterLifecycle.stoppedTasks[0], '检测到新的未完成快速任务，已打开继续。')
          return
        }
        continue
      }
      openQuickTaskGroup(project, null, '新的快速任务已就绪。')
      return
    }
  }, [current, beginQuickTaskEntryScope, refreshCurrent, isCurrentQuickTaskSession, openQuickTaskGroup, confirm, setStatusForProject])

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
    invalidateQuickTaskSession(projectId)
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
  }, [current, invalidateQuickTaskSession, refreshCurrent, isCurrentProject, openFormalTaskInWizard, beginFreshTranslationTask, confirm, restoreDraftSessionInWizard, abandonFormalTask, setStatusForProject])

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

  const openRunInOverview = useCallback((run: Run) => {
    if (!current || run.project_id !== current.id) return
    beginQuickTaskSession(current.id, `quick-idle-${createQuickTaskId()}`)
    quickTaskDetailRef.current = isQuickTaskRun(run)
      ? { projectId: current.id, taskId: quickTaskIdOfRun(run), runId: run.id }
      : { projectId: '', taskId: '', runId: '' }
    const artifacts = runArtifacts(current, run.id)
    const hydratedRun = { ...run, artifacts }
    setLatestRun(hydratedRun)
    setQualityIssues([])
    setBusy(false)
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
    setView('overview')
  }, [current, beginQuickTaskSession, setPrimaryLanguage])

  useEffect(() => {
    const restored = restoredNavigationRef.current
    refreshProjects(restored?.projectId)
      .then(() => {
        if (restored && currentIdRef.current === restored.projectId) {
          setView(restored.view)
          setTab(restored.tab)
          setStep(restored.step)
          return
        }
        clearSessionNavigation()
        setView('overview')
        setTab('meta')
        setStep(1)
      })
      .catch(() => clearSessionNavigation())
      .finally(() => setProjectsReady(true))
    refreshSettings()
    refreshRuntimeVersion()
    refreshLanguageOptions(API)
      .then(() => setLanguageVersion((value) => value + 1))
      .catch(() => undefined)
  }, [])

  useProjectListPolling(refreshProjects, currentIdRef)
  const { queues: jobQueues, refresh: refreshJobQueues } = useActiveJobsPolling()

  const cancelQueueJob = useCallback(async (job: JobQueueEntry) => {
    const accepted = await confirm(
      `确定取消“${job.project_name || '未知项目'}”的${queueJobKindLabel(job.job_kind)}任务吗？`,
      { title: '取消后台任务', confirmLabel: '确认取消', cancelLabel: '返回', tone: 'warn' }
    )
    if (!accepted) return
    try {
      await api(`/api/system/job-queues/${encodeURIComponent(job.job_id)}/cancel`, { method: 'POST' }, '取消后台任务')
      await refreshJobQueues()
    } catch (error) {
      setStatus(`取消后台任务失败：${error instanceof Error ? error.message : String(error)}`)
    }
  }, [confirm, refreshJobQueues])

  useEffect(() => {
    currentIdRef.current = currentId
    beginAnnouncementSession('')
    const session = translationTaskSessionsRef.current.get(currentId)
    activateTranslationTaskId(session && !session.id.startsWith('legacy:') ? session.id : '')
    resetProjectTransientState('准备就绪')
    return () => {
      if (deleteHoldTimer.current !== null) window.clearTimeout(deleteHoldTimer.current)
      if (announcementCancelHoldTimer.current !== null) window.clearTimeout(announcementCancelHoldTimer.current)
    }
  }, [currentId, activateTranslationTaskId, beginAnnouncementSession, resetProjectTransientState])

  useEffect(() => {
    if (!projectsReady || !restoredTaskScopeHandled || !currentId || view !== 'quick' || quickTaskSessionRef.current.projectId === currentId) return
    beginQuickTaskSession(currentId, `quick-idle-${createQuickTaskId()}`)
  }, [projectsReady, restoredTaskScopeHandled, currentId, view, beginQuickTaskSession])

  useEffect(() => {
    let canceled = false
    let retryTimer: number | null = null
    setHydratedProjectId('')
    if (!currentId) return () => { canceled = true }
    const scheduleRetry = () => {
      if (canceled || currentIdRef.current !== currentId) return
      retryTimer = window.setTimeout(() => {
        retryTimer = null
        void hydrate()
      }, 1000)
    }
    const hydrate = async () => {
      try {
        const loaded = await refreshCurrent(currentId)
        if (canceled || currentIdRef.current !== currentId) return
        if (loaded?.id === currentId) setHydratedProjectId(currentId)
        else scheduleRetry()
      } catch {
        scheduleRetry()
      }
    }
    void hydrate()
    return () => {
      canceled = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
    }
  }, [currentId, refreshCurrent])

  useEffect(() => {
    if (restoredTaskScopeHandled || !projectsReady) return
    const restored = restoredNavigationRef.current
    const storedScope = restored?.taskScope
    if (!restored || currentId !== restored.projectId) {
      setRestoredTaskScopeHandled(true)
      return
    }
    if (!current || hydratedProjectId !== currentId) return

    const restoreFormal = restored.view === 'wizard'
    const restoreQuick = restored.view === 'quick'
    const restoreAnnouncement = restored.view === 'announcement'
    let restoreStoredStep = restored.view !== 'wizard'

    if (restoreFormal) {
      const exactTask = storedScope?.kind === 'formal'
        ? formalTranslationTasks(current).find((task) => task.translationTaskId === storedScope.taskId) || null
        : null
      const task = exactTask || findActiveFormalTask(current) || findUnfinishedFormalTask(current)
      if (task) {
        openFormalTaskInWizard(current, task, '\u5df2\u6062\u590d\u5237\u65b0\u524d\u7684\u7ffb\u8bd1\u4efb\u52a1\u3002')
        if (exactTask) {
          const session = translationTaskSessionsRef.current.get(current.id)
          if (session) translationTaskSessionsRef.current.set(current.id, { ...session, step: restored.step })
          restoreStoredStep = true
        }
      } else {
        beginFreshTranslationTask(current)
      }
    } else if (restoreQuick) {
      const lifecycle = selectQuickTaskLifecycle(current.runs || [])
      const exactGroup = storedScope?.kind === 'quick'
        ? lifecycle.groups.find((group) => (
            !group.terminal
            && group.taskId === storedScope.taskId
            && group.runs.some((run) => run.id === storedScope.runId)
          )) || null
        : null
      const group = exactGroup || lifecycle.activeTask || lifecycle.stoppedTasks[0] || null
      if (group) {
        const preferredRunId = exactGroup && storedScope?.kind === 'quick' ? storedScope.runId : ''
        openQuickTaskGroup(current, group, '\u5df2\u6062\u590d\u5237\u65b0\u524d\u7684\u5feb\u901f\u4efb\u52a1\u3002', preferredRunId)
      } else {
        openQuickTaskGroup(current, null, '\u65b0\u7684\u5feb\u901f\u4efb\u52a1\u5df2\u5c31\u7eea\u3002')
      }
    } else if (restoreAnnouncement) {
      const tasks = current.announcement_tasks || []
      const exactTask = storedScope?.kind === 'announcement'
        ? tasks.find((task) => task.id === storedScope.taskId && task.status !== 'canceled') || null
        : null
      const lifecycle = selectAnnouncementTaskLifecycle(tasks)
      const task = exactTask || lifecycle.activeTask || lifecycle.stoppedTasks[0] || null
      openAnnouncementTask(task || undefined, task
        ? '\u5df2\u6062\u590d\u5237\u65b0\u524d\u7684\u516c\u544a\u4efb\u52a1\u3002'
        : '\u65b0\u7684\u516c\u544a\u4efb\u52a1\u5df2\u5c31\u7eea\u3002')
    }

    setView(restored.view)
    setTab(restored.tab)
    if (restoreStoredStep) setStep(restored.step)
    setRestoredTaskScopeHandled(true)
  }, [
    restoredTaskScopeHandled,
    projectsReady,
    currentId,
    hydratedProjectId,
    current,
    beginFreshTranslationTask,
    openFormalTaskInWizard,
    openQuickTaskGroup,
    openAnnouncementTask,
  ])

  useEffect(() => {
    if (currentId) projectNavigationRef.current.set(currentId, { view, tab, step })
  }, [currentId, view, tab, step])

  useEffect(() => {
    if (!restoredTaskScopeHandled || !currentId || view !== 'wizard' || hydratedProjectId !== currentId) return
    const session = translationTaskSessionsRef.current.get(currentId)
    if (!session) return
    translationTaskSessionsRef.current.set(currentId, {
      ...session,
      step,
      sourceArtifactId: scopedSourceArtifact?.id || '',
      selectedLanguages,
    })
  }, [restoredTaskScopeHandled, currentId, hydratedProjectId, view, step, scopedSourceArtifact?.id, selectedLanguages.join('|')])

  useEffect(() => {
    if (!projectsReady || !restoredTaskScopeHandled || !currentId) return
    let taskScope: SessionTaskScope | undefined
    if (view === 'wizard') {
      taskScope = translationTaskId ? { kind: 'formal', taskId: translationTaskId } : undefined
    } else if (view === 'quick') {
      const session = quickTaskSession?.projectId === currentId ? quickTaskSession : null
      const group = session && current
        ? selectQuickTaskLifecycle(current.runs || []).groups.find((item) => item.taskId === session.taskId) || null
        : null
      const initialRun = session && quickTaskInitialRun
        && quickTaskInitialRun.project_id === currentId
        && quickTaskIdOfRun(quickTaskInitialRun) === session.taskId
        ? quickTaskInitialRun
        : null
      const run = initialRun || group?.activeRun || group?.latestRun || null
      taskScope = session && run ? { kind: 'quick', taskId: session.taskId, runId: run.id } : undefined
    } else if (view === 'announcement') {
      taskScope = announcementFocusTaskId ? { kind: 'announcement', taskId: announcementFocusTaskId } : undefined
    }
    writeSessionNavigation({ projectId: currentId, view, tab, step, ...(taskScope ? { taskScope } : {}) })
  }, [
    projectsReady,
    restoredTaskScopeHandled,
    currentId,
    current,
    view,
    tab,
    step,
    translationTaskId,
    quickTaskSession,
    quickTaskInitialRun,
    announcementFocusTaskId,
  ])

  const activeRunPolling = Boolean(pollingLatestRun && ['queued', 'running'].includes(pollingLatestRun.status))
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
    const detail = quickTaskDetailRef.current
    const focusedQuickRun = view === 'overview' && detail.projectId === current.id
      ? (current.runs || []).find((run) => isQuickTaskRun(run) && run.id === detail.runId)
        || (!detail.runId
          ? (current.runs || []).find((run) => isQuickTaskRun(run) && quickTaskIdOfRun(run) === detail.taskId)
          : null)
        || null
      : null
    if (view === 'announcement') {
      const focusedTaskId = announcementFocusTaskIdRef.current
      const latestAnnouncementRun = focusedTaskId
        ? (current.runs || []).find((run) => String(run.metadata?.task_id || run.metadata?.announcement_task_id || '') === focusedTaskId) || null
        : null
      setLatestRun(latestAnnouncementRun ? { ...latestAnnouncementRun, artifacts: runArtifacts(current, latestAnnouncementRun.id) } : null)
    } else if (view === 'quick') {
      setLatestRun(null)
    } else if (focusedQuickRun) {
      const hydratedRun = { ...focusedQuickRun, artifacts: runArtifacts(current, focusedQuickRun.id) }
      const inputArtifactId = String(focusedQuickRun.metadata?.input_artifact_id || '')
      const inputArtifact = artifacts.find((artifact) => artifact.id === inputArtifactId) || null
      setLatestRun(hydratedRun)
      setQaArtifact(preferredTranslationResultArtifact(current, hydratedRun) || inputArtifact)
    } else if (session) {
      const source = artifacts.find((artifact) => artifact.id === session.sourceArtifactId) || null
      const task = formalTranslationTasks(current).find((item) => item.id === session.id) || null
      const hydratedRun = task ? { ...task.latestRun, artifacts: runArtifacts(current, task.latestRun.id) } : null
      setSourceArtifact(source)
      setPrimaryLanguages(session.selectedLanguages, normalizeLanguageCode(hydratedRun?.language) || session.selectedLanguages[0])
      setLatestRun(hydratedRun)
      setQaArtifact(hydratedRun ? preferredTranslationResultArtifact(current, hydratedRun) : null)
      setStep(session.step)
    } else {
      const latestProjectRun = (current.runs || []).find((run) => !isQuickTaskRun(run)) || null
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
  }, [current?.id, current?.artifacts?.length, current?.runs?.length, view, announcementSessionGeneration, setPrimaryLanguages])

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
    if (!actionLatestRun || !['failed', 'needs_input'].includes(actionLatestRun.status) || !isCurrentActionRunScope(actionLatestRun)) {
      setQualityIssues([])
      return
    }
    loadQualityIssues(actionLatestRun.id, actionLatestRun.project_id, () => isCurrentActionRunScope(actionLatestRun))
  }, [actionLatestRun?.id, actionLatestRun?.status, isCurrentActionRunScope])

  useRunStatusPolling(
    pollingLatestRun,
    tab,
    selectedLanguage,
    isCurrentProject,
    isCurrentActionRunScope,
    setActionLatestRun,
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

  useAnnouncementTaskPolling(
    current,
    announcementFocusTaskId,
    announcementSessionGeneration,
    refreshProjectSnapshot,
    isCurrentProject,
    isCurrentAnnouncementSession,
    setBusyForProject,
    setStatusForProject,
  )

  const isCloudDeployment = runtimeVersion?.deployment_mode === 'cloud'
  const showSettingsButton = !__HIDE_SETTINGS__ && runtimeVersion?.deployment_mode === 'local' && can(ADMIN)
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
              <ActiveJobsBadge queues={jobQueues} open={activeJobsPanelOpen} onToggle={() => setActiveJobsPanelOpen((value) => !value)} />
              {activeJobsPanelOpen ? <ActiveJobsPanel queues={jobQueues} onClose={() => setActiveJobsPanelOpen(false)} onCancel={cancelQueueJob} /> : null}
            </div>
            <span
              className={versionMismatch ? 'runtime-version-badge version-mismatch' : 'runtime-version-badge'}
              title={versionMismatch
                ? `前端 v${bundleVersion} 与后端 v${backendVersion} 版本不一致，请刷新页面或重新部署前端`
                : (runtimeVersion?.git_sha ? `commit ${runtimeVersion.git_sha}` : 'current deployment version')}
            >
              {versionMismatch ? `v${bundleVersion} / 后端 v${backendVersion} 版本不一致` : `v${bundleVersion}`}
            </span>
            {!authEnabled ? <OperatorIdentityControl /> : null}
            {showSettingsButton ? <button className="btn btn-ghost" onClick={() => setSettingsOpen(true)}><Settings size={16} aria-hidden="true" />设置</button> : null}
            {authEnabled && can(ADMIN) ? <button className="btn btn-ghost" data-testid="open-user-management" onClick={() => setUserManagementOpen(true)}><UserCog size={16} aria-hidden="true" />用户管理</button> : null}
            {authEnabled && user ? (
              <div className="current-user-chip" data-testid="current-user-chip">
                <span className="current-user-name">{user.display_name || user.username}</span>
                <span className="badge current-user-role">{roleBadgeLabel(user.role)}</span>
                <button className="btn btn-ghost btn-sm" onClick={() => { void logout() }}><LogOut size={14} aria-hidden="true" />退出</button>
              </div>
            ) : null}
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
                  backgroundTaskCount={projectQueueJobCount(jobQueues, project.id)}
                  isActive={project.id === currentId}
                  isDeleteHold={deleteHoldProjectId === project.id}
                  canDelete={can(PROJECT_MANAGE)}
                  onPointerDown={handleProjectPointerDown}
                  onPointerUp={cancelProjectDeleteHold}
                  onPointerLeave={cancelProjectDeleteHold}
                  onPointerCancel={cancelProjectDeleteHold}
                  onSelect={(project, event) => {
                    const saved = projectNavigationRef.current.get(project.id)
                    selectProject(project, event)
                    if (event.defaultPrevented || project.id === currentId) return
                    invalidateQuickTaskSession(project.id)
                    setView(saved?.view === 'quick' ? 'overview' : (saved?.view || 'overview'))
                    setTab(saved?.tab || 'meta')
                    setStep(saved?.step || 1)
                  }}
                />
              ))}
            </div>
            {can(PROJECT_READ) ? <button className="new-project-btn" onClick={() => setNewProjectOpen(true)}><Plus size={15} aria-hidden="true" />新建项目</button> : null}
            <div className="sidebar-title quick"><Zap size={15} aria-hidden="true" />快捷入口</div>
            <button className="project-item quick-entry" onClick={() => {
              if (!current) return
              void openNewTranslationTask()
            }} disabled={!current || projectContextLoading || !can(TASK_RUN)}>
              <span className="pname"><WandSparkles size={16} aria-hidden="true" />新翻译任务</span>
              <span className="pmeta">基于当前项目启动工作流</span>
            </button>
            <button className="project-item quick-entry" data-testid="quick-task-entry" onClick={() => {
              if (!current) return
              void openNewQuickTask()
            }} disabled={!current || projectContextLoading || !can(TASK_RUN)}>
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
                focusedQuickRunId={quickTaskDetailRef.current.projectId === current.id ? quickTaskDetailRef.current.runId : undefined}
                focusedQuickReadOnly={Boolean(
                  quickTaskDetailRef.current.projectId === current.id
                  && scopedLatestRun
                  && isQuickTaskRun(scopedLatestRun)
                  && (!quickTaskIdOfRun(scopedLatestRun) || quickTaskIsTerminalState(String(scopedLatestRun.metadata?.translation_task_state || '')))
                )}
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
                onOpenActivityRun={openRunInOverview}
                onStartTask={() => { void openNewTranslationTask() }}
                onStartAnnouncement={() => { void openNewAnnouncementTask() }}
                onStartQuickTask={() => { void openNewQuickTask() }}
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
                {view === 'quick' && quickTaskSession?.projectId === current.id ? (
                  <QuickTaskWizard
                    key={`${quickTaskSession.projectId}:${quickTaskSession.generation}`}
                    project={current}
                    busy={busy}
                    status={status}
                    jobQueues={jobQueues}
                    settings={settings}
                    scope={quickTaskSession}
                    initialRun={quickTaskInitialRun}
                    onBack={() => {
                      beginQuickTaskSession(current.id, `quick-idle-${createQuickTaskId()}`)
                      quickTaskDetailRef.current = { projectId: '', taskId: '', runId: '' }
                      setBusy(false)
                      setStatusForProject(current.id, '准备就绪')
                      setView('overview')
                    }}
                    onStartNextTask={() => { void openNewQuickTask() }}
                    onUploadFile={(file, kind, accept) => upload(file, kind, '', accept)}
                    onStartQuickTask={async (payload) => {
                      const run = await startQuickTask(payload)
                      if (run && quickTaskSession && isCurrentQuickTaskSession(quickTaskSession) && quickTaskIdOfRun(run) === quickTaskSession.taskId) {
                        setQuickTaskInitialRun(run)
                      }
                      return run
                    }}
                    onRefreshProject={async (scope) => {
                      const loaded = await refreshCurrent(scope.projectId).catch(() => null)
                      return isCurrentQuickTaskSession(scope) ? loaded : null
                    }}
                    onContinueTask={(group) => openQuickTaskGroup(current, group, '已继续选中的快速任务。')}
                    onViewResult={(run) => { if (run) openRunInOverview(run) }}
                    isCurrentScope={isCurrentQuickTaskSession}
                  />
                ) : view === 'quick' ? (
                  <span className="loading">正在恢复快速任务...</span>
                ) : view === 'announcement' ? (
                  <AnnouncementWizard
                    key={`${current.id}:${announcementSessionGeneration}`}
                    project={current}
                    busy={busy}
                    status={status}
                    jobQueues={jobQueues}
                    selectedLanguage={selectedLanguage}
                    setSelectedLanguage={setSelectedLanguage}
                    assetArtifacts={scopedAssetArtifacts}
                    announcementText={announcementText}
                    setAnnouncementText={setAnnouncementText}
                    lookupResult={announcementLookupResult}
                    onUploadAsset={uploadAnnouncementAsset}
                    onUploadConstraint={uploadAnnouncementConstraint}
                    onUploadTermsFile={uploadAnnouncementTermsFile}
                    onCreateTask={createAnnouncementTask}
                    onTaskAction={runAnnouncementTaskAction}
                    onLookup={runAnnouncementLookup}
                    onBack={() => { setStatusForProject(current.id, '准备就绪'); setView('overview') }}
                    onStartNext={() => { void openNewAnnouncementTask() }}
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
                    jobQueues={jobQueues}
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

      {newProjectOpen && can(PROJECT_READ) ? <NewProjectModal onClose={() => setNewProjectOpen(false)} onCreate={createProject} /> : null}
      {deleteProjectTarget && can(PROJECT_MANAGE) ? <DeleteProjectModal project={deleteProjectTarget} busy={busy} onClose={() => { longPressTriggeredProjectId.current = ''; setDeleteProjectTarget(null) }} onDelete={deleteProject} /> : null}
      {announcementCancelTarget ? <CancelAnnouncementTaskModal task={announcementCancelTarget} busy={busy} onClose={() => { longPressTriggeredAnnouncementTaskId.current = ''; setAnnouncementCancelTarget(null) }} onCancelTask={cancelAnnouncementTask} /> : null}
      {settingsOpen && can(ADMIN) ? <SettingsModal onClose={() => { setSettingsOpen(false); refreshSettings() }} /> : null}
      {userManagementOpen && user && can(ADMIN) ? <UserManagementModal currentUserId={user.id} onClose={() => setUserManagementOpen(false)} /> : null}
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
window.__lwsRoot.render(
  <AuthProvider>
    <AuthGate>
      <App />
    </AuthGate>
  </AuthProvider>
)
